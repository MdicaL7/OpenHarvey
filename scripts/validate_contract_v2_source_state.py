"""Verify correction/withdrawal and soft-delete source validity through real app APIs."""
import argparse,json,sys,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
from run_suite import Api
from suite_common import atomic_json,require_review

def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha);cfg=json.loads(a.config.read_text());s=json.loads(a.checkpoint.read_text());c=Api(cfg['origin']);c.call('POST','/api/login',body=json.loads(Path(cfg['accounts']['owner']['login_file']).read_text()));evidence={'checks':[]}
 def record(name,result):evidence['checks'].append({'name':name,'result':result});atomic_json(a.out,evidence)
 def report(w):
  items=c.call('GET','/api/workspaces/'+s['spaces'][w]['id'])['artifacts'];reports=[x for x in items if x['kind']=='review'];assert len(reports)==1;return c.call('GET','/api/artifacts/'+reports[0]['id'])
 source=report('SRC');target=report('TARGET');old_hash=source['content_hash'];sid=source['id'];tid=target['id']
 def recall(rid):
  req=urllib.request.Request(c.origin+f'/api/artifacts/{tid}/risks/{rid}/precedents',headers={'X-Workbench-Request':'1'})
  with c.opener.open(req,timeout=210) as r:return json.load(r)
 before=recall('EX-ACCEPT');assert before['items'];record('before_correction',before)
 old=source['feedback']['EX-ACCEPT'];body={'source_hash':source['source_hash'],'revision':old['revision'],'decision':'判断有误','note':'原审查把缺少终验期限当作完全没有验收安排，需要纠正；已有初验规则应保留，终验问题仍须单独处理。'}
 changed=c.call('PUT',f'/api/artifacts/{sid}/risks/EX-ACCEPT/feedback',body=body);record('correcting_feedback_saved',changed)
 # Feedback history itself is immediately authoritative; asynchronous Memory receipt is checked separately.
 source=report('SRC');assert source['content_hash']==old_hash;assert len(source['feedback']['EX-ACCEPT']['history'])>=1;record('original_report_unchanged',{'content_hash':old_hash,'feedback':source['feedback']['EX-ACCEPT']})
 import time
 for _ in range(120):
  source=report('SRC')
  if source['memory_sync']['EX-ACCEPT']['status']=='synced':break
  time.sleep(1)
 else:raise RuntimeError('Feedback synchronization timed out')
 after=recall('EX-ACCEPT');assert any(x['risk_id']=='EX-ACCEPT' and x['decision']=='判断有误' and x['version']>1 for x in after['items']);record('corrected_case_recalled',after)
 c.call('PATCH','/api/workspaces/'+s['spaces']['SRC']['id'],body={'action':'delete','confirmed':True})
 try:
  hidden=recall('EX-PAY');assert not hidden['items'];record('removed_source_exits_recall',hidden)
 finally:c.call('PATCH','/api/workspaces/'+s['spaces']['SRC']['id'],body={'action':'restore'})
 restored=recall('EX-PAY');assert restored['items'];record('restored_source_revalidated',restored)
 evidence['status']='pass';atomic_json(a.out,evidence);print('Source state checks passed')
if __name__=='__main__':main()
