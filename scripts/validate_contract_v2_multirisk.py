"""Fresh-team real multi-risk replay plus role/standard/version checks."""
import argparse,concurrent.futures,json,sys,urllib.request,uuid
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
import run_suite as m
from suite_common import atomic_json,require_review
RISK_IDS=['EX-PAY','EX-ACCEPT','EX-TERMINATE']
class MultiRisk(m.Runner):
 def do(self,s):
  self.active_step=s;c=self.clients['owner'];a=s['action']
  if a=='copy_scheme':
   old=c.call('GET','/api/risk-schemes/options')['selected'];copy=self.mutate('copy','POST','/api/risk-schemes/public-risk-examples/copy',body={'scope':'personal'});self.state['scheme']=copy;self.state['old_scheme']=old;c.call('PUT','/api/risk-schemes/selection',body={'id':copy['id']});self.save();return {'scheme_id':copy['id'],'version':copy['revision']}
  if a in {'parallel_recall','changed_standard','opposite_role'}:
   w=c.call('GET','/api/workspaces/'+self.state['spaces'][s['workspace']]['id']);reports=[x for x in w['artifacts'] if x['kind']=='review'];assert len(reports)==1;aid=reports[0]['id']
   if a=='changed_standard':
    scheme=c.call('GET','/api/risk-schemes/'+self.state['scheme']['id']);content=scheme['content'];rule=next(x for x in content['rules'] if x['id']=='EX-PAY');rule['baseline']='收款保障调整：拟超过30天账期须先核验足额银行保函；不能直接套用以前的预付款意见。';c.call('PUT','/api/risk-schemes/'+scheme['id'],body={'revision':scheme['revision'],'scope':'personal','content':content})
   def fetch(rid):
    req=urllib.request.Request(c.origin+f'/api/artifacts/{aid}/risks/{rid}/precedents',headers={'X-Workbench-Request':'1'})
    with c.opener.open(req,timeout=210) as response:return json.load(response)
   ids=['EX-PAY'] if a=='changed_standard' else RISK_IDS
   with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:values=dict(zip(ids,pool.map(fetch,ids)))
   if a=='opposite_role':assert all(not x['items'] for x in values.values()),'Opposite-role precedent leaked'
   else:
    for rid,value in values.items():assert any(x['risk_id']==rid for x in value['items']),f'{rid} has no actual corresponding case'
    if a=='changed_standard':assert all(x['relation']!='applicable' for x in values['EX-PAY']['items'])
   return {'checks':a,'actual_results':values,'report_id':aid}
  if a=='check_single_contract':
   obs=self.observed(s);assert len(obs['core']['review_cases'])==3;assert not any(x['data']['kind']=='experience' for x in obs['candidates']['items']);return obs
  return super().do(s)
def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha);m.SUITE='contract-v2';cfg=json.loads(a.config.read_text());old=json.loads((a.out/'checkpoint.json').read_text()) if (a.out/'checkpoint.json').exists() else None;runner=MultiRisk(cfg,a.out,old)
 def step(i,action,workspace='SRC',**kw):return {'step_id':f'ABC-{i:02}','actor':'owner','team':'abc','workspace':workspace,'case_ids':[], 'action':action,**kw}
 concise='请完整读取当前合同，按当前方案逐项核验全部风险，理由和建议每项各不超过80字，保留真实原文引用，保存完整结构化风险报告。'
 steps=[step(1,'create_team',name='并发处置修复验收'),step(2,'assert_empty'),step(3,'copy_scheme'),step(4,'upload_contract',input_id='H01'),step(5,'message',text='我方是供货方。'+concise,require_saved_artifact=True),step(6,'risk_feedback',risk_id='EX-PAY',decision='接受风险',note='本项目可接受60天账期，但必须收取20%预付款，仅限本项目；尚未核验执行。'),step(7,'risk_feedback',risk_id='EX-ACCEPT',decision='要求修改',note='增加明确的终验期限、逾期处理及整改后复验期限，隐藏缺陷责任保留。'),step(8,'risk_feedback',risk_id='EX-TERMINATE',decision='补充材料',note='先核验不可取消采购和专用投入凭证，扣除可转售价值及减损金额后讨论结算。'),step(9,'check_single_contract'),step(10,'upload_contract','TARGET',input_id='F01'),step(11,'message','TARGET',text='我方是供货方。'+concise+'付款、验收、解除结算三项风险均请查询实际历史处置，核对差异。',require_saved_artifact=True),step(12,'parallel_recall','TARGET'),step(13,'changed_standard','TARGET'),step(14,'upload_contract','BUYER',input_id='F01'),step(15,'message','BUYER',text='我方是采购方。'+concise,require_saved_artifact=True),step(16,'opposite_role','BUYER')]
 atomic_json(a.out/'supplemental-steps.json',steps)
 try:runner.run(steps)
 finally:
  if runner.state.get('old_scheme'):runner.clients['owner'].call('PUT','/api/risk-schemes/selection',body={'id':runner.state['old_scheme']})
 print('Multi-risk live validation complete')
if __name__=='__main__':main()
