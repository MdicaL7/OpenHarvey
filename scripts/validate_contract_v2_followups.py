"""Reusable ordinary-provider, revised-document and preference-source followups."""
import argparse,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'));sys.path.insert(0,str(ROOT/'scripts'))
import run_suite as m
from export_contract_v2_native import export
from suite_common import atomic_json,require_review
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['ordinary','revision','preference-source']);p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--team-alias',required=True);p.add_argument('--workspace',required=True);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha)
 cfg=json.loads(a.config.read_text());old=json.loads(a.checkpoint.read_text());state=json.loads((a.out/'checkpoint.json').read_text()) if (a.out/'checkpoint.json').exists() else {**old,'completed':[],'calls':{},'run_id':uuid.uuid4().hex};state.pop('blocked',None);m.SUITE='contract-v2';runner=m.Runner(cfg,a.out,state)
 def step(n,action,**kw):return {'step_id':a.action.upper()+'-'+str(n),'actor':'owner','team':a.team_alias,'workspace':a.workspace,'case_ids':[],'action':action,**kw}
 if a.action=='ordinary':steps=[step(1,'new_thread'),step(2,'message',model_role='ordinary',wait_extraction=False,text='只根据本条输入回答：2加3等于几？请只回复数字。')]
 elif a.action=='revision':steps=[step(1,'new_thread'),step(2,'attach',input_id='F01-R2'),step(3,'message',text='附件是这份合同的修订稿。请实际读取修订附件，并与原主合同对照付款及验收条款，引用新旧原文和版本，说明哪些条件变化。不要把修订稿的存在当作已签署或已执行，也不要直接照搬旧处理意见。')]
 else:steps=[step(1,'message',text='请先查询我的相关称呼记忆，再确认当前应使用的称呼，区分历史原话与当前正式约定。')]
 atomic_json(a.out/'supplemental-steps.json',steps);runner.run(steps)
 t=runner.state['threads'][a.workspace][-1];native=export(Path(cfg['diagnostics']['app_data']),runner.users['owner']['username'],[t],a.out/'native-readonly.json')
 if a.action=='revision':
  doc=runner.state['documents'][a.workspace+':F01-R2'];assert any('【D'+doc['id']+':' in part.get('state',{}).get('output','') for msgs in native.values() for msg in msgs for part in msg.get('parts',[]) if part.get('type')=='tool' and part.get('tool')=='read'),'Revised version was not read'
 print('Followup complete; inspect frozen native output and actual model verdict separately')
