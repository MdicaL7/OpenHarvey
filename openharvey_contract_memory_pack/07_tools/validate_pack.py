#!/usr/bin/env python3
"""Offline fixture / causal replay integrity only. Never invokes a model or application."""
import hashlib,json,re,sys,zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from suite_common import ROOT as R,manifest,pack_digest
errors=[];checks=0

def check(ok,msg):
 global checks
 checks+=1
 if not ok:errors.append(msg)
def readj(p):return json.loads((R/p).read_text())
def readl(p):return [json.loads(l) for l in (R/p).read_text().splitlines() if l]
for p in R.rglob('*'):
 if not p.is_file() or '__pycache__' in p.parts or '08_validation' in p.parts:continue
 if p.suffix in {'.json','.jsonl'}:
  try:json.loads(p.read_text()) if p.suffix=='.json' else [json.loads(l) for l in p.read_text().splitlines() if l];checks+=1
  except Exception as e:errors.append(str(p.relative_to(R))+': '+str(e))
contracts=readj('00_start_here/contract_manifest.json');locations=manifest('source_locations.json');anchors={r['anchor'] for r in locations};ids=set()
check(len(contracts)==11,'expected 10 originals + 1 revision');check(sum(m['split']=='history' for m in contracts)==6,'history count')
for m in contracts:
 cid=m['doc_id'];check(cid not in ids,'duplicate contract');ids.add(cid);body=(R/m['txt_path']).read_text()
 check(re.findall(r'^第(\d+)条 ',body,re.M)==[str(i) for i in range(1,15)],cid+' clause sequence')
 check(not re.search(r'虚构|合成|评测|测试文件|测试主体|测试元数据|ORG-|PRJ-|\[(?:H|F)\d{2}-C\d+',body),cid+' contains operator markings')
 check('甲方签章：________________' in body and '乙方签章：________________' in body,cid+' empty signature fields')
 check(hashlib.sha256(body.encode()).hexdigest()==m['txt_sha256'],cid+' TXT digest')
 check(hashlib.sha256((R/m['docx_path']).read_bytes()).hexdigest()==m['docx_sha256'],cid+' DOCX digest')
 with zipfile.ZipFile(R/m['docx_path']) as z:
  w='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}';xml=ET.fromstring(z.read('word/document.xml'))
  paras=[''.join(t.text or '' for t in p.iter(w+'t')) for p in xml.iter(w+'p')]
  check(paras==[l for l in body.splitlines() if l],cid+' DOCX/TXT mismatch')
  check(not list(ET.fromstring(z.read('word/styles.xml')).iter(w+'pBdr')),cid+' title border')
 clause_rows=[l for l in locations if l['input_id']==cid];check(len(clause_rows)==14,cid+' missing sidecar clauses')
 for loc in clause_rows:
  check(loc['text'] in body,'missing text location '+loc['anchor']);check(loc['file_sha256']==m['txt_sha256'],'location digest '+loc['anchor'])
revision=(R/next(m['txt_path'] for m in contracts if m['doc_id']=='F01-R2')).read_text();check('0.05%' in next(l['text'] for l in locations if l['anchor']=='F01-R2-C06'),'revision did not change clause 6')
events=[]
for n in ['reviewer_comments','final_decisions_and_updates','policies']:events+=readl('02_review_writeback/operator_only_indexes/'+n+'.jsonl')
eventids={e['event_id'] for e in events};check(len(events)==len(eventids)==21,'event count')
for e in events:
 loc=next((l for l in locations if l['anchor']==e['source_clause_id']),None);check(loc is not None,'event location missing')
 if loc:
  body=(R/loc['file']).read_text();check(not re.search(r'虚构|合成|测试事实|本测试|TENANT-|ORG-|ROLE-|PRJ-',body),'business event contains testing markers '+e['event_id']);check(loc['text'] in body,'event content changed unexpectedly')
 check(all(x in eventids for x in e['supersedes_event_ids']),'event lineage')
for g in readl('05_private_gold_DO_NOT_INGEST/extraction_gold.jsonl'):
 f=g['expected_fields'];check(sum(f['payment_installments'])==f['total_inclusive_tax'],'installment sum '+g['doc_id']);check(f['document_status']=='unsigned_draft','visible synthetic status gold');check(all(x in anchors for x in g['source_clauses']),'gold clause source')
