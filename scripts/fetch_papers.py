"""Simple OpenAlex JSONL collection: seeds, split, fetch, combine. Uses certifi when available for HTTPS trust."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import sqlite3
import ssl
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.openalex_schema import WORK_FIELDS, METADATA_VERSION, normalize_work


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def read_rows(path):
    with Path(path).open() as f:
        for n,line in enumerate(f,1):
            if line.strip():
                try:yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f'Invalid JSON in {path} line {n}; restore/repair the last partial line before resuming') from exc


def write_json(path, obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(obj,indent=2)+'\n');temp.replace(path)


class Stop(Exception):pass


def tls_context():
    # Respect explicitly configured institution/proxy trust stores.
    if os.environ.get('SSL_CERT_FILE') or os.environ.get('SSL_CERT_DIR'):
        return ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        return ssl.create_default_context()
    return ssl.create_default_context(cafile=certifi.where())


class Client:
    def __init__(self, limit):
        self.limit=limit;self.calls=0
        self.context=tls_context()
    def get(self, endpoint, params):
        params=dict(params)
        if os.environ.get('OPENALEX_API_KEY'):params['api_key']=os.environ['OPENALEX_API_KEY']
        url='https://api.openalex.org/'+endpoint+'?'+urllib.parse.urlencode(params)
        reason="unknown network error"
        for attempt in range(4):
            if self.calls>=self.limit:raise Stop('Request limit reached. Run the same command again to resume.')
            self.calls+=1
            try:
                with urllib.request.urlopen(url,timeout=90,context=self.context) as response:
                    result=json.load(response)
                time.sleep(.15)
                return result
            except urllib.error.HTTPError as e:
                if e.code==404:return None
                if e.code in (401,403,429):raise Stop(f'API returned HTTP {e.code}. Check your key/quota; rerun later.') from None
                if e.code<500:raise Stop(f'API rejected the request (HTTP {e.code}); no fields were silently removed.') from None
                reason=f'HTTP {e.code}'
            except (urllib.error.URLError,TimeoutError,OSError) as e:
                underlying=getattr(e,'reason',e)
                if isinstance(underlying,ssl.SSLCertVerificationError):
                    raise Stop('HTTPS certificate verification failed. Run: python -m pip install --upgrade certifi. If using an institutional proxy, configure SSL_CERT_FILE with its trusted CA bundle.') from None
                if isinstance(underlying,socket.gaierror):reason='DNS lookup failed (check internet/VPN/DNS)'
                elif isinstance(underlying,TimeoutError):reason='connection timed out'
                else:reason=type(underlying).__name__
            except ValueError:raise Stop('Invalid API JSON; rerun to retry remaining IDs.') from None
            if attempt<3:time.sleep(2**attempt)
        raise Stop(f'Network/server failure after retries: {reason}. Run again to resume.')


def fetch_ids(input_path, output, ids, origin, limit, client=None):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    if Path(input_path).resolve()==output.resolve():raise ValueError('Output must not overwrite input')
    ids=list(dict.fromkeys(ids));wanted=set(ids)
    manifest=output.with_suffix('.manifest.json');errors=output.with_suffix('.failures.jsonl')
    config={'input_sha256':sha(input_path),'metadata_version':METADATA_VERSION,'fields':WORK_FIELDS,
            'record_origin':origin,'target_count':len(ids)}
    if origin=='reference':
        assignment=json.loads(Path(input_path).read_text())
        config.update(seed_sha256=assignment['seed_sha256'],assignment=assignment['assignment'])
    if manifest.exists():
        if json.loads(manifest.read_text())!=config:raise ValueError('Input/schema changed: choose a new output file')
    else:
        if output.exists() or errors.exists():raise ValueError('Output exists without its resume manifest')
        write_json(manifest,config)
    done={r['requested_id'] for r in read_rows(output)} if output.exists() else set()
    missing={r['requested_id'] for r in read_rows(errors)} if errors.exists() else set()
    if (done|missing)-wanted:raise ValueError('Output contains IDs outside this assignment')
    output.touch(exist_ok=True)
    pending=[i for i in ids if i not in done|missing]
    client=client or Client(limit)
    def save(wid, raw):
        if raw is None:
            with errors.open('a') as f:
                f.write(json.dumps({'requested_id':wid,'status':'not_found','http_status':404})+'\n');f.flush();os.fsync(f.fileno())
            missing.add(wid);return
        if not isinstance(raw,dict) or not isinstance(raw.get('id'),str):raise Stop('Malformed work response; rerun to retry')
        row=normalize_work(raw)
        row.update(requested_id=wid,record_origin=origin,raw=raw)
        with output.open('a') as f:
            f.write(json.dumps(row,ensure_ascii=False,separators=(',',':'))+'\n');f.flush();os.fsync(f.fileno())
        done.add(wid)
    try:
        for start in range(0,len(pending),100):
            batch=pending[start:start+100]
            data=client.get('works',{'filter':'openalex:'+'|'.join(batch),'per_page':100,'select':WORK_FIELDS,'corpus':'all'})
            if not isinstance(data,dict) or not isinstance(data.get('results'),list):raise Stop('Malformed batch; rerun to retry')
            found={r['id'].rsplit('/',1)[-1]:r for r in data['results']}
            for wid in batch:
                if wid in found:save(wid,found[wid])
            for wid in batch:
                if wid not in found:save(wid,client.get('works/'+wid,{'select':WORK_FIELDS,'corpus':'all'}))
            print(json.dumps({'http_attempts':client.calls,'downloaded':len(done),'not_found':len(missing),'pending':len(wanted-done-missing)}),flush=True)
    except Stop as exc:print(str(exc),flush=True)
    result={'downloaded':len(done),'not_found':len(missing),'pending':len(wanted-done-missing),'output':str(output)}
    print(json.dumps(result,indent=2));return result


def split(seeds, folder, allow_missing=False):
    manifest=Path(seeds).with_suffix('.manifest.json')
    config=json.loads(manifest.read_text())
    if config['record_origin']!='seed':raise ValueError('Split requires refreshed seeds')
    completed=set();aliases={};refs=set()
    for row in read_rows(seeds):
        completed.add(row['requested_id']);aliases[row['requested_id']]=row['id']
        refs.update(row['refs'] or [])
    failures=Path(seeds).with_suffix('.failures.jsonl')
    missing={r['requested_id'] for r in read_rows(failures)} if failures.exists() else set()
    if len(completed|missing)!=config['target_count']:raise ValueError('Finish the original seed download before splitting')
    if missing and not allow_missing:raise ValueError('Some seed IDs returned 404. Review failures, then use --allow-missing to explicitly accept this coverage')
    seed_ids=completed|missing|set(aliases.values())
    targets=sorted({aliases.get(i,i) for i in refs}-seed_ids)
    random.Random(42).shuffle(targets)
    folder=Path(folder)
    common={'seed_sha256':sha(seeds),'metadata_version':METADATA_VERSION,'shuffle_seed':42,'missing_seed_ids':sorted(missing)}
    for name,ids in [('reference_ids',targets),('justin_ids',targets[::2]),('partner_ids',targets[1::2])]:
        body={**common,'assignment':name,'ids':ids};path=folder/(name+'.json')
        if path.exists() and json.loads(path.read_text())!=body:raise ValueError('Assignments already differ; choose a new folder')
    for name,ids in [('reference_ids',targets),('justin_ids',targets[::2]),('partner_ids',targets[1::2])]:
        write_json(folder/(name+'.json'),{**common,'assignment':name,'ids':ids})
    print(json.dumps({'external_ids':len(targets),'justin':len(targets[::2]),'partner':len(targets[1::2]),'folder':str(folder)},indent=2))


def combine(inputs, output):
    output=Path(output)
    if output.exists():raise ValueError('Choose a new combined output filename')
    if len(inputs)!=3:raise ValueError('Supply refreshed seeds, Justin references, and partner references')
    configs=[json.loads(Path(p).with_suffix('.manifest.json').read_text()) for p in inputs]
    if [c['record_origin'] for c in configs]!=['seed','reference','reference']:raise ValueError('Input order: seeds, Justin references, partner references')
    if any(c['metadata_version']!=METADATA_VERSION or c['fields']!=WORK_FIELDS for c in configs):raise ValueError('Mixed metadata schemas')
    if any(c.get('seed_sha256')!=sha(inputs[0]) for c in configs[1:]):raise ValueError('References belong to a different refreshed seed snapshot')
    if {c.get('assignment') for c in configs[1:]}!={'justin_ids','partner_ids'}:raise ValueError('Supply both distinct reference assignments')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        with sqlite3.connect(str(Path(tmp)/'merge.sqlite')) as db:
            db.execute('CREATE TABLE works(id TEXT PRIMARY KEY,rank TEXT,body TEXT)')
            db.execute('CREATE TABLE aliases(requested TEXT,canonical TEXT,PRIMARY KEY(requested,canonical))')
            db.execute('CREATE INDEX alias_canonical ON aliases(canonical)')
            for path in inputs:
                for row in read_rows(path):
                    requested=row['requested_id'];cid=row['id']
                    db.execute('INSERT OR IGNORE INTO aliases VALUES (?,?)',(requested,cid))
                    rank=('1' if row['record_origin']=='seed' else '0')+row['metadata_fetched_at']+hashlib.sha256(json.dumps(row,sort_keys=True).encode()).hexdigest()
                    db.execute('INSERT INTO works VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET rank=excluded.rank,body=excluded.body WHERE excluded.rank>works.rank',(cid,rank,json.dumps(row,ensure_ascii=False)))
            temp=output.with_suffix('.tmp')
            with temp.open('w') as f:
                for cid,body in db.execute('SELECT id,body FROM works ORDER BY id'):
                    row=json.loads(body);row['requested_ids']=[i for i, in db.execute('SELECT requested FROM aliases WHERE canonical=? ORDER BY requested',(cid,))]
                    f.write(json.dumps(row,ensure_ascii=False)+'\n')
            temp.replace(output)
            count=db.execute('SELECT COUNT(*) FROM works').fetchone()[0]
    write_json(output.with_suffix('.manifest.json'),{'inputs':[{ 'file':str(p),'sha256':sha(p)} for p in inputs],'unique_papers':count,'sha256':sha(output)})
    print(json.dumps({'unique_papers':count,'output':str(output)},indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('seeds');q.add_argument('--input',default='data/raw/openalex/works.jsonl');q.add_argument('--output',default='data/refreshed/seeds_enriched.jsonl');q.add_argument('--max-requests',type=int,default=1000)
    q=sub.add_parser('split');q.add_argument('--seeds',default='data/refreshed/seeds_enriched.jsonl');q.add_argument('--output-dir',default='data/refreshed/assignments');q.add_argument('--allow-missing',action='store_true')
    q=sub.add_parser('fetch');q.add_argument('--ids',required=True);q.add_argument('--output',required=True);q.add_argument('--max-requests',type=int,default=1000)
    q=sub.add_parser('combine');q.add_argument('--inputs',nargs=3,required=True);q.add_argument('--output',default='data/refreshed/combined.jsonl')
    a=p.parse_args()
    if hasattr(a,'max_requests') and a.max_requests<1:p.error('--max-requests must be positive')
    if a.command=='seeds':fetch_ids(a.input,a.output,[r['id'].rsplit('/',1)[-1] for r in read_rows(a.input)],'seed',a.max_requests)
    elif a.command=='split':split(a.seeds,a.output_dir,a.allow_missing)
    elif a.command=='fetch':
        assignment=json.loads(Path(a.ids).read_text())
        if assignment['metadata_version']!=METADATA_VERSION:raise ValueError('Assignment schema mismatch')
        fetch_ids(a.ids,a.output,assignment['ids'],'reference',a.max_requests)
    else:combine(a.inputs,a.output)

if __name__=='__main__':main()
