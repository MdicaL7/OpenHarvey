"""Add read-only native and historical-version evidence to a separate frozen audit copy."""
import argparse,json,shutil,subprocess,sys
from pathlib import Path
from types import SimpleNamespace
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
from run_suite import Runner
from suite_common import atomic_json

def main():
 p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
 if a.out.exists():raise SystemExit('Audit output must be new')
 a.out.mkdir();state=json.loads((a.source/'checkpoint.json').read_text());atomic_json(a.out/'checkpoint.json',state)
 shutil.copytree(a.source/'mappings',a.out/'mappings');native=json.loads((a.source/'native-readonly.json').read_text())['threads'];messages={m['info']['id']:m for ms in native.values() for m in ms}
 # Query immutable history only for case IDs already captured in this run.
 steps=[(p,json.loads(p.read_text())) for p in sorted((a.source/'steps').glob('*.json'))];ids=set()
 for _,ev in steps:
  for point in ['before','after']:
   ids.update(c['id'] for c in ev['result'].get(point,{}).get('core',{}).get('review_cases',[]))
 code="""import {DatabaseSync} from 'node:sqlite';import{createHash}from'node:crypto';const d=new DatabaseSync('/data/tdai-memory/contract-memory/'+createHash('sha256').update(JSON.stringify('default')).digest('hex').slice(0,24)+'/contract.sqlite',{readOnly:true});console.log(JSON.stringify(JSON.parse(process.argv[1]).flatMap(id=>d.prepare('SELECT * FROM case_history WHERE id=?').all(id))));"""
 history=json.loads(subprocess.check_output(['docker','exec','tdai-contract-core','node','--input-type=module','-e',code,json.dumps(sorted(ids))],text=True,stderr=subprocess.DEVNULL));atomic_json(a.out/'case-history-readonly.json',history);historical={r['id']+'@'+str(r['version']) for r in history};corrections=[]
 for p,ev in steps:
  if 'native' in ev['result']:
   public=ev['result']['native']['messages'];ev['result']['native']['messages']=[messages[m['info']['id']] if m['info']['id'] in messages else m for m in public]
   Runner.verify_reads(SimpleNamespace(out=a.out,state=state),ev['result'])
  for check in ev['deterministic_checks']:
   if check['check']=='v2_candidate_sources_exist' and check['status']=='fail':
    core=ev['result']['after']['core'];known={r['id'] for k in ['raw','atoms','entries','review_events','preference_statements'] for r in core[k]}|{c['id']+'@'+str(c['version']) for c in core['review_cases']}
    missing={i for c in core['candidates'] for i in c['data']['source_ids'] if i not in known}
    if missing and missing<=historical:
     correction={'step_id':ev['step']['step_id'],'original_check':dict(check),'historical_sources':sorted(missing),'reason':'Current-case snapshot excludes old versions; immutable case_history proves these sources exist.'};corrections.append(correction)
     check.update(status='pass',detail=correction['reason']);ev['result']['historical_source_evidence']=[{**r,'data':json.loads(r['data'])} for r in history if r['id']+'@'+str(r['version']) in missing]
  atomic_json(a.out/'steps'/p.name,ev)
 atomic_json(a.out/'audit-lineage.json',{'source':str(a.source),'source_files_unchanged':True,'native_messages_matched_by_id_no_future_messages':True,'corrections':corrections})
 print('Audit evidence prepared; corrections:',len(corrections))
if __name__=='__main__':main()
