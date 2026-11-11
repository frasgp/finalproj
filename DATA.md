# Data guide: raw OpenAlex pull and Retraction Watch labels

Audited 2026-10-29 against the pull of 2026-10-21. This repo holds a copy of the raw data and the
code needed to pull and load it: `scripts_fetch.py`, and `src/` (`openalex_fetch.py`, `slice_config.py`,
`rw_labels.py`, `dataset.py`). Run everything from the repo root. The copies are byte-identical to the
originals in the `cartel-detection` project (checked with `cmp` for the two big data files).

## 1. What the data is

| Part | What | Size |
|---|---|---|
| OpenAlex works | Journal articles from 13 journals, 2019-2022 | 51,091 rows |
| Retraction Watch | Retraction records, joined to works by DOI | 61,843 usable records (retractions with a DOI) |

- **Raw OpenAlex file:** `data/raw/openalex/works.jsonl` (about 90 MB, one JSON object per line).
- **Raw Retraction Watch file:** `data/raw/retraction-watch-data/retraction_watch.csv`. It is a clone of the public Retraction Watch dataset, read as `cp1252`.
- **Progress file:** `data/raw/openalex/state.json` records which source-year queries are finished.
- **Pull log:** `data/raw/fetch.log`.

## 2. How the OpenAlex data was pulled

**Slice (fixed in `src/slice_config.py`):** 13 journals x 4 years (2019-2022) = 52 queries.

**HIGH_LABEL journals** (CS-adjacent, many manipulation retractions):

| OpenAlex ID | Journal | Publisher |
|---|---|---|
| S178238111 | Mathematical Problems in Engineering | Hindawi |
| S179157397 | Journal of Intelligent & Fuzzy Systems | IOS Press |
| S207319443 | Complexity | Hindawi |
| S235346 | Wireless Communications and Mobile Computing | Wiley |
| S72372694 | Computational Intelligence and Neuroscience | Hindawi |
| S65753830 | Soft Computing | Springer |
| S120683614 | Security and Communication Networks | Hindawi |
| S152111507 | Mobile Information Systems | IOS Press |
| S36625193 | Journal of Healthcare Engineering | Hindawi |
| S96783963 | Journal of Sensors | Hindawi |

**CONTROL journals** (large, rarely retracted, used as negatives):

| OpenAlex ID | Journal | Publisher |
|---|---|---|
| S192650101 | Information Sciences | Elsevier |
| S10169007 | Knowledge-Based Systems | Elsevier |
| S414566 | Pattern Recognition | Elsevier |

**Query (one per journal-year):**

```
GET https://api.openalex.org/works
    ?filter=primary_location.source.id:{SOURCE_ID},publication_year:{YEAR}
    &per-page=200&page={1,2,...}
    &select=id,doi,publication_year,title,authorships,referenced_works,abstract_inverted_index,primary_location
```

**Mechanics:**
- Each journal-year is paged with `page=` until a page returns fewer than 200 works. A single journal-year stays under OpenAlex's 10,000-result paging limit.
- A journal-year is written to `works.jsonl` only after it finishes, then recorded in `state.json`. If the run stops (HTTP 429, or fewer than 15 credits left), re-running skips finished journal-years.
- The free API allows about 1,000 credits per day per IP, at 1 credit per 200-work page. The whole pull used about 273. No API key was needed. Set `OPENALEX_API_KEY` for a bigger budget.
- Each work is slimmed to 8 fields on the way in (see section 3).

**To reproduce:**

```bash
pip install requests pandas
python scripts_fetch.py        # exit 0 + "COMPLETE" when done; rerun if "INCOMPLETE"
```

**Retraction Watch:** `git clone https://gitlab.com/crossref/retraction-watch-data` into `data/raw/retraction-watch-data/`. Our copy was cloned on 2026-10-21. Note the CSV and README are copied into this repo, but not the upstream `.git` folder.

## 3. How the data looks

### Sharing the expanded dataset

Keep `data/raw/openalex/works.jsonl` as the fixed seed cohort. The expansion
database checks its SHA-256 before resuming; appending there would invalidate
that check and change the study population in existing notebooks.

From the project root, run (Python 3.9+; standard library only):

