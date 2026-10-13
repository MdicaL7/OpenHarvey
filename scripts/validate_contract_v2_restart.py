"""Restart the explicitly selected local experiment, preserving read-only evidence."""
import argparse,json,os,signal,subprocess,sys,time,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
from run_suite import Api
from snapshot_memory import snapshot
from suite_common import atomic_json,require_review

def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--state-root',type=Path,required=True);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha)
 cfg=json.loads(a.config.read_text());state=json.loads(a.checkpoint.read_text());r=a.state_root;team=state['teams']['v2-main']['id'];login=json.loads(Path(cfg['accounts']['owner']['login_file']).read_text())
 def capture():return snapshot(cfg['diagnostics'],team,login['username'])
 def stable(obs):return {k:sorted([{x:r[x] for x in fields} for r in obs[k]],key=lambda r:r['id'] if 'id'in r else json.dumps(r,sort_keys=True)) for k,fields in {'raw':['id','data'],'review_cases':['id','version','status','data'],'entries':['id','version','status','data'],'tombstones':['fingerprint']}.items()}
 def health(port):
  for _ in range(50):
   try:
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/health',timeout=2) as v:
     if v.status==200:return
   except Exception:pass
   time.sleep(.5)
  raise RuntimeError('Health failed on '+str(port))
 c=Api(cfg['origin']);c.call('POST','/api/login',body=login)
 for threads in state['threads'].values():
  for t in threads:
   obs=c.call('GET','/api/threads/'+t['id'])
   if obs.get('status',{}).get('type')!='idle' or obs.get('queue',{}).get('active'):raise RuntimeError('Experiment still executing')
 before=capture();atomic_json(r/'restart-before.json',before)
 if any(j['status']=='running' for j in before['jobs']):raise RuntimeError('Extraction still running')
 for label in ['owner','outsider']:
  pid=int((r/(label+'-app.pid')).read_text());cmd=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
  if 'scripts/run_tencentdb_local.py' not in cmd:raise RuntimeError('PID identity mismatch')
  os.kill(pid,signal.SIGTERM)
  for _ in range(40):
   try:os.kill(pid,0)
   except ProcessLookupError:break
   time.sleep(.25)
  else:raise RuntimeError('Application shutdown timeout')
 subprocess.run(['docker','stop','tdai-contract-proxy','tdai-contract-core'],check=True,stdout=subprocess.DEVNULL)
 subprocess.run(['docker','start','tdai-contract-core'],check=True,stdout=subprocess.DEVNULL);health(8430)
 subprocess.run(['docker','start','tdai-contract-proxy'],check=True,stdout=subprocess.DEVNULL);health(8106)
 for label,port in [('owner',8081),('outsider',8082)]:
  command=json.loads((r/(label+'-launch.json')).read_text())
  with (r/(label+'-app.log')).open('ab') as log:proc=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
  (r/(label+'-app.pid')).write_text(str(proc.pid));health(port)
 after=capture();atomic_json(r/'restart-after.json',after)
 assert stable(before)==stable(after),'Persisted memory or versions changed across restart'
 evidence={'run_id':state['run_id'],'step_id':'V2-S026','status':'pass','artifact_paths':[str(r/'restart-before.json'),str(r/'restart-after.json')],'checks':['raw retained','case versions and status retained','formal versions retained','tombstones retained','all local services healthy']};atomic_json(r/'restart-evidence.json',evidence)
 cfg['operator_evidence']['V2-S026']=str(r/'restart-evidence.json');atomic_json(a.config,cfg)
 print('Restart persistence passed; runner can resume')
if __name__=='__main__':main()
