"""Fetch a journal/year slice of OpenAlex works with checkpointed cursor paging.

The free API allows ~1000 credits/day per IP (1 credit per 200-work page), so
fetching is resumable: each page is appended to a JSONL shard and the cursor is
saved. Set OPENALEX_API_KEY for a larger budget.
"""
import json
import os
import time
from pathlib import Path

import requests

API = "https://api.openalex.org"
WORK_FIELDS = "id,doi,publication_year,title,authorships,referenced_works,abstract_inverted_index,primary_location"


def reconstruct_abstract(inverted_index):
    """Rebuild abstract text from OpenAlex's {word: [positions]} index."""
    if not inverted_index:
        return ""
    positions = {pos: word for word, locs in inverted_index.items() for pos in locs}
    return " ".join(positions[i] for i in sorted(positions))


def slim_work(work):
    """Keep only the fields the pipeline needs (drops heavy nested metadata)."""
    loc = work.get("primary_location") or {}
    source = (loc.get("source") or {})
    return {
        "id": work["id"].rsplit("/", 1)[-1],
        "doi": (work.get("doi") or "").replace("https://doi.org/", "").lower(),
        "year": work.get("publication_year"),
        "title": work.get("title") or "",
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")),
        "authors": [a["author"]["id"].rsplit("/", 1)[-1] for a in work.get("authorships", []) if a.get("author", {}).get("id")],
        "source": (source.get("id") or "").rsplit("/", 1)[-1],
        "refs": [r.rsplit("/", 1)[-1] for r in work.get("referenced_works", [])],
    }


def _params(extra=None):
    params = dict(extra or {})
    if os.environ.get("OPENALEX_API_KEY"):
        params["api_key"] = os.environ["OPENALEX_API_KEY"]
    return params


def resolve_source(name):
    """Return (source_id, display_name) of the best OpenAlex match for a journal name."""
    resp = requests.get(f"{API}/sources", params=_params({"search": name, "per-page": 3, "select": "id,display_name,works_count"}), timeout=30)
    resp.raise_for_status()
    results = resp.json()["results"]
    if not results:
        raise LookupError(f"No OpenAlex source for {name!r}")
    top = results[0]
    return top["id"].rsplit("/", 1)[-1], top["display_name"], top["works_count"]


def fetch_slice(source_ids, years, out_dir, min_remaining=15):
    """Fetch every (source, year) query with basic page= paging (no API key needed;
    each query must stay under OpenAlex's 10,000-result limit). Resumable: finished
    queries are recorded in state.json. Returns True when everything is downloaded."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / "state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    done = set(state.get("done", []))
    shard = out_dir / "works.jsonl"
    for source in source_ids:
        for year in range(years[0], years[1] + 1):
            key = f"{source}:{year}"
            if key in done:
                continue
            flt = f"primary_location.source.id:{source},publication_year:{year}"
            page, rows = 1, []
            while True:
                resp = requests.get(
                    f"{API}/works",
                    params=_params({"filter": flt, "per-page": 200, "page": page, "select": WORK_FIELDS}),
                    timeout=120,
                )
                if resp.status_code == 429:
                    print("rate limited; finished queries kept, resume later")
                    return False
                resp.raise_for_status()
                results = resp.json()["results"]
                rows.extend(slim_work(w) for w in results)
                remaining = int(resp.headers.get("x-ratelimit-remaining", 999))
                if len(results) < 200:
                    break
                if remaining < min_remaining:
                    print(f"budget nearly exhausted ({remaining} credits); resume later")
                    return False
                page += 1
                time.sleep(0.1)
            with shard.open("a") as fh:  # written only once a query fully finished
                fh.writelines(json.dumps(r) + "\n" for r in rows)
            done.add(key)
            state_path.write_text(json.dumps({"done": sorted(done)}))
            print(key, len(rows), "remaining credits", remaining, flush=True)
    return True
