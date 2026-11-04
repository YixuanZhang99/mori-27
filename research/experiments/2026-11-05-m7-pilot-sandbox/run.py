"""No-paid M7 pilot entry with actual sandbox and loopback synthetic provider."""
import json, tempfile, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoo.mle_bench_lite.cny_budget import CampaignBudget
from zoo.mle_bench_lite.composed_agent import run_governed_agent
from zoo.mle_bench_lite.public_train import write_csv

program = '''import csv,json
p=json.load(open("data/protocol.json"))
with open("data/predict.csv",newline="") as f: rows=list(csv.DictReader(f))
cols=p["output_columns"]; n=len(cols)-1
with open("predictions.csv","w",newline="") as f:
 w=csv.writer(f); w.writerow(cols)
 for row in rows: w.writerow([row["row_id"]]+[1/n]*n)
'''
requests=[]
class Handler(BaseHTTPRequestHandler):
 def do_POST(self):
  request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
  prompt=json.loads(request['messages'][0]['content']); requests.append(1)
  result=json.dumps({'artifact':program,'hypothesis':prompt['hypothesis']})
  body=json.dumps({'model':'deepseek-flash','usage':{'prompt_tokens':3,'completion_tokens':4,'total_tokens':7},'choices':[{'finish_reason':'stop','message':{'content':result}}]}).encode()
  self.send_response(200); self.end_headers(); self.wfile.write(body)
 def log_message(self,*args): pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler); worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
try:
 with tempfile.TemporaryDirectory(prefix='m7-sandbox-fixture-') as tmp:
  root=Path(tmp); data=root/'run/workspace/data'; data.mkdir(parents=True)
  write_csv(data/'train.csv',['id','x','author'],[{'id':str(i),'x':str(i),'author':'ABC'[i%3]} for i in range(60)])
  write_csv(data/'test.csv',['id','x'],[{'id':str(i),'x':str(100+i)} for i in range(4)])
  write_csv(data/'sample_submission.csv',['id','A','B','C'],[{'id':str(i),'A':1/3,'B':1/3,'C':1/3} for i in range(4)])
  key=root/'key'; key.write_bytes(b'k'*32); key.chmod(0o600)
  ledger=CampaignBudget.create(root/'fixture.db'); ledger.enable_governance(expected_policy_sha256=ledger.manifest_binding()['policy_sha256'],expected_head=ledger.snapshot()['journal_head'])
  result=run_governed_agent(workspace=data.parent,task_id='spooky-author-identification',model='deepseek-flash',api_base=f'http://127.0.0.1:{server.server_port}/v1',token_budget=3_000_000,seed=1,iterations=1,variant='full',max_completion_tokens=4,solution_timeout=30,anonymization_key_path=key,spending_ledger_path=ledger.path,api_key='fixture-only')
  assert result['submission_materialized'] and result['recorded_replay']['passed'] and len(requests)==3
  assert ledger.snapshot()['settled_upper_bound_micro_cny']==114
  print(json.dumps({'passed':True,'runner':'bubblewrap-seccomp','model_requests_external':0,'loopback_calls':len(requests),'synthetic_currency_micro_cny':114,'runtime':result['runtime'],'official_benchmark':False}))
finally:
 server.shutdown(); server.server_close(); worker.join()
