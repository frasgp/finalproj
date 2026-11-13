"""Shared research metadata schema for seed and reference API downloads."""
from datetime import datetime, timezone

METADATA_VERSION = 4
# Keep API names and nested structures for analysis without another lookup.
METADATA_FIELDS = (
    'publication_date', 'type', 'language', 'ids', 'biblio',
    'cited_by_count', 'counts_by_year', 'referenced_works_count',
    'fwci', 'citation_normalized_percentile', 'cited_by_percentile_year',
    'is_retracted',
    'authorships', 'corresponding_author_ids', 'corresponding_institution_ids',
    'countries_distinct_count', 'institutions_distinct_count',
    'primary_location', 'open_access', 'best_oa_location',
    'primary_topic', 'topics', 'keywords', 'mesh',
    'indexed_in', 'has_fulltext', 'has_content', 'content_urls',
    'created_date', 'updated_date',
)
WORK_FIELDS = ','.join(dict.fromkeys((
    'id', 'doi', 'publication_year', 'title', 'referenced_works',
    'abstract_inverted_index', *METADATA_FIELDS,
)))


def reconstruct_abstract(index):
    positions = {p: word for word, locations in (index or {}).items() for p in locations}
    return ' '.join(positions[p] for p in sorted(positions))


def normalize_work(work: dict):
    """Preserve analysis aliases plus rich metadata; absent is not zero/false."""
    source = ((work.get('primary_location') or {}).get('source') or {})
    authorships = work.get('authorships')
    refs = work.get('referenced_works')
    referenced: int = sum([int(d.get("cited_by_count")) for d in work.get("counts_by_year", [])])
    # row = {field: work.get(field) for field in METADATA_FIELDS}
    row = dict()
    row.update(
        id=work['id'].rsplit('/', 1)[-1],
        doi=(work.get('doi') or '').strip().removeprefix('https://doi.org/').lower(),
        year=work.get('publication_year'), 
        title=work.get('title') or '',
        abstract=reconstruct_abstract(work.get('abstract_inverted_index')),
        source=(source.get('id') or '').rsplit('/', 1)[-1],
        authors=None if authorships is None else [
            a['author']['id'].rsplit('/', 1)[-1] for a in authorships
            if (a.get('author') or {}).get('id')],
        refs=None if refs is None else [r.rsplit('/', 1)[-1] for r in refs],
        referenced=referenced,
        topics=[{"id":t["id"], "score":t["score"]} for t in work.get("topics", {})],
        keywords=[d["display_name"] for d in work.get("keywords", {})],
        type=work.get("type"),
        is_retracted=work.get("is_retracted"),
        # metadata_version=METADATA_VERSION,
        # metadata_fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    return row
