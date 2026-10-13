"""Focused post-fix preference/protection regression; capture actual API receipts."""
import argparse,json,sys,uuid,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'));sys.path.insert(0,str(ROOT/'scripts'))
import run_suite as m
from validate_contract_v2_preferences import Preferences
from suite_common import atomic_json,require_review

class Protection(Preferences):
    def do(self,s):
        self.active_step=s
        if s['action']=='conflict_ignore':
            result=super().do(s);call=self.state['calls'][s['step_id']+':ignore'];again=self.clients['owner'].call('POST',call['path'],body=call['body']);assert again==call['result'];result['repeat_ignore']=again;return result
        if s['action']=='verify_latest':
            native=self.clients['owner'].call('GET','/api/threads/'+self.thread(s));msgs=native['messages'];last=next(x for x in reversed(msgs) if x['info']['role']=='assistant');text='\n'.join(p['text'] for p in last['parts'] if p.get('type')=='text')
            obs=self.observed(s);assert all(w in text for w in s['required']),text
            if s.get('deleted'):
                entry=self.state['entries']['address'];assert not any(x['id']==entry['id'] for x in obs['personal']['items']);self.clients['owner'].call('GET',f'/api/contract-memory/detail/{entry["id"]}?team_id={self.team(s)}')
                assert not any(x['fingerprint'] in {self.state['ignored_candidate']['fingerprint'],self.state['candidate_baselines']['address']['fingerprint']} for x in obs['candidates']['items'])
            else:
                address=self.state['entries']['address'];assert address['version']==2 and address['protected']==1
            return {'native':native,'after':obs,'final_assistant_text':text,'requires_semantic_judge':True}
        return super().do(s)

def main():
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--replay-from',type=Path);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha);m.SUITE='contract-v2';cfg=json.loads(a.config.read_text());receipts=[]
    class Captured(m.Api):
        def call(self,method,path,body=None,**kw):
            value=super().call(method,path,body=body,**kw)
            if method!='GET' and path!='/api/login':
                receipts.append({'method':method,'path':path,'body':m.scrub(body),'http_status':kw.get('expected',200),'response':m.scrub(value)})
                atomic_json(a.out/'api-receipts.json',receipts)
            return value
    prior=json.loads((a.out/'checkpoint.json').read_text()) if (a.out/'checkpoint.json').exists() else None
    if a.replay_from and not prior:
        prior={**json.loads(a.replay_from.read_text()),'completed':[],'calls':{},'run_id':uuid.uuid4().hex};prior.pop('blocked',None)
    if (a.out/'api-receipts.json').exists():receipts.extend(json.loads((a.out/'api-receipts.json').read_text()))
    r=Protection(cfg,a.out,prior,api_factory=Captured)
    if a.replay_from:
        s={'step_id':'PROTECT-REPLAY-01','actor':'owner','team':'prefs','workspace':'H01','case_ids':[],'action':'message','text':'今后所有合同审查交付都应保留文档ID和原文段落定位。这是新增的长期证据要求，现有已经确认的正文仍按当前版本适用。此刻不用审查合同。'}
        r.run([s]);path=a.out/'steps/PROTECT-REPLAY-01.json';ev=json.loads(path.read_text());before=ev['result']['before']['core'];after=ev['result']['after']['core'];old_runs={x['id'] for x in before['llm_runs']};l3=[x for x in after['llm_runs'] if x['id'] not in old_runs and x['data']['stage']=='l3'];assert l3,'No actual same-source L3 reprocessing'
        ignored=r.state['ignored_candidate'];deleted=r.state['entries']['address'];blocked={ignored['fingerprint'],r.state['candidate_baselines']['address']['fingerprint']};old_sources=set(ignored['data']['source_ids'])|set(deleted['data']['source_ids']);inputs={p['id'] for x in l3 for p in x['data']['input']['preferences']};assert old_sources<=inputs,'L3 did not receive the original ignored/deleted sources'
        assert not any(x['fingerprint']in blocked for x in after['candidates'] if x['status']=='pending');assert not any(x['id']==deleted['id'] for x in ev['result']['after']['personal']['items'])
        style=r.state['entries']['style'];current=next(x for x in after['entries'] if x['id']==style['id']);assert current['data']==style['data'] and current['version']==style['version']
        atomic_json(a.out/'same-source-proof.json',{'status':'pass','source_file':str(path),'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'actual_l3_runs':[{**x,'data':{k:v for k,v in x['data'].items() if k not in {'prompt'}}} for x in l3],'original_ignored':ignored,'deleted_entry':deleted,'protected_current_entry':current,'candidates_after_reprocessing':after['candidates'],'tombstones':after['tombstones'],'jobs':after['jobs'],'revisions':after['revisions'],'checks':{'same_original_sources_present_in_real_L3_input':True,'ignored_deleted_fingerprints_absent_from_pending':True,'deleted_entry_absent_from_formal_list':True,'protected_version_and_body_unchanged':True}});print('Same-source L3 replay proof completed');return
    def st(i,action,**kw):return {'step_id':f'PROTECT-{i:02}','actor':'owner','team':'prefs','workspace':'H01','case_ids':[],'action':action,**kw}
    steps=[st(1,'create_team',name='偏好人工保护修复复测'),st(2,'upload_contract',input_id='H01'),st(3,'message',text='以后所有合同报告先给结论，再分点说明。今后请称呼我为大哥。此刻不用审查合同。'),
      st(4,'candidate_action',operation='confirm',entry_alias='style',selector={'kind':'preference','contains':'结论'},repeat=True),st(5,'candidate_action',operation='confirm',entry_alias='address',selector={'kind':'preference','contains':'大哥'},repeat=True),
      st(6,'message',text='以后称呼我为老师，替代以前的称呼约定。'),st(7,'conflict_ignore',selector={'kind':'preference','contains':'老师'}),
      st(8,'entry_action',entry_alias='address',operation='update',content='称呼用户为“老师”。',stale_check=True),
      st(9,'entry_action',entry_alias='style',operation='update',content='合同报告先给结论，再列原文证据与建议。',stale_check=True),
      st(10,'new_thread'),st(11,'message',text='请先查询我的相关历史偏好声明，再核对当前已确认的称呼与报告结构。说明当前真正应使用的约定；旧声明只用于溯源，不替代最新正式正文。'),st(12,'verify_latest',required=['老师','证据','建议']),
      st(13,'entry_action',entry_alias='address',operation='delete'),st(14,'new_thread'),st(15,'message',text='请查询我当前仍有效的已确认工作约定，并按当前正式正文说明报告结构。不要将历史原话或已删除条目当作现行偏好。'),st(16,'verify_latest',required=['证据','建议'],deleted=True)]
    atomic_json(a.out/'steps-plan.json',steps);r.run(steps)
    # All repeats use the identical operation ID; log the real receipt, not a synthetic status assertion.
    for key,call in r.state['calls'].items():
        if key.endswith(':entry') and '/contract-memory/' in call['path']:
            again=r.clients['owner'].call('POST',call['path'],body=call['body']);assert again==call['result']
    atomic_json(a.out/'post-checks.json',{'status':'pass','api_receipts':len(receipts),'repeated_saved_operations_equal':True,'note':'Semantic latest-preference usage is independently judged from the native final reply.'});print('Focused protection regression completed')
if __name__=='__main__':main()
