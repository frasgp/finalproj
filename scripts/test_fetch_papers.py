import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import ssl
import socket
import urllib.error
spec=importlib.util.spec_from_file_location('fetch_papers',Path(__file__).with_name('fetch_papers.py'))
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)

class Fake:
    def __init__(self,works,limit=100):self.works=works;self.calls=0;self.limit=limit
    def get(self,endpoint,params):
        if self.calls>=self.limit:raise f.Stop('Interrupted')
        self.calls+=1
        if endpoint=='works':
            ids=params['filter'].split(':',1)[1].split('|')
            return {'results':[self.works[i] for i in ids if i in self.works and self.works[i]['id'].endswith('/'+i)]}
        return self.works.get(endpoint.split('/')[-1])

def work(i,refs=()):
    return {'id':'https://openalex.org/'+i,'referenced_works':['https://openalex.org/'+r for r in refs],
            'abstract_inverted_index':{'word':[0]},'topics':[{'id':'T1','subfield':{'id':'S1'}}],
            'cited_by_percentile_year':{'min':90,'max':91}}

class Tests(unittest.TestCase):
    def test_refresh_split_resume_combine(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);original=d/'original.jsonl';original.write_text('{"id":"W1"}\n')
            seeds=d/'seeds.jsonl';f.fetch_ids(original,seeds,['W1'],'seed',5,Fake({'W1':work('W1',['W1','W2','W3'])}))
            f.split(seeds,d/'ids')
            assignments=[json.loads((d/'ids'/n).read_text()) for n in ('justin_ids.json','partner_ids.json')]
            self.assertEqual(set(assignments[0]['ids'])|set(assignments[1]['ids']),{'W2','W3'})
            self.assertFalse(set(assignments[0]['ids'])&set(assignments[1]['ids']))
            outputs=[]
            # Redirect both targets to the same work; final export deduplicates them.
            for name,assignment in zip(('justin','partner'),assignments):
                path=d/'ids'/(name+'_ids.json');out=d/(name+'.jsonl');outputs.append(out)
                data={i:work('W20') for i in assignment['ids']}
                f.fetch_ids(path,out,assignment['ids'],'reference',1,Fake(data,limit=1))
                result=f.fetch_ids(path,out,assignment['ids'],'reference',5,Fake(data))
                self.assertEqual(result['pending'],0)
                client=Fake(data);f.fetch_ids(path,out,assignment['ids'],'reference',5,client);self.assertEqual(client.calls,0)
            merged=d/'combined.jsonl';f.combine([seeds,*outputs],merged)
            rows=list(f.read_rows(merged));self.assertEqual(len(rows),2)
            self.assertEqual(rows[1]['requested_ids'],['W2','W3'])
            self.assertEqual(rows[0]['topics'][0]['subfield']['id'],'S1')
            self.assertEqual(rows[0]['cited_by_percentile_year']['min'],90)
            self.assertEqual(original.read_text(),'{"id":"W1"}\n')
    def test_missing_and_schema_guard(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);original=d/'original.jsonl';original.write_text('{"id":"W1"}\n{"id":"W2"}\n')
            out=d/'seeds.jsonl';f.fetch_ids(original,out,['W1','W2'],'seed',10,Fake({'W1':work('W1')}))
            with self.assertRaises(ValueError):f.split(out,d/'ids')
            f.split(out,d/'ids',allow_missing=True)
            original.write_text('{"id":"W3"}\n')
            with self.assertRaises(ValueError):f.fetch_ids(original,out,['W3'],'seed',1,Fake({}))

class NetworkTests(unittest.TestCase):
    def test_verified_context(self):
        context=f.tls_context()
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)
        self.assertGreater(context.cert_store_stats()['x509_ca'],0)

    @patch.object(f.urllib.request,'urlopen')
    def test_certificate_error_is_explicit_and_not_retried(self, request):
        request.side_effect=urllib.error.URLError(ssl.SSLCertVerificationError(1,'untrusted'))
        with self.assertRaisesRegex(f.Stop,'certificate verification failed'):
            f.Client(10).get('works',{})
        self.assertEqual(request.call_count,1)

    @patch.object(f.time,'sleep')
    @patch.object(f.urllib.request,'urlopen')
    def test_dns_error_is_explicit(self, request, sleep):
        request.side_effect=urllib.error.URLError(socket.gaierror(8,'unavailable'))
        with self.assertRaisesRegex(f.Stop,'DNS lookup failed'):
            f.Client(10).get('works',{})
        self.assertEqual(request.call_count,4)

if __name__=='__main__':unittest.main()
