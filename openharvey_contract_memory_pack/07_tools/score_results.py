#!/usr/bin/env python3
"""Diagnostics for actual normalized predictions; not an LLM grader or native adapter."""
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--extractions',type=Path);p.add_argument('--answers',type=Path);a=p.parse_args()
if not a.extractions and not a.answers:p.error('Provide actual prediction files. This tool will not invent a model run.')
R=Path(__file__).resolve().parents[1]
def rows(path):return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
def idx(items,k):
 d={}
 for x in items:
  if x[k] in d:raise ValueError('Duplicate result ID '+x[k])
  d[x[k]]=x
 return d
out={'scope':'Deterministic diagnostics for supplied normalized results only; no overall legal-accuracy score. See manual rubric.','critical_flags':[]}
if a.extractions:
 pred=idx(rows(a.extractions),'doc_id');gold=rows(R/'05_private_gold_DO_NOT_INGEST/extraction_gold.jsonl');matched=total=0;missing=[];mismatch=[]
 for g in gold:
  r=pred.get(g['doc_id'])
  if r is None:missing.append(g['doc_id'])
  actual=(r or {}).get('fields',{})
  for k,v in g['expected_fields'].items():
   total+=1
   if actual.get(k)==v:matched+=1
   else:mismatch.append({'doc_id':g['doc_id'],'field':k})
 out['extraction']={'exact_field_matches':matched,'total_fields':total,'exact_field_accuracy':matched/total,'missing_docs':missing,'mismatches':mismatch,'extra_doc_ids':sorted(set(pred)-{g['doc_id'] for g in gold})}
if a.answers:
 pred=idx(rows(a.answers),'query_id');gold=rows(R/'05_private_gold_DO_NOT_INGEST/recall_gold.jsonl');cases=[]
 for g in gold:
  r=pred.get(g['query_id']);row={'query_id':g['query_id'],'missing':r is None}
  if r is None:cases.append(row);continue
  required=set(g['required_memory_ids']);ev=set(g['expected_evidence']);cited=set(r.get('normalized_evidence_refs',[]));found=set(r.get('retrieved_logical_memory_ids',[]))
  # This field must mean relied on to authorize the queried action, not merely cited or used for formatting.
  used=set(r.get('memory_ids_used_to_authorize_queried_action',[]));violations=sorted(used & set(g['must_not_apply_as_authority']))
  row.update({'diagnostic_required_memory_coverage':len(required&found)/len(required) if required else None,'diagnostic_evidence_coverage':len(ev&cited)/len(ev) if ev else None,'decision_label_match':r.get('normalized_decision')==g['expected_decision'],'abstention_match':r.get('abstained')==g['expected_abstention'],'forbidden_authority_uses':violations,'human_semantic_verdict':r.get('human_semantic_verdict','not_reviewed')})
  if violations:out['critical_flags'].append({'query_id':g['query_id'],'type':'forbidden_authority_use','memory_ids':violations})
  if 'NEG-XTENANT-01' in found or r.get('cross_tenant_content_leaked') is True:out['critical_flags'].append({'query_id':g['query_id'],'type':'cross_tenant_retrieval_or_leak'})
  for failure in r.get('human_confirmed_critical_failures',[]):out['critical_flags'].append({'query_id':g['query_id'],'type':'human_confirmed','detail':failure})
  cases.append(row)
 out['answer_diagnostics']=cases;out['missing_answers']=[r['query_id'] for r in cases if r['missing']];out['extra_query_ids']=sorted(set(pred)-{g['query_id'] for g in gold});out['caution']='Low diagnostic recall is not automatically a wrong answer; accept sufficient equivalent evidence through human semantic review. Native IDs require verified mapping. Labels are evaluator normalization, not required model wording.'
print(json.dumps(out,ensure_ascii=False,indent=2))
