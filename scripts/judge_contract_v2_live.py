"""Judge frozen evidence, with exact serialized-record citations and retained failed attempts."""
import argparse,json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
import run_suite as suite
from structured_model import complete
from suite_common import atomic_json,require_review

def main():
 p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--supplement',type=Path,action='append',default=[]);a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha)
 cfg=json.loads(a.config.read_text());state=json.loads((a.evidence/'checkpoint.json').read_text());suite.SUITE='contract-v2';results=[];extras=[json.loads(p.read_text()) for p in a.supplement]
 for case in suite.manifest('cases.json'):
  evidence=[suite.compact_evidence(json.loads((a.evidence/'steps'/(s+'.json')).read_text())) for s in case['step_ids']]
  if case['case_id'] in {'V2-BOUNDARY','V2-PROTECTION','V2-RELIABILITY'}:evidence += [{'step':{'step_id':'SUPPLEMENT-'+str(i)},'result':v} for i,v in enumerate(extras)]
  sources={ev['step']['step_id']:json.dumps(ev['result'],ensure_ascii=False,sort_keys=True,indent=2) for ev in evidence}
  digest=hashlib.sha256(json.dumps({'case':case,'sources':sources,'model':cfg['models']['roles']['judge']},ensure_ascii=False,sort_keys=True).encode()).hexdigest();casepath=a.out/(case['case_id']+'.json')
  if casepath.exists():
   saved=json.loads(casepath.read_text());assert saved['input_sha']==digest;results.append(saved);continue
  record={'case_id':case['case_id'],'input_sha':digest,'attempts':[]}
  for attempt in range(2):
   request={'role':'judge','model':cfg['models']['roles']['judge']['model'],'stage':'judge','request_id':state['run_id']+':audit-judge:'+case['case_id']+':'+str(attempt),'prompt':'仅评估冻结的真实证据与指定用例，不调用工具。输出一个对应case_id的结果。引用必须从sources中某个字符串逐字复制连续片段，source_id必须是sources的键。不要自己重排JSON、拼接多个字段或用省略号改写引用。引用可以是原话，也可以是序列化记录中连续的真实结构字段。证据不足返回needs_review，不把助手声称或预期结果当事实。至少一条有效引用，关键失败单列。'+('上次引用未能逐字匹配，请重新选择实际连续片段。' if attempt else ''),'input':{'case':case,'sources':sources}}
   raw=complete(cfg['models'],request,execute=True);items=raw['output']['results'];valid=len(items)==1 and items[0]['case_id']==case['case_id'] and bool(items[0]['evidence']) and all(len(e['quote'].strip())>=4 and e['source_id'] in sources and e['quote'] in sources[e['source_id']] for e in items[0]['evidence']);record['attempts'].append({'raw':raw,'citations_valid':valid});atomic_json(casepath,record)
   if valid:record['result']=items[0];break
  if 'result' not in record:record['result']={'case_id':case['case_id'],'verdict':'needs_review','critical_failures':['Judge citation validation failed'],'evidence':[]}
  atomic_json(casepath,record);results.append(record);print(case['case_id'],record['result']['verdict'],flush=True)
 atomic_json(a.out/'summary.json',{'source_run_id':state['run_id'],'same_configured_model':True,'results':[r['result'] for r in results]})
if __name__=='__main__':main()
