#!/usr/bin/env python3
"""Deterministic fixture checks only; never calls OpenHarvey or a model."""
import json,re,sys,zipfile,hashlib
from pathlib import Path
from xml.etree import ElementTree as ET
R=Path(__file__).resolve().parents[1];errors=[];checks=0

def check(ok,msg):
 global checks
 checks+=1
 if not ok:errors.append(msg)
def readj(p):return json.loads((R/p).read_text())
def readl(p):return [json.loads(l) for l in (R/p).read_text().splitlines() if l.strip()]
for p in R.rglob('*.json'):
 if '08_validation' in p.parts:continue
 try:json.loads(p.read_text());checks+=1
 except Exception as e:errors.append(f'JSON {p}: {e}')
for p in R.rglob('*.jsonl'):
 try:[json.loads(l) for l in p.read_text().splitlines() if l.strip()];checks+=1
 except Exception as e:errors.append(f'JSONL {p}: {e}')
manifest=readj('00_start_here/contract_manifest.json');check(len(manifest)==10,'contract count not 10');check(sum(m['split']=='history' for m in manifest)==6,'history count');anchors=set();ids=set()
for row in manifest:
 cid=row['doc_id'];check(cid not in ids,'duplicate '+cid);ids.add(cid);body=(R/row['txt_path']).read_text();found=re.findall(r'\[('+cid+r'-C\d{2})\]',body)
 check(found==[f'{cid}-C{i:02d}' for i in range(1,15)],cid+' clause numbering');anchors.update(found)
 check('原创虚构' in body and '未签署' in body,cid+' missing provenance');check(len(body)>1800,cid+' stub text')
 with zipfile.ZipFile(R/row['docx_path']) as z:
  doc=ET.fromstring(z.read('word/document.xml'));w='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
  txt=''.join(el.text or '' for el in doc.iter(w+'t'))
  for anchor in found:check(anchor in txt,cid+' DOCX missing '+anchor)
  styles=ET.fromstring(z.read('word/styles.xml'));check(not list(styles.iter(w+'pBdr')),cid+' style border residue')
  for a in ['C05','C06','C07']:check(cid+'-'+a in txt,cid+' missing core clause')
for row in readl('05_private_gold_DO_NOT_INGEST/extraction_gold.jsonl'):
 f=row['expected_fields'];check(sum(f['payment_installments'])==f['total_inclusive_tax'],row['doc_id']+' sum mismatch');check(f['our_entity_id']=='ORG-HZ-001',row['doc_id']+' our identity')
 expected=f['party_a_entity_id'] if f['our_contract_role']=='甲方' else f['party_b_entity_id'];check(expected==f['our_entity_id'],row['doc_id']+' role mismatch')
 for fact in row['key_obligations']:
  check(fact['clause_id'] in anchors,'unknown fact anchor')
  if fact['topic']=='secondary_training_permission':check(fact['permission_grantor_entity_id']=='ORG-HZ-001' and fact['obligor_entity_id'] is None,'permission mapping')
events=[]
for n in ['reviewer_comments','final_decisions_and_updates','policies']:events+=readl('02_review_writeback/operator_only_indexes/'+n+'.jsonl')
check(len(events)==21,'event count');event_ids={e['event_id'] for e in events};check(len(event_ids)==21,'duplicate events')
anchors.update(e['source_clause_id'] for e in events)
for e in events:
 ep=R/'02_review_writeback/event_files'/f"{e['recorded_at'][:10]}_{e['event_id']}.txt"
 check(ep.exists(),'missing per-event TXT '+e['event_id']);check(e['source_clause_id'] in ep.read_text(),'event anchor missing');check(bool(e['authority_scope']),'missing authority')
 check(all(s in event_ids for s in e['supersedes_event_ids']),'unknown event lineage')
q=readl('04_queries/queries.jsonl');g=readl('05_private_gold_DO_NOT_INGEST/recall_gold.jsonl');check(len(q)==24 and len(g)==24,'query counts');check({x['query_id'] for x in q}=={x['query_id'] for x in g},'query gold mismatch')
mem=readl('05_private_gold_DO_NOT_INGEST/expected_memories.jsonl');mids={m['memory_id'] for m in mem};check(len(mem)==15,'memory count')
for m in mem:
 check(all(s in event_ids for s in m['source_ids']),m['memory_id']+' unknown sources');check(all(a in anchors for a in m['document_refs']),m['memory_id']+' unknown anchors')
for row in g:
 check(all(a in anchors for a in row['expected_evidence']),row['query_id']+' unknown evidence')
 check(all(m in mids for m in row['required_memory_ids']),row['query_id']+' unknown memory')
 check(all(m in mids or m=='NEG-XTENANT-01' for m in row['must_not_apply_as_authority']),row['query_id']+' unknown forbidden memory')
inputs=readj('00_start_here/input_manifest_OPERATOR_ONLY.json');imap={r['input_id']:r for r in inputs};stages=readj('00_start_here/temporal_stages_OPERATOR_ONLY.json');versions=readl('05_private_gold_DO_NOT_INGEST/expected_memory_versions.jsonl')
for s in stages:
 for inputid in s['allowed_history_input_ids']:
  check(inputid in imap,'unknown stage input');r=imap[inputid];check(r['available_at']<=s['as_of'],'future stage leakage');check(r['kind']!='future_contract','future contract in history');check((R/r['path']).exists(),'missing stage file')
 snap=readl('05_private_gold_DO_NOT_INGEST/'+s['stage']+'_memory_snapshot.jsonl')
 check(len({r['memory_id'] for r in snap})==len(snap),'overlapping version')
 for m in snap:
  check(m['known_from']<=s['as_of'] and (m['known_until_exclusive'] is None or s['as_of']<m['known_until_exclusive']),'wrong snapshot version')
  for source in m['source_ids']:check(next(e for e in events if e['event_id']==source)['recorded_at']<=s['as_of'],'snapshot future source '+source)
for doc in readl('05_private_gold_DO_NOT_INGEST/future_review_expectations.jsonl'):check(doc['actual_final_contract_decision'] is None,'future actual label leak')
# Verify checksums only when distribution checksum manifest has been created.
checksum=R/'SHA256SUMS'
if checksum.exists():
 for line in checksum.read_text().splitlines():
  digest,name=line.split('  ',1);p=R/name;check(p.exists() and hashlib.sha256(p.read_bytes()).hexdigest()==digest,'checksum mismatch '+name)
report={'result':'PASS' if not errors else 'FAIL','checks':checks,'contracts':len(manifest),'history_contracts':6,'future_contracts':4,'clauses':140,'source_events':len(events),'queries':len(q),'current_gold_memories':len(mem),'memory_versions':len(versions),'temporal_stages':len(stages),'errors':errors,'scope':'Local fixture integrity only. No OpenHarvey runtime, model extraction, retrieval or memory writeback was executed.'}
print(json.dumps(report,ensure_ascii=False,indent=2));sys.exit(1 if errors else 0)
