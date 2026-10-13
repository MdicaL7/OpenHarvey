"""Scoped local fault injection with guaranteed service restoration and business-API retries."""
import argparse,json,os,signal,subprocess,sys,time,urllib.request,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
from run_suite import Api
from snapshot_memory import snapshot
from suite_common import atomic_json,require_review

def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--state-root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha)
 cfg=json.loads(a.config.read_text());state=json.loads(a.checkpoint.read_text());r=a.state_root;team=state['teams']['abc']['id'];account=json.loads(Path(cfg['accounts']['owner']['login_file']).read_text());c=Api(cfg['origin']);c.call('POST','/api/login',body=account);evidence={'checks':[]}
 def record(name,value):evidence['checks'].append({'name':name,'value':value});atomic_json(a.out,evidence)
 def poll(fn,condition,seconds=120):
  until=time.monotonic()+seconds
  while time.monotonic()<until:
   value=fn()
   if condition(value):return value
   time.sleep(1)
  raise RuntimeError('Fault verification timed out')
 def docker(action,name):subprocess.run(['docker',action,name],check=True,stdout=subprocess.DEVNULL)
 def health(port):return poll(lambda:probe(port),bool,60)
 def probe(port):
  try:
   with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as z:return z.status==200
  except Exception:return False
 def observe():return snapshot(cfg['diagnostics'],team,account['username'])
 def report():
  w=c.call('GET','/api/workspaces/'+state['spaces']['SRC']['id']);aid=next(x['id'] for x in w['artifacts'] if x['kind']=='review');return c.call('GET','/api/artifacts/'+aid)
 def feedback(note):
  p=report();old=p['feedback'].get('EX-LIABILITY',{});return c.call('PUT',f'/api/artifacts/{p["id"]}/risks/EX-LIABILITY/feedback',body={'source_hash':p['source_hash'],'revision':old.get('revision',0),'decision':'补充材料','note':note})
 def start_adapter():
  tokens=json.loads((r/'role-tokens.json').read_text());env=os.environ.copy();env.update(CONTRACT_EXTRACTION_ADAPTER_TOKEN=tokens['memory_extraction'],CONTRACT_JUDGE_ADAPTER_TOKEN=tokens['judge'])
  cmd=[str(ROOT/'.venv/bin/python'),str(ROOT/'openharvey_contract_memory_pack/07_tools/structured_model.py'),'--config',str(r/'models.json'),'--execute','--reviewed-pack-sha',a.reviewed_pack_sha,'--host','0.0.0.0','--port','8766']
  with (r/'structured-adapter.log').open('ab') as log:proc=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=log,start_new_session=True)
  (r/'structured-adapter.pid').write_text(str(proc.pid));health(8766)
 try:
  # Proxy failure affects a fresh short request, never an existing user task.
  t=c.call('POST','/api/workspaces/'+state['spaces']['TARGET']['id']+'/threads');before=observe();docker('stop','tdai-contract-proxy')
  try:
   sent=c.call('POST','/api/threads/'+t['id']+'/messages',body={'text':'仅回复服务恢复检查。','model':cfg['business_model'],'request_id':uuid.uuid4().hex},expected=202)
   q=poll(lambda:c.call('GET','/api/threads/'+t['id']+'/queue'),lambda q:q.get('paused') or any(x.get('status')=='failed' for x in q.get('items',[])))
   assert observe()['raw']==before['raw'];record('proxy_failure_visible_without_memory_write',{'accepted':sent,'queue':q})
  finally:docker('start','tdai-contract-proxy');health(8106)
  c.call('POST','/api/threads/'+t['id']+'/abort')
  recovered_thread=c.call('POST','/api/workspaces/'+state['spaces']['TARGET']['id']+'/threads')
  accepted=c.call('POST','/api/threads/'+recovered_thread['id']+'/messages',body={'text':'服务恢复检查：请只回复恢复成功。','model':cfg['business_model'],'request_id':uuid.uuid4().hex},expected=202)
  response=poll(lambda:c.call('GET','/api/threads/'+recovered_thread['id']),lambda v:v.get('status',{}).get('type')=='idle' and v.get('completion_id')==accepted['id'],600)
  assert '恢复成功' in json.dumps(response,ensure_ascii=False);record('proxy_recovery_real_response',response)
  # Outbox retains the saved feedback when Core cannot acknowledge it.
  docker('stop','tdai-contract-core')
  try:
   saved=feedback('请补充一般责任上限及例外的风险承受说明，尚未作出批准。');sync=poll(lambda:report()['memory_sync'].get('EX-LIABILITY',{}),lambda x:x.get('status')=='failed');record('core_outage_feedback_durable',{'saved':saved,'sync':sync})
  finally:docker('start','tdai-contract-core');health(8430)
  c.call('POST','/api/contract-memory/sync-retry',body={'event_id':sync['event_id']});poll(lambda:report()['memory_sync'].get('EX-LIABILITY',{}),lambda x:x.get('status')=='synced')
  recovered=observe();case=next(x for x in recovered['review_cases'] if x['data']['risk_id']=='EX-LIABILITY');c.call('POST','/api/contract-memory/sync-retry',body={'event_id':sync['event_id']});poll(lambda:report()['memory_sync'].get('EX-LIABILITY',{}),lambda x:x.get('status')=='synced');same=next(x for x in observe()['review_cases'] if x['id']==case['id']);assert same['version']==case['version'];record('outbox_retry_idempotent',{'case_id':case['id'],'version':case['version']})
  poll(observe,lambda v:not any(j['status'] in {'pending','running'} or j['status']=='failed' and j['attempts']<3 for j in v['jobs']),600)
  # Deliberately fail only the extraction bridge, then use the public retry action.
  pid=int((r/'structured-adapter.pid').read_text());command=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True);assert 'structured_model.py' in command;os.kill(pid,signal.SIGTERM)
  try:
   poll(lambda:not probe(8766),bool,20);saved=feedback('补充意见：例外责任须明确对应触发条件，仅供本项目核对；未证明已执行。')
   failed=poll(observe,lambda v:any(j['status']=='failed' and j['attempts']>=3 for j in v['jobs']),120);record('extraction_failure_observable',{'saved':saved,'failed_jobs':[j for j in failed['jobs'] if j['status']=='failed']})
  finally:start_adapter()
  for job in failed['jobs']:
   if job['status']=='failed':c.call('POST','/api/contract-memory/retry',body={'team_id':team,'id':job['id'],'operation_id':uuid.uuid4().hex})
  restored=poll(observe,lambda v:not any(j['status'] in {'pending','running','failed'} for j in v['jobs']),600);record('extraction_recovered',{'jobs':[(j['id'],j['status']) for j in restored['jobs']],'cases':[(x['id'],x['version']) for x in restored['review_cases']]})
  evidence['status']='pass';atomic_json(a.out,evidence);print('Real fault recovery checks passed')
 except Exception as e:evidence['status']='failed';evidence['error']=str(e);atomic_json(a.out,evidence);raise
 finally:
  for name,port in [('tdai-contract-core',8430),('tdai-contract-proxy',8106)]:
   if not probe(port):docker('start',name);health(port)
  if not probe(8766):start_adapter()
if __name__=='__main__':main()
