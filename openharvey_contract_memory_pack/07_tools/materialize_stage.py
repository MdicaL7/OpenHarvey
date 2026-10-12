#!/usr/bin/env python3
"""Materialize only causal TXT inputs. No network, no model, no application writes."""
import argparse,json,shutil
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--stage',required=True);p.add_argument('--out',required=True);a=p.parse_args()
root=Path(__file__).resolve().parents[1]
stages=json.loads((root/'00_start_here/temporal_stages_OPERATOR_ONLY.json').read_text())
match=[s for s in stages if s['stage']==a.stage]
if not match:raise SystemExit('Unknown stage. Choices: '+', '.join(s['stage'] for s in stages))
stage=match[0];out=Path(a.out).resolve()
if out.exists() and any(out.iterdir()):raise SystemExit('Refusing a non-empty destination; use a fresh directory to prevent future-data contamination.')
manifest=json.loads((root/'00_start_here/input_manifest_OPERATOR_ONLY.json').read_text())
allowed=set(stage['allowed_history_input_ids']);selected=sorted([r for r in manifest if r['input_id'] in allowed],key=lambda r:(r['available_at'],r['input_id']))
for r in selected:
 target=out/'UPLOAD_HISTORY_ONLY'/Path(r['path']).name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/r['path'],target)
future=set(stage['held_out_future_input_ids'])
for r in manifest:
 if r['input_id'] in future:
  target=out/'HELD_OUT_UPLOAD_ONE_PER_NEW_WORKSPACE'/Path(r['path']).name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/r['path'],target)
qs=[q for q in (json.loads(x) for x in (root/'04_queries/queries.jsonl').read_text().splitlines()) if q['query_id'] in stage['query_ids']]
(out/'upload_order_OPERATOR_ONLY.jsonl').write_text(''.join(json.dumps(dict(r,upload_file=Path(r['path']).name),ensure_ascii=False)+'\n' for r in selected))
(out/'questions_OPERATOR_ONLY.jsonl').write_text(''.join(json.dumps(q,ensure_ascii=False)+'\n' for q in qs))
(out/'stage_manifest_OPERATOR_ONLY.json').write_text(json.dumps(stage,ensure_ascii=False,indent=2))
print(json.dumps({'stage':a.stage,'as_of':stage['as_of'],'history_inputs':len(selected),'future_inputs':len(future),'query_count':len(qs),'out':str(out)},ensure_ascii=False,indent=2))