queries=readl('04_queries/queries.jsonl');recall=readl('05_private_gold_DO_NOT_INGEST/recall_gold.jsonl');check(len(queries)==len(recall)==24,'retain original Q01-Q24')
for g in recall:check(set(g['expected_evidence'])<=anchors,'query source '+g['query_id'])
inputs=readj('00_start_here/input_manifest_OPERATOR_ONLY.json');imap={r['input_id']:r for r in inputs};stages=readj('00_start_here/temporal_stages_OPERATOR_ONLY.json')
for st in stages:
 for iid in st['allowed_history_input_ids']:
  check(iid in imap and imap[iid]['available_at']<=st['as_of'],'future stage leak '+iid);check((R/imap[iid]['path']).is_file(),'missing input '+iid)
 check('组织L3' not in st['isolation'],'outdated organization-L3 description')
v2cases=manifest('v2_cases.json');v2steps=manifest('v2_steps.json')
v2ids={c['case_id'] for c in v2cases};v2sids={t['step_id'] for t in v2steps}
check(len(v2cases)==9 and len(v2steps)==27,'v2 suite census')
check(len(v2ids)==len(v2cases) and len(v2sids)==len(v2steps),'v2 IDs unique')
for c in v2cases:
 check(set(c['step_ids'])<=v2sids and bool(c['step_ids']),'v2 step mapping '+c['case_id'])
 check(set(c['source_anchors'])<=anchors,'v2 clause mapping '+c['case_id'])
 check(set(c['source_steps'])<=v2sids,'v2 dialogue/feedback source '+c['case_id'])
for t in v2steps:
 check(set(t['case_ids'])<=v2ids,'v2 case mapping '+t['step_id'])
 if t.get('input_id'):check(t['input_id'] in imap,'v2 input '+t['step_id'])
 if t['action']=='risk_feedback':check(t['risk_id']=='EX-PAY' and bool(t['note']),'v2 real feedback operation')
cases=manifest('cases.json');steps=manifest('steps.json');coverage=manifest('clause_coverage.json');categories=manifest('categories.json');dialogues=manifest('dialogues.json')
check(len({c['case_id'] for c in cases})==len(cases),'duplicate case IDs');check(len({s['step_id'] for s in steps})==len(steps),'duplicate steps')
caseids={c['case_id'] for c in cases};stepids={s['step_id'] for s in steps};allanchors=anchors|set(dialogues)
for c in cases:
 check(bool(c['step_ids']) and set(c['step_ids'])<=stepids,'unscheduled case '+c['case_id']);check(set(c['source_anchors'])<=allanchors,'unknown clause '+c['case_id']);check(bool(c['expected']) and bool(c['forbidden']),'case rubric missing')
for category in categories:
 polarities={c['polarity'] for c in cases if c['category']==category};check({'positive','negative'}<=polarities,'missing positive/negative coverage '+category)
for s in steps:
 check(set(s['case_ids'])<=caseids,'unknown step case')
 if s.get('input_id') and s['action']!='seed_quarantine':
  iid=s['input_id'];check(iid in imap,'unknown step input '+iid)
  if iid in imap:
   check(not any(n in imap[iid]['path'] for n in ['05_private_gold','09_scenarios','06_negative_controls']),'forbidden upload path')
   if s.get('as_of'):check(imap[iid]['available_at']<=s['as_of'],'future input in step '+s['step_id'])
 if s['action']=='seed_quarantine':check(s['actor']=='outsider' and s['team']=='X','quarantine seed not isolated')
check(len([p for p in coverage if p['clause_number'] is not None])==154,'all clauses annotated')
check(all(p['coverage_role'] in {'主测条款','背景条款'} for p in coverage),'coverage role missing')
check(next(s['step_id'] for s in steps if s.get('query_id')=='Q24')<next(s['step_id'] for s in steps if s.get('input_id')=='F01-R2'),'revision leaks into earlier Q24')
checksum=R/'SHA256SUMS'
if checksum.exists():
 for line in checksum.read_text().splitlines():
  digest,name=line.split('  ',1);p=R/name;check(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==digest,'checksum mismatch '+name)
report={'result':'PASS' if not errors else 'FAIL','checks':checks,'contracts':len(contracts),'clauses':154,'source_events':len(events),'original_queries':24,'contract_v2_cases':len(v2cases),'contract_v2_steps':len(v2steps),'cases':len(cases),'steps':len(steps),'categories':len(categories),'pack_sha':pack_digest(),'errors':errors,'scope':'Offline materials/manifests only. No real model, application upload, extraction, publication or judge run.'}
print(json.dumps(report,ensure_ascii=False,indent=2));sys.exit(bool(errors))