```bash
python3 scripts/export_expanded.py
```

This exports the seeds followed by successfully retrieved references into
`data/raw/openalex/snapshots/<snapshot-id>/works.jsonl.gz`. Each directory also
contains `aliases.json` (requested ID to canonical ID) and `manifest.json`
(input checksum, counts, fetch coverage, output sizes and SHA-256 checksums).
The script reads one consistent SQLite transaction, including committed WAL
data, so fetching can continue. It publishes a complete directory atomically.
Re-exporting identical inputs reuses the same snapshot; later fetches produce
a new snapshot. The SQLite file and original JSONL are not modified.

Canonical OpenAlex IDs are deduplicated, with seed records taking precedence.
Among duplicate references, prefer a nonempty abstract, then the latest fetch.
Missing abstracts are retained; pending/omitted/404 records are not exported.
DOIs use the seed format. `record_origin` is `seed` or `reference`.
For references, `refs` and `authors` are **null (not fetched)**, not empty lists.
Resolve cited IDs through `aliases.json` when matching citation targets.

Read with `pd.read_json(snapshot_path / "works.jsonl.gz", lines=True)`.
Filter `record_origin == "seed"` for study subjects. Do not pass the full combined
file into `load_labeled_works()` as a replacement cohort: reference-only papers
are context, and missing labels must not turn them into control subjects.
The existing expansion notebooks still use SQLite; this export is a portable
corpus for collaboration, not a fetch-resume or embedding-cache backup.

Recommended two-person workflow:

1. Designate one person to fetch and publish a snapshot at agreed milestones.
2. Commit the exporter and the snapshot's small `manifest.json`. Payloads are
   ignored by Git. Record a release tag/download location in the commit or PR.
3. Upload `works.jsonl.gz`, `aliases.json`, and `manifest.json` as assets of a
   versioned GitHub Release (for example `data-2026-11-11-01`). Keep published
   snapshots immutable; use a new release for new data.
4. The collaborator downloads all three files into the matching snapshot folder
   and checks the payload SHA-256 values against the committed manifest:
   `shasum -a 256 works.jsonl.gz aliases.json`.
5. Both people record the same snapshot ID in their analysis results.

