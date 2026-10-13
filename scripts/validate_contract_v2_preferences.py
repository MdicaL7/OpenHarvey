"""Focused real preference use/conflict/ignore flow in a fresh team."""
import argparse,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
import run_suite as m
from suite_common import atomic_json,require_review
class Preferences(m.Runner):
 def do(self,s):
  self.active_step=s
  if s['action']=='conflict_ignore':
   c=self.clients['owner'];obs=self.observed(s);candidate=self.pick_candidate(s,obs);assert candidate['data'].get('conflicts'),'No conflict recorded against prior formal preference'
   r=self.mutate('ignore','POST','/api/contract-memory/ignore',body={'team_id':self.team(s),'id':candidate['id'],'operation_id':self.key('ignore')},idempotent=True);self.state['ignored_candidate']=candidate;self.save();return {'conflict':candidate,'ignored':r,'after':self.observed(s)}
  if s['action']=='assert_preference_answer':
   t=self.clients['owner'].call('GET','/api/threads/'+self.thread(s));texts=[p.get('text','') for msg in t['messages'] if msg['info']['role']=='assistant' for p in msg.get('parts',[]) if p.get('type')=='text'];text='\n'.join(texts);assert all(word in text for word in s['expected']),text
   obs=self.observed(s)
   if self.state.get('ignored_candidate'):assert all(x['fingerprint']!=self.state['ignored_candidate']['fingerprint'] for x in obs['candidates']['items'])
   return {'native':t,'observed':obs,'expected':s['expected']}
  return super().do(s)
def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha);m.SUITE='contract-v2';cfg=json.loads(a.config.read_text());state=json.loads((a.out/'checkpoint.json').read_text()) if (a.out/'checkpoint.json').exists() else None;r=Preferences(cfg,a.out,state)
 def st(i,action,**kw):return {'step_id':f'PREF-{i:02}','actor':'owner','team':'prefs','workspace':'H01','case_ids':[],'action':action,**kw}
 steps=[st(1,'create_team',name='长期偏好与冲突验收'),st(2,'upload_contract',input_id='H01'),st(3,'message',text='以后所有合同报告先给结论，再分点说明。今后请称呼我为大哥。此刻不用审查合同。'),st(4,'candidate_action',operation='confirm',entry_alias='style',selector={'kind':'preference','contains':'结论'},repeat=True),st(5,'candidate_action',operation='confirm',entry_alias='address',selector={'kind':'preference','contains':'大哥'}),st(6,'new_thread'),st(7,'message',text='请说出我已经确认的长期称呼和报告结构约定。'),st(8,'assert_preference_answer',expected=['大哥','结论']),st(9,'message',text='以后称呼我为老师，替代以前的称呼约定。'),st(10,'conflict_ignore',selector={'kind':'preference','contains':'老师'}),st(11,'entry_action',entry_alias='address',operation='update',content='称呼用户为“老师”。',stale_check=True),st(12,'new_thread'),st(13,'message',text='请说出我已经确认的长期称呼和报告结构约定。'),st(14,'assert_preference_answer',expected=['老师','结论'])]
 atomic_json(a.out/'supplemental-steps.json',steps);r.run(steps)
if __name__=='__main__':main()
