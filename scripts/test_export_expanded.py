import gzip
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from export_expanded import export, sha256


class ExportTests(unittest.TestCase):
    def test_merge_aliases_unknowns_and_repeatability(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            seeds = root / 'seed.jsonl'
            seeds.write_text(json.dumps({'id': 'W1', 'refs': ['W2'], 'authors': []}) + '\n')
            original = seeds.read_bytes()
            database = root / 'references.sqlite'
            with sqlite3.connect(database) as db:
                db.executescript('''CREATE TABLE meta(key TEXT,value TEXT);
                    CREATE TABLE targets(id TEXT,canonical_id TEXT,payload TEXT,
                                         status TEXT,fetched_at TEXT);''')
                db.execute('INSERT INTO meta VALUES (?,?)', ('seed_sha256', sha256(seeds)))
                for requested, canonical, status in [
                    ('W2', 'W3', 'fetched'), ('W3', 'W3', 'no_abstract'),
                    ('W4', 'W1', 'fetched'), ('W5', 'W5', 'no_abstract')]:
                    db.execute('INSERT INTO targets VALUES (?,?,?,?,?)',
                               (requested, canonical, json.dumps({
                                   'id': canonical, 'doi': 'https://doi.org/10.A/TEST',
                                   'abstract': 'text' if status == 'fetched' else ''}),
                                status, '2026-01-01'))
                db.execute("INSERT INTO targets VALUES ('W6',NULL,NULL,'pending',NULL)")
            output, manifest = export(seeds, database, root / 'out')
            with gzip.open(output / 'works.jsonl.gz', 'rt') as stream:
                rows = [json.loads(line) for line in stream]
            self.assertEqual([r['id'] for r in rows], ['W1', 'W3', 'W5'])
            self.assertEqual(rows[1]['abstract'], 'text')
            self.assertEqual(rows[1]['doi'], '10.a/test')
            self.assertIsNone(rows[1]['refs'])
            self.assertEqual(rows[0]['record_origin'], 'seed')
            self.assertEqual(json.loads((output / 'aliases.json').read_text()),
                             {'W2': 'W3', 'W4': 'W1'})
            self.assertEqual(manifest['counts']['duplicate_references_skipped'], 2)
            self.assertEqual(export(seeds, database, root / 'out')[0], output)
            self.assertEqual(seeds.read_bytes(), original)
            (output / 'works.jsonl.gz').write_bytes(b'broken')
            with self.assertRaisesRegex(ValueError, 'damaged'):
                export(seeds, database, root / 'out')
            seeds.write_text('{}\n')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                export(seeds, database, root / 'out')
            self.assertFalse(list((root / 'out').glob('.export-*')))


if __name__ == '__main__':
    unittest.main()