GitHub warns above 50 MiB and blocks ordinary Git files above 100 MiB; this is
not a 50 MB plan limit ([GitHub file limits](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)).
Release assets must each be under 2 GiB ([release limits](https://docs.github.com/en/repositories/releasing-projects-on-github/about-releases)).
If exports outgrow that, use versioned object storage or shard release assets.
Git LFS is an alternative for automatic checkout/download, but each changed
version of a large file consumes its full size again in storage, and downloads
consume bandwidth ([LFS billing](https://docs.github.com/en/billing/concepts/product-billing/git-lfs)).
For this growing research corpus, milestone release snapshots are simpler.
Do not split files merely to commit all of them to regular Git: history still
accumulates the data. The original seed JSONL is already tracked; ignoring it
would not remove it from history. Coordinate any later Git/LFS history migration
with your collaborator. This export workflow does not rewrite history.

### `works.jsonl` (one work per line)

| Field | Type | Meaning |
|---|---|---|
| `id` | str | OpenAlex work ID, e.g. `W2963...` (the `https://openalex.org/` prefix is stripped) |
| `doi` | str | Lower-cased DOI without the `https://doi.org/` prefix. Empty string if none |
| `year` | int | Publication year (2019-2022) |
| `title` | str | Title. Empty string if none |
| `abstract` | str | Rebuilt from OpenAlex's inverted index. Empty string if OpenAlex has none |
| `authors` | list[str] | OpenAlex author IDs (`A...`), in author order. Authors without an ID are dropped |
| `source` | str | OpenAlex journal ID (`S...`) of the primary location. This is the journal key |
| `refs` | list[str] | OpenAlex IDs (`W...`) of the works this paper cites (outgoing references only) |

### Labelled table (`src/dataset.py`)

`load_labeled_works()` drops duplicate IDs, left-joins works to Retraction Watch on `doi`, and adds:

| Column | Meaning |
|---|---|
| `paper_mill` | Retraction Watch reason contains "Paper Mill" |
| `peer_review` | Reason contains "Compromised Peer Review" or "Rogue Editor" |
| `referencing` | Reason contains "Referencing/Attributions" (weak proxy; Retraction Watch has no explicit "citation manipulation" reason) |
| `manipulation` | `paper_mill OR peer_review`. This is the primary positive class |
| `high_label_journal` | `source` is one of the 10 HIGH_LABEL journals |

Papers with no Retraction Watch match get `False` for all four labels.
Only records whose `RetractionNature` is "Retraction" and whose DOI starts with `10.` are used.

### Per-journal summary

| Group | Journal | Papers | In Retraction Watch | `manipulation` | Abstract missing |
|---|---|---|---|---|---|
| HIGH | Mathematical Problems in Engineering | 8,820 | 4.0% | 2.1% | 0.6% |
| HIGH | Journal of Intelligent & Fuzzy Systems | 5,646 | 11.9% | 10.2% | 0.9% |
| HIGH | Complexity | 4,448 | 6.0% | 5.9% | 2.5% |
| HIGH | Wireless Communications and Mobile Computing | 4,423 | 17.8% | 9.6% | 1.8% |
| HIGH | Computational Intelligence and Neuroscience | 4,303 | 23.7% | 11.3% | 0.2% |
| HIGH | Soft Computing | 3,734 | 10.5% | 9.0% | **95.5%** |
| HIGH | Security and Communication Networks | 2,727 | 34.4% | 24.8% | 3.6% |
| HIGH | Mobile Information Systems | 2,628 | 14.4% | 8.9% | 0.5% |
| HIGH | Journal of Healthcare Engineering | 2,342 | 45.3% | 27.5% | 0.4% |
| HIGH | Journal of Sensors | 1,826 | 23.4% | 20.5% | 0.8% |
| CONTROL | Information Sciences | 4,468 | 0.0% | 0.0% | **95.1%** |
| CONTROL | Knowledge-Based Systems | 3,417 | 0.03% | 0.0% | **95.0%** |
| CONTROL | Pattern Recognition | 2,309 | 0.0% | 0.0% | **90.6%** |

Overall:
- 6,300 works (12.3%) match a Retraction Watch record.
- Label counts: `paper_mill` 3,675, `peer_review` 1,659, `referencing` 4,927, `manipulation` 4,194.
- Average of 33.4 references and 3.4 authors per paper. The maximum is 400 references and 95 authors.

## 4. Accuracy check

| Check | Result |
|---|---|
| Valid JSON, single schema | 51,091 rows, 0 bad lines |
| Duplicates | 0 duplicate work IDs, 0 duplicate DOIs |
| Stays inside the slice | 0 rows outside 2019-2022, 0 outside the 13 journals |
| Rows vs `fetch.log` | All 52 journal-years match exactly |
| Journal IDs vs names | All 13 match OpenAlex's `display_name` (ISSN-L and publisher also checked) |
| Rows vs live OpenAlex | 47 of 52 journal-years match exactly. The other 5 differ by at most 11 works (local 51,091 vs live 51,064), which looks like index drift in the 8 days since the pull. I did not verify which works changed |
| Missing abstracts | 40 abstract-less papers re-checked live: all 40 also lack an abstract in OpenAlex, so this is a gap at the source and not a pull bug |

Verdict: the pull is complete and accurate for what it queries. The caveats below are limits of the data, not errors in the pull.

## 5. Caveats everyone should know

1. **Label and journal are confounded.** The 3 CONTROL journals have essentially no Retraction Watch labels by construction. A model or statistic that separates positives from negatives can simply be separating Hindawi-style journals from Elsevier journals. Evaluate within journals, or at journal level, and be careful with claims such as "citation excess tracks journal niche, not retractions".
2. **Text is missing for 4 journals.** More than 90% of abstracts are missing for Information Sciences, Knowledge-Based Systems, Pattern Recognition and Soft Computing. Any abstract-based feature (topic coherence, embeddings) is biased by journal, and all three controls lose their text.
3. **Retracted papers are under-labelled.** 1,024 titles start with `RETRACTED:`, but only 798 of them match in Retraction Watch. About 226 retracted papers therefore carry a negative label. Some may be retracted for non-manipulation reasons; I did not check.
4. **Non-research items are included.** The pull has no `type` filter, and about 1,555 titles look like errata, editorials or retraction notices. Live OpenAlex lists 143 `paratext` records in Information Sciences alone. I did not check whether the downstream pipeline drops them.
5. **The citation graph is sparse.** Of 1.71M references, only 2.83% point at papers inside the slice. Only outgoing references were pulled (no `cited_by`). The query filters on `primary_location`, so papers whose primary location is a repository and not the journal are missed.
6. **277 works have no DOI** and can never be matched to Retraction Watch.
7. **`manipulation` overlaps its parts.** `manipulation` is the union of `paper_mill` and `peer_review`, and the two overlap heavily (for example in Journal of Intelligent & Fuzzy Systems, `manipulation` equals `peer_review`, 573, while `paper_mill` is 400).
8. **Snapshot only.** OpenAlex changes over time, so a re-pull will not match this file exactly.

## 6. Tips for loading

```python
import pandas as pd
works = pd.read_json("data/raw/openalex/works.jsonl", lines=True)

# labelled version (run from the repo root)
from src.dataset import load_labeled_works
df = load_labeled_works()
```

- Filter on `source` (not journal name) when selecting a journal.
- Use `abstract != ""` to restrict to papers that have text.
- `authors` and `refs` are Python lists of IDs.

## 7. Let a collaborator fetch references using their own OpenAlex account

The reference-fetching code is **`reference_expansion/pipeline.py`**. Its `fetch`
command requests up to 100 specified OpenAlex work IDs per batch. `--max-requests`
limits actual HTTP attempts, including individual-ID follow-ups and retries; it is
not a promised number of completed 100-paper batches.

The **collaboration wrapper is `scripts/collaborative_fetch.py`**. It splits the
remaining queue into disjoint assignments, reuses the same fetcher, exports
portable result bundles, and merges completed records into the coordinator's
original expansion database. It never appends papers to the original seed file
or `state.json`.

### Account and Python setup (each person)

1. Create your own OpenAlex account, verify your email, and copy your API key from
   [OpenAlex API settings](https://openalex.org/settings/api).
2. In your own terminal, set the key:

   ```bash
   export OPENALEX_API_KEY="your-own-key"
   ```

   Do not put real keys in Git, shared files, screenshots, or result bundles.
   The fetcher reads this environment variable; it does **not** automatically
   load a `.env` file. Set it again in a new terminal session.
3. Activate a Python environment and install the small fetching dependency:

   ```bash
   python3 -m pip install requests
   ```

   Fetching does not require pandas, PyTorch, or sentence-transformers. Those are
   analysis dependencies. If needed, create a local environment first:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   python3 -m pip install requests
   ```

OpenAlex currently documents a free verified key with a larger daily budget than
keyless access. Each person uses their own account allowance; follow the returned
budget/rate-limit headers. New accounts may have initial pacing restrictions.
See [authentication and rate limits](https://help.openalex.org/api/authentication/).
The code saves progress and stops on 429 or the configured budget reserve; it
neither buys additional usage nor automatically restarts after a daily reset.

### Work packages prepared for this dataset

Current plan: **`4684dc08c4e38e46`**, covering 813,691 pending/omitted IDs.

| Person | Assignment file | Unique requested IDs |
|---|---|---:|
| Coordinator (you) | `part-01-of-02.json.gz` | 406,846 |
| Partner | `part-02-of-02.json.gz` | 406,845 |

They are in:

```text
reference_expansion/data/work_packages/4684dc08c4e38e46/
```

Send the partner **part 02** as a file (for example an additional release attachment).
They save it in that same relative directory in their checkout. The work package
is a compressed list of IDs/frequencies plus seed/assignment identity and a
checksum. It contains no API key or original paper text. Do not manually decompress
or edit it for the helper commands.

**Both people must use their assigned queues during this collaboration. Do not
also run the old unrestricted master-queue fetch command**, or it may duplicate
work assigned to your partner. Do not regenerate overlapping work packages while
these assignments are still in use. Use the two packages from the same plan.

### Your commands (coordinator)

Run from finalproj in your selected environment:

```bash
python3 scripts/collaborative_fetch.py init \
  --assignment reference_expansion/data/work_packages/4684dc08c4e38e46/part-01-of-02.json.gz \
  --db reference_expansion/data/coordinator.sqlite

python3 scripts/collaborative_fetch.py fetch \
  --db reference_expansion/data/coordinator.sqlite --max-requests 1000
```

The init step is idempotent. Repeat fetch to resume. For the existing Week1
interpreter, replace `python3` with `../Week1/.venv/bin/python`.

### Partner's commands

After pulling the committed scripts, receiving part 02, installing `requests`,
and setting their own key:

```bash
python3 scripts/collaborative_fetch.py init \
  --assignment reference_expansion/data/work_packages/4684dc08c4e38e46/part-02-of-02.json.gz \
  --db reference_expansion/data/partner.sqlite

python3 scripts/collaborative_fetch.py fetch \
  --db reference_expansion/data/partner.sqlite --max-requests 1000
```

They can repeat fetch on later days. All progress is saved locally. They do not
need your master SQLite database or the original seed data to fetch an assignment;
assignment metadata identifies the expected seed snapshot. The published combined
snapshot is for analysis, not an interchangeable fetch-resume database.

### Share completed results and merge them

The partner can export results before the entire assignment is complete:

```bash
python3 scripts/collaborative_fetch.py export-results \
  --db reference_expansion/data/partner.sqlite \
  --output reference_expansion/outputs/partner-results-01.json.gz
```

They send you that `.json.gz` file, not their API key or live SQLite files. It
contains completed fetched/no-abstract/404 records and provenance, but no embeddings.
Use a new filename for later changed exports (for example `partner-results-02.json.gz`).
Reimporting the same completed records is safe.

Save it under `reference_expansion/outputs/` and merge on your machine:

```bash
python3 scripts/collaborative_fetch.py merge \
  --bundle reference_expansion/outputs/partner-results-01.json.gz
```

Merge your own assignment results too:

```bash
python3 scripts/collaborative_fetch.py export-results \
  --db reference_expansion/data/coordinator.sqlite \
  --output reference_expansion/outputs/coordinator-results-01.json.gz

python3 scripts/collaborative_fetch.py merge \
  --bundle reference_expansion/outputs/coordinator-results-01.json.gz
```

By default, merges update `reference_expansion/data/references.sqlite`. The helper
checks bundle integrity, seed identity, requested-ID membership, and payload/status
consistency, and merges transactionally. Existing fetched abstracts are retained;
results can improve pending/404/no-abstract states. Newer same-quality records are
not automatically substituted: refreshing an existing snapshot is a separate task.
Import history is recorded. Checksums detect accidental corruption, not an
untrustworthy data provider; exchange bundles with your intended collaborator.

Then create the new combined sharing snapshot using the existing exporter:

```bash
python3 scripts/export_expanded.py
```

Publish its `works.jsonl.gz`, `aliases.json`, and `manifest.json` under a new release
tag, and use the same new snapshot ID for both collaborators' analyses. The old
frozen exploratory notebook does not automatically incorporate this newer snapshot.

### Future assignments and what to commit

After both current assignments are finished or explicitly retired and merged,
create a new plan from whatever remains:

```bash
python3 scripts/collaborative_fetch.py split --parts 2
```

It prints the new plan folder and assignment paths. It does not start fetching or
reserve records in the master database; coordination means fetching only the agreed
assignments, not the unrestricted queue at the same time.

Commit the code and instructions needed for collaboration:

```bash
git add DATA.md reference_expansion/.gitignore reference_expansion/pipeline.py
git add scripts/collaborative_fetch.py scripts/test_collaborative_fetch.py
```

For the expanded-snapshot export workflow, also include its existing code/docs:

```bash
git add .gitignore scripts/export_expanded.py scripts/test_export_expanded.py
git add data/raw/openalex/snapshots/*/manifest.json
```

Review `git diff --cached --stat` before committing. Do **not** stage the entire
`reference_expansion/` folder unless you also intend to publish all the analysis
notebooks and helper code. Work packages, databases, and result bundles are under
ignored `data/` or `outputs/` directories; exchange them as files, not ordinary Git
objects. Nothing in this workflow uploads files or commits on your behalf.
