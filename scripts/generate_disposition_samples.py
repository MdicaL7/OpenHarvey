"""Generate synthetic shared fixtures using the production L0 formatter.

Run from repository root: python -m scripts.generate_disposition_samples
"""
import json
from pathlib import Path
from contract_web.contract_precedents import ContractPrecedents


def samples():
    base = dict(schema_version=1, workspace_id='sample-workspace', report_id='sample-report',
                risk_id='SAMPLE-PAYMENT', document_version='sample-document-v1',
                risk_definition_hash='sample-risk-definition-v1', document_refs=[],
                contract_title='虚构采购合同', risk_name='付款条件', topic='付款', our_role='采购方',
                created_at='2026-10-14T00:00:00+00:00')
    cases = [('valid', 1, '接受风险', '仅限本项目，预付款为20%，须先核验保函。'),
             ('revision', 2, '要求修改', '修订：预付款调整为10%，保函条件保留。'),
             ('blank', 3, '要求修改', '  \n  '),
             ('withdraw_to_pending', 4, '待处理', '')]
    result = []
    for name, revision, decision, note in cases:
        payload = {**base, 'event_id': f'sample-event-{revision}', 'revision': revision,
                   'decision': decision, 'note': note}
        result.append({'name': name, 'payload': payload,
                       'message': ContractPrecedents.format_disposition_message(payload),
                       'expected_valid_case': bool(note.strip()) and decision != '待处理',
                       'illustrative_l0_id': f'sample-l0-{revision}'})
    return result


if __name__ == '__main__':
    Path('docs/disposition-samples.json').write_text(json.dumps(samples(), ensure_ascii=False, indent=2) + '\n')
