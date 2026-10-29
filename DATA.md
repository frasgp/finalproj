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
