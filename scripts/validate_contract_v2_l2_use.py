"""Continue real cases into a confirmed L2 method and require actual正文 tool use."""
import argparse,json,sys,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'));sys.path.insert(0,str(ROOT/'scripts'))
import run_suite as m
from export_contract_v2_native import export
from suite_common import atomic_json,require_review

def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--checkpoint',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha);m.SUITE='contract-v2';cfg=json.loads(a.config.read_text());old=json.loads(a.checkpoint.read_text());state=json.loads((a.out/'checkpoint.json').read_text()) if (a.out/'checkpoint.json').exists() else {**old,'completed':[],'calls':{},'entries':{},'entry_baselines':{},'candidate_baselines':{},'run_id':uuid.uuid4().hex};state.pop('blocked',None);r=m.Runner(cfg,a.out,state)
 def st(i,action,**kw):return {'step_id':f'L2-USE-{i:02}','actor':'owner','team':'abc','workspace':'TARGET','case_ids':[],'action':action,**kw}
 steps=[st(1,'risk_feedback',risk_id='EX-PAY',decision='要求修改',note='本合同不照搬其他项目的预付款让步；要求增加银行保函保障，再讨论较长账期，保函须核验有效性。'),st(2,'candidate_action',operation='confirm',entry_alias='method',selector={'kind':'experience','contains':'付款'}),st(3,'new_thread'),st(4,'message',text='请先读取我已经确认的付款处置经验正文，再说明本合同需要核对哪些适用条件。结论仍以当前原文为准。')]
 atomic_json(a.out/'steps-plan.json',steps);r.run(steps)
 t=r.state['threads']['TARGET'][-1];native=export(Path(cfg['diagnostics']['app_data']),r.users['owner']['username'],[t],a.out/'native-readonly.json');tools=[x for ms in native.values() for msg in ms for x in msg.get('parts',[]) if x.get('type')=='tool']
 reads=[x for x in tools if x.get('tool')=='bash' and '/scenario/read' in x.get('state',{}).get('input',{}).get('command','') and x['state']['status']=='completed'];assert reads,'Agent did not actually call scenario/read'
 entry=r.state['entries']['method'];assert any(entry['data']['content'] in x['state'].get('output','') for x in reads),'Read result does not contain the confirmed method'
 atomic_json(a.out/'acceptance.json',{'status':'pass','formal_entry_id':entry['id'],'formal_entry_version':entry['version'],'actual_scenario_reads':reads,'method':'real model-selected read-only bridge'});print('Actual confirmed L2正文 read passed')
if __name__=='__main__':main()
