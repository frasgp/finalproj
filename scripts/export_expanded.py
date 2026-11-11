"""Export a consistent, deduplicated seed + reference snapshot without changing seeds."""
import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def encode(row):
    return (json.dumps(row, sort_keys=True, ensure_ascii=False) + '\n').encode('utf-8')


def export(seeds, database, destination):
    seeds, database, destination = map(Path, (seeds, database, destination))
    seed_digest = sha256(seeds)
    destination.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.export-', dir=destination))
    db = None
    try:
        db = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
        db.execute('BEGIN')  # One committed view, even while the fetcher continues.
        metadata = dict(db.execute('SELECT key,value FROM meta'))
        if metadata.get('seed_sha256') != seed_digest:
            raise ValueError('Expansion database does not match the seed SHA-256.')
        statuses = dict(db.execute('SELECT status,COUNT(*) FROM targets GROUP BY status'))
        aliases = {}
        for requested, canonical in db.execute(
                "SELECT id,canonical_id FROM targets WHERE status IN ('fetched','no_abstract')"):
            if not canonical:
                raise ValueError(f'Missing canonical ID for {requested}')
            if requested != canonical:
                aliases[requested] = canonical
        (staging / 'aliases.json').write_bytes(encode(aliases))
        seen = set()
        counts = {'seed': 0, 'reference': 0, 'duplicate_references_skipped': 0}
        with open(staging / 'works.jsonl.gz', 'wb') as raw:
            with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as out:
                with open(seeds, encoding='utf-8') as source:
                    for line in source:
                        if not line.strip():
                            continue
                        row = json.loads(line)
                        if row['id'] in seen:
                            raise ValueError(f'Duplicate seed ID: {row["id"]}')
                        seen.add(row['id'])
                        row['record_origin'] = 'seed'
                        out.write(encode(row))
                        counts['seed'] += 1
                # Prefer an abstract, then the latest fetch, then requested ID.
                rows = db.execute("""SELECT id,canonical_id,payload FROM targets
                    WHERE status IN ('fetched','no_abstract')
                    ORDER BY canonical_id, CASE status WHEN 'fetched' THEN 0 ELSE 1 END,
                             fetched_at DESC,id""")
                for requested, canonical, payload in rows:
                    row = json.loads(payload)
                    if row['id'] != canonical:
                        raise ValueError(f'Payload ID mismatch for {requested}')
                    if canonical in seen:
                        counts['duplicate_references_skipped'] += 1
                        continue
                    seen.add(canonical)
                    row['doi'] = (row.get('doi') or '').removeprefix('https://doi.org/').lower()
                    row.update(record_origin='reference', refs=None, authors=None)
                    out.write(encode(row))
                    counts['reference'] += 1
        if sha256(seeds) != seed_digest:
            raise ValueError('Seeds changed during export; retry with a fixed seed file.')
        manifest = {
            'schema_version': 1,
            'seed_sha256': seed_digest,
            'counts': counts,
            'fetch_status_counts': statuses,
            'scope': 'one-hop outgoing; reference rows are context, not study subjects',
            'unknown_fields': 'Reference refs/authors are null because they were not fetched.',
            'files': {name: {'sha256': sha256(staging / name),
                             'bytes': (staging / name).stat().st_size}
                      for name in ('works.jsonl.gz', 'aliases.json')},
        }
        snapshot_id = hashlib.sha256(encode(manifest)).hexdigest()
        manifest['snapshot_id'] = snapshot_id
        (staging / 'manifest.json').write_bytes(encode(manifest))
        final = destination / snapshot_id
        if final.exists():
            for name in ('manifest.json', 'works.jsonl.gz', 'aliases.json'):
                if sha256(final / name) != sha256(staging / name):
                    raise ValueError(f'Existing snapshot is damaged: {final / name}')
        else:
            staging.rename(final)
        return final, manifest
    finally:
        if db is not None:
            db.close()
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--seeds', type=Path, default=ROOT / 'data/raw/openalex/works.jsonl')
    parser.add_argument('--db', type=Path, default=ROOT / 'reference_expansion/data/references.sqlite')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'data/raw/openalex/snapshots')
    args = parser.parse_args()
    path, manifest = export(args.seeds, args.db, args.output_dir)
    print(json.dumps({'snapshot': str(path), **manifest}, indent=2))


if __name__ == '__main__':
    main()
