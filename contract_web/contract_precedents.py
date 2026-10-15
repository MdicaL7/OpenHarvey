"""Saved risk dispositions: durable delivery via standard L0/L1 APIs and local precedent filtering/reranking."""
import asyncio
import datetime
import hashlib
import json
import re
import time
import urllib.parse
from fastapi import HTTPException
from .contract_memory import MemoryTransportError
from .settings import encoded
from .store import digest
from .tencentdb_memory import PROVIDER, binding_directory

DISPOSITION_HEADER = '[CONTRACT_RISK_DISPOSITION]'
METADATA_KEYS = (
    'schema_version', 'event_id', 'workspace_id', 'document_version', 'document_refs',
    'report_id', 'risk_id', 'risk_name', 'topic', 'risk_definition_hash',
    'our_role', 'decision', 'note', 'revision', 'created_at',
)
DEMAND_ROLES = ('采购方', '买方', '买受人', '采购人', '委托方', '委托人', '发包方', '发包人')
SUPPLY_ROLES = ('供货方', '供应方', '供应商', '卖方', '出卖人', '销售方', '受托方', '受托人', '服务方', '服务商', '承包方', '承包人')
PROJECT_SCOPE_KEYWORDS = ('仅限本项目', '仅本项目', '仅限本合同', '仅本合同', '仅限', '仅适用于', '本项目', '本合同', '个案', '特批')
CONDITION_KEYWORDS = ('条件', '前提', '必须', '若', '如果', '待', '后再', '保函', '预付款', '要求', '先核验')
EXCEPTION_KEYWORDS = ('不照搬', '除外', '例外', '仍以', '未核验', '尚未核验')


def message_length(value):
    # Native Zod string.max counts UTF-16 code units, including astral text.
    return len(value.encode('utf-16-le')) // 2


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class ContractPrecedents:
    def __init__(self, memory, risks=None):
        self.memory, self.store = memory, memory.store
        self.risks = risks
        self.worker = None
        self.cache = {}
        self.lock = asyncio.Lock()
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS contract_memory_outbox (
              id TEXT PRIMARY KEY,user_id TEXT,team_id TEXT,workspace_id TEXT,artifact_id TEXT,risk_id TEXT,
              data TEXT,status TEXT,attempts INTEGER DEFAULT 0,next_attempt REAL DEFAULT 0,error TEXT,created REAL);
            CREATE TABLE IF NOT EXISTS contract_memory_deliveries (
              event_id TEXT NOT NULL, backend TEXT NOT NULL, batch TEXT NOT NULL,
              status TEXT NOT NULL, attempts INTEGER DEFAULT 0, error TEXT,
              l0_id TEXT, l1_id TEXT, data TEXT NOT NULL, PRIMARY KEY(event_id,backend));
            CREATE TABLE IF NOT EXISTS contract_memory_delivery_history (
              id INTEGER PRIMARY KEY, event_id TEXT NOT NULL, snapshot TEXT NOT NULL, created REAL NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS contract_memory_l0 ON contract_memory_deliveries(backend,l0_id);
            ''')

    @staticmethod
    def disposition_metadata(payload):
        return {k: payload.get(k) for k in METADATA_KEYS}

    @classmethod
    def format_disposition_message(cls, payload):
        meta = cls.disposition_metadata(payload)
        title = payload.get('contract_title') or payload.get('contract_filename') or meta.get('workspace_id') or ''
        role_text = meta.get('our_role') or payload.get('perspective') or '未明确角色'
        clause = (payload.get('clause_text') or '').strip()
        lines = [
            DISPOSITION_HEADER,
            f"合同：{title}",
            f"交易角色：{role_text}",
            f"风险项：{meta['risk_name']}（{meta['risk_id']}，主题：{meta['topic']}）",
            f"处置决定：{meta['decision']}（第 {meta['revision']} 版）",
            f"处置说明：{meta['note'] or '未填写处置理由'}",
        ]
        if clause:
            lines.append(f"关联条款原文：{clause}")
        lines.append('这是已保存的处置事件。接受风险不代表正式审批；要求修改不代表修改已完成。待处理或撤回不是有效案例。仅当有效处置的 note.trim() 非空时提炼 L1，不增加质量或数量门槛。')
        lines.append('METADATA_JSON: ' + encoded(meta))
        return '\n'.join(lines)

    @staticmethod
    def role_side(role):
        if not role or not isinstance(role, str):
            return None
        has_demand = any(k in role for k in DEMAND_ROLES)
        has_supply = any(k in role for k in SUPPLY_ROLES)
        if has_demand and not has_supply:
            return 'demand'
        if has_supply and not has_demand:
            return 'supply'
        return None

    @classmethod
    def is_opposite_role(cls, current_role, case_role):
        s1, s2 = cls.role_side(current_role), cls.role_side(case_role)
        return bool(s1 and s2 and s1 != s2)

    def resolve_role(self, u, workspace_id, document_version, perspective, explicit_role=None):
        if explicit_role and explicit_role not in {'甲方', '乙方'}:
            return explicit_role
        role = perspective if perspective and perspective not in {'甲方', '乙方'} else None
        if role is None and perspective in {'甲方', '乙方'} and workspace_id:
            w = self.store.one('SELECT document_id FROM workspaces WHERE id=? AND user_id=?', (workspace_id, u['id']))
            if w:
                path = self.store.user_root(u['id']) / 'sources' / w['document_id'] / 'document.json'
                if path.is_file():
                    source = json.loads(path.read_text())
                    if not document_version or source.get('source_hash') == document_version:
                        pattern = re.compile(re.escape(perspective) + r'[（(](采购方|供货方|供应方|买方|卖方|委托方|受托方|服务方)[）)]')
                        for segment in source.get('segments', []):
                            match = pattern.search(segment['text'])
                            if match:
                                role = match[1]
                                break
        return role

    def document_refs(self, u, report):
        result = []
        for ref in report.get('evidence', []):
            doc = self.store.one('SELECT * FROM documents WHERE id=? AND user_id=? AND removed_at IS NULL', (ref.get('document_id'), u['id']))
            if not doc or doc['source_hash'] != ref.get('source_hash'):
                raise HTTPException(409, '历史处置引用的文档版本已变化')
            p = self.store.user_root(u['id']) / 'sources' / doc['id'] / 'document.json'
            data = json.loads(p.read_text()) if p.is_file() else {}
            block = next((s for s in data.get('segments', []) if s['id'] == ref.get('block_id')), None)
            if not block or ref.get('quote', '').strip() not in block['text'] or not ref.get('quote', '').strip():
                raise HTTPException(409, '处置引用无法核验')
            result.append({'document_id': doc['id'], 'version': doc['source_hash'], 'paragraph_id': block['id'], 'quote': ref['quote']})
        return result

    def current(self, u, row, report, rid, for_recall=False):
        w = self.store.one('SELECT * FROM workspaces WHERE id=? AND user_id=? AND deleted_at IS NULL', (row['workspace_id'], u['id']))
        if not w:
            raise HTTPException(404, '合同空间不存在')
        primary = self.store.one('SELECT source_hash FROM documents WHERE id=? AND user_id=? AND removed_at IS NULL', (w['document_id'], u['id']))
        if not primary or primary['source_hash'] != row['source_hash']:
            raise HTTPException(409, '报告对应的主合同版本已变化，请重新审查')
        if not w.get('team_id'):
            raise HTTPException(422, '此合同空间尚未启用合同记忆')
        self.memory.member(u, w['team_id'])
        f = next((x for x in report.get('findings', []) if x['risk_id'] == rid), None)
        if not f:
            raise HTTPException(404, '报告没有这项风险')
        scheme = report.get('execution_config', {}).get('risk_scheme', {})
        rule = next((x for x in scheme.get('rules', []) if x.get('id') == rid), {})
        if for_recall and self.risks:
            try:
                live = self.risks.choose(u, scheme.get('id'))
                rule = next((x for x in live['rules'] if x['id'] == rid), {})
                scheme = live
            except (ValueError, HTTPException):
                rule = {}
                scheme = {'revision': None}
        refs = self.document_refs(u, f)
        # Labels such as 甲方/乙方 alone do not establish transaction roles.
        perspective = report.get('perspective')
        role = self.resolve_role(u, w['id'], row['source_hash'], perspective)
        return {
            'workspace_id': w['id'], 'team_id': w['team_id'], 'risk_id': rid,
            'contract_title': w['title'],
            'contract_filename': (self.store.one('SELECT filename FROM documents WHERE id=?', (w['document_id'],)) or {}).get('filename'),
            'risk_name': f.get('risk_name', rule.get('name', rid)),
            'topic': f.get('category', rule.get('category', rule.get('name', rid))),
            'risk_definition': rule,
            'risk_definition_hash': fingerprint(rule or {'id': rid, 'name': f.get('risk_name', rid)}),
            'risk_scheme_version': scheme.get('revision', scheme.get('version')),
            'perspective': perspective, 'our_role': role,
            'document_version': row['source_hash'], 'document_refs': refs,
            'clause_text': '\n'.join(r['quote'] for r in refs),
            'verdict': f.get('verdict'), 'report_id': row['id'],
        }

    def enqueue(self, db, u, row, report, rid, decision, note, revision, created, batch='live'):
        w = self.store.one('SELECT * FROM workspaces WHERE id=? AND user_id=?', (row['workspace_id'], u['id']))
        if not w or not w.get('team_id'):
            return 'not_connected'
        # Only reports actually run through the managed Memory provider produce events.
        if report.get('execution_config', {}).get('model', {}).get('providerID') != PROVIDER:
            return 'not_enabled'
        current = self.current(u, row, report, rid)
        binding, _, uid = self.memory.binding(u)
        team = self.memory.member(u, w['team_id'])
        thread = self.store.one('SELECT * FROM threads WHERE id=?', (row['thread_id'],))
        task = self.store.one('SELECT task_id FROM tdai_workspaces WHERE workspace_id=? AND user_id=?', (w['id'], u['id']))
        event_id = 'feedback_' + fingerprint([row['id'], rid, revision])
        created_iso = datetime.datetime.fromtimestamp(created, datetime.timezone.utc).isoformat()
        payload = {
            **current, 'target': [binding['core_url'], binding['service_id'], team['tdai_team_id'], team['agent_id'], uid], 'schema_version': 1, 'event_id': event_id, 'actor_user_id': uid,
            'session_id': thread['session_id'], 'task_id': task['task_id'] if task else None,
            'decision': decision, 'note': note, 'revision': revision, 'created_at': created_iso,
        }
        metadata = self.disposition_metadata(payload)
        message = self.format_disposition_message(payload)
        payload['metadata'] = metadata
        payload['message'] = message
        payload['messages'] = [{'role': 'user', 'content': message}]
        db.execute(
            'INSERT OR IGNORE INTO contract_memory_outbox(id,user_id,team_id,workspace_id,artifact_id,risk_id,data,status,created) VALUES(?,?,?,?,?,?,?,?,?)',
            (event_id, u['id'], w['team_id'], w['id'], row['id'], rid, encoded(payload), 'pending', created),
        )
        # Preserve old outbox history; delivery identity includes the target pipeline.
        cursor = db.execute('INSERT OR IGNORE INTO contract_memory_deliveries(event_id,backend,batch,status,data) VALUES(?,?,?,?,?)',
                            (event_id, 'native-v3', batch, 'pending' if message_length(message) <= 8192 else 'blocked_length', encoded(payload)))
        return ('pending' if message_length(message) <= 8192 else 'blocked_length') if cursor.rowcount else 'already_queued'

    def status(self, aid, rid, uid):
        r = self.store.one("SELECT o.id AS event_id,COALESCE(d.data,o.data) AS data,d.status,d.error,d.attempts,d.l0_id,d.l1_id FROM contract_memory_outbox o LEFT JOIN contract_memory_deliveries d ON d.event_id=o.id AND d.backend='native-v3' WHERE o.artifact_id=? AND o.risk_id=? AND o.user_id=? ORDER BY o.created DESC,o.rowid DESC LIMIT 1", (aid, rid, uid))
        if not r:
            return {'status': 'not_enabled'}
        payload = json.loads(r.pop('data'))
        r['status'] = r['status'] or 'legacy_not_delivered'
        r['feedback_saved'] = True
        r['l1_status'] = 'not_expected' if not (payload.get('note') or '').strip() or payload.get('decision') in {'待处理', '撤回'} else ('found' if r['l1_id'] else 'not_observed')
        return r

    async def flush(self):
        async with self.lock:
            rows = self.store.all("SELECT o.*,d.data AS delivery_data,d.status AS delivery_status,d.attempts AS delivery_attempts FROM contract_memory_outbox o JOIN contract_memory_deliveries d ON d.event_id=o.id WHERE d.backend='native-v3' AND d.status='pending' ORDER BY o.created LIMIT 10")
            for r in rows:
                sent = False
                try:
                    u = self.store.one('SELECT * FROM users WHERE id=? AND active=1', (r['user_id'],))
                    if not u:
                        raise HTTPException(403, '账号已停用')
                    team = self.memory.member(u, r['team_id'])
                    w = self.store.one('SELECT * FROM workspaces WHERE id=? AND user_id=? AND deleted_at IS NULL', (r['workspace_id'], u['id']))
                    if not w or w['team_id'] != team['id']:
                        raise HTTPException(403, '原合同已移除')
                    payload = json.loads(r['delivery_data'])
                    binding, _, uid = self.memory.binding(u)
                    if payload.get('target') != [binding['core_url'], binding['service_id'], team['tdai_team_id'], team['agent_id'], uid]:
                        raise HTTPException(409, 'Memory 目标身份已变化，请使用目标重新绑定预检；普通重试不能更换目标')
                    if not payload.get('task_id') or not payload.get('session_id'):
                        raise HTTPException(409, 'Task 或 Session 映射缺失')
                    payload.setdefault('schema_version', 1)
                    payload.setdefault('created_at', payload.get('created'))
                    content = self.format_disposition_message(payload)
                    if message_length(content) > 8192:
                        raise HTTPException(422, '完整处置事件超过 L0 8192 字上限，未截断；反馈已保存')
                    # Claim before network I/O. A crash/timeout is ambiguous, never auto-resend.
                    with self.store.connect() as db:
                        claimed = db.execute("UPDATE contract_memory_deliveries SET status='uncertain',attempts=attempts+1 WHERE event_id=? AND backend='native-v3' AND status='pending' AND data=? AND attempts=?", (r['id'], r['delivery_data'], r['delivery_attempts'])).rowcount
                    if not claimed:
                        continue
                    sent = True
                    result = await self.memory.remote(u, team, '/v3/conversation/add', {
                        'task_id': payload['task_id'], 'session_id': payload['session_id'],
                        'messages': [{'role': 'user', 'content': content}],
                    })
                    ids = result.get('accepted_ids') if isinstance(result, dict) else None
                    if not isinstance(ids, list) or len(ids) != 1 or not isinstance(ids[0], str) or not ids[0] or type(result.get('total_count')) is not int or result['total_count'] != 1:
                        raise HTTPException(503, 'L0 接收回执无效，投递结果未确认')
                    self.store.execute("UPDATE contract_memory_deliveries SET status='l0_received',l0_id=?,error=NULL WHERE event_id=? AND backend='native-v3' AND status='uncertain' AND attempts=?", (ids[0], r['id'], r['delivery_attempts'] + 1))
                except Exception as e:
                    safe = not sent or isinstance(e, MemoryTransportError) and e.safe_to_retry
                    self.store.execute("UPDATE contract_memory_deliveries SET status=?,error=? WHERE event_id=? AND backend='native-v3' AND status=? AND attempts=? AND data=?",
                                       ('blocked' if safe else 'uncertain', str(getattr(e, 'detail', '投递结果未确认，须核对远端')), r['id'], 'uncertain' if sent else 'pending', r['delivery_attempts'] + int(sent), r['delivery_data']))

    async def rebind(self, u, event_id, enqueue=False):
        row = self.store.one("SELECT d.* FROM contract_memory_deliveries d JOIN contract_memory_outbox o ON o.id=d.event_id WHERE d.event_id=? AND d.backend='native-v3' AND o.user_id=?", (event_id, u['id']))
        if not row:
            raise HTTPException(404, '投递记录不存在')
        if row['status'] != 'blocked' or row['l0_id']:
            raise HTTPException(409, '仅确定未发送且 blocked 的任务可重新绑定；pending、结果不明和已接收任务不可重绑定')
        old = json.loads(row['data'])
        artifact = self.store.one('SELECT * FROM artifacts WHERE id=?', (old['report_id'],))
        if not artifact:
            raise HTTPException(409, '原报告不存在，不能重新绑定')
        try:
            report = json.loads((self.store.user_root(u['id']) / 'published' / artifact['id'] / 'report.json').read_text())
        except (OSError, ValueError):
            raise HTTPException(409, '原报告不可读，不能重新绑定') from None
        context = self.current(u, artifact, report, old['risk_id'])
        if context['team_id'] != old['team_id']:
            raise HTTPException(409, '本接口不支持跨本地团队迁移旧事件；请恢复原合同团队映射或保存新反馈')
        feedback = self.store.one('SELECT * FROM risk_feedback WHERE artifact_id=? AND risk_id=? AND user_id=? ORDER BY revision DESC LIMIT 1', (artifact['id'], old['risk_id'], u['id']))
        if not feedback or any(feedback[k] != old[k] for k in ('revision', 'decision', 'note')):
            raise HTTPException(409, '该事件已被新反馈替代，不可重新绑定')
        if context['document_version'] != old['document_version'] or context['risk_definition_hash'] != old['risk_definition_hash']:
            raise HTTPException(409, '文档或风险定义变化，不可重新绑定旧事件')
        team = self.memory.member(u, context['team_id'])
        binding, key, uid = self.memory.binding(u)
        task = self.store.one('SELECT task_id FROM tdai_workspaces WHERE workspace_id=? AND user_id=?', (context['workspace_id'], u['id']))
        thread = self.store.one('SELECT * FROM threads WHERE id=? AND workspace_id=? AND deleted_at IS NULL', (artifact['thread_id'], context['workspace_id']))
        if not task or not thread or not thread['session_id']:
            raise HTTPException(409, '当前配置缺少本合同 Task/Session 映射；须先由管理员修复映射')
        # Session IDs are local runtime identifiers, not remote meta entities.
        # Verify local ownership plus the authorized remote user/team/agent/task graph.
        async def meta(path, body):
            return await self.memory.tdai.call(binding, '/v3/meta/' + path, body, key)
        verified = await meta('auth/verify', {'user_key': key})
        agent = await meta('agent/get', {'agent_id': team['agent_id']})
        remote_task = await meta('task/get', {'task_id': task['task_id']})
        membership = await meta('team-member/get', {'team_id': team['tdai_team_id'], 'user_id': uid})
        links = await meta('task-agent/list', {'task_id': task['task_id'], 'limit': 100, 'offset': 0})
        if (verified.get('valid') is not True or (verified.get('user') or {}).get('user_id') != uid
                or membership.get('status') != 'active'
                or agent.get('team_id') != team['tdai_team_id'] or agent.get('status') != 'active'
                or remote_task.get('team_id') != team['tdai_team_id'] or remote_task.get('creator_user_id') != uid
                or remote_task.get('status') not in {'running', 'completed'}
                or not any(x.get('agent_id') == team['agent_id'] and x.get('status') == 'active' for x in links.get('items', []))):
            raise HTTPException(409, '当前授权配置不能验证新目标归属（Task-Agent 最多核验前 100 项）；须由管理员配置用户、团队、Agent 和 Task 关联后再预检，不能仅更换地址')
        payload = {**old, 'target': [binding['core_url'], binding['service_id'], team['tdai_team_id'], team['agent_id'], uid],
                   'actor_user_id': uid, 'task_id': task['task_id'], 'session_id': thread['session_id']}
        if message_length(self.format_disposition_message(payload)) > 8192:
            raise HTTPException(409, '正文超限，不可重新入队')
        token = fingerprint([row, payload])
        if not enqueue:
            return {'eligible': True, 'event_id': event_id, 'preview_token': token, 'writes': 0}
        if enqueue != token:
            raise HTTPException(409, '目标或任务已变化，请重新进行目标预检')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            # Recheck local config after the remote verification wait.
            latest_binding, _, latest_uid = self.memory.binding(u)
            latest_team = self.memory.member(u, context['team_id'])
            if payload['target'] != [latest_binding['core_url'], latest_binding['service_id'], latest_team['tdai_team_id'], latest_team['agent_id'], latest_uid]:
                raise HTTPException(409, '授权配置已变化，请重新预检')
            latest_context = self.current(u, artifact, report, old['risk_id'])
            latest_feedback = self.store.one('SELECT * FROM risk_feedback WHERE artifact_id=? AND risk_id=? AND user_id=? ORDER BY revision DESC LIMIT 1', (artifact['id'], old['risk_id'], u['id']))
            latest_task = self.store.one('SELECT task_id FROM tdai_workspaces WHERE workspace_id=? AND user_id=?', (context['workspace_id'], u['id']))
            latest_thread = self.store.one('SELECT * FROM threads WHERE id=? AND workspace_id=? AND deleted_at IS NULL', (thread['id'], context['workspace_id']))
            if latest_context != context or latest_feedback != feedback or latest_task != task or latest_thread != thread:
                raise HTTPException(409, '本地来源或映射已变化，请重新预检')
            count = db.execute("UPDATE contract_memory_deliveries SET data=?,status='pending',error=NULL,batch=? WHERE event_id=? AND backend='native-v3' AND status='blocked' AND data=? AND attempts=? AND l0_id IS NULL", (encoded(payload), 'rebind-' + str(time.time_ns()), event_id, row['data'], row['attempts'])).rowcount
            if count:
                db.execute('INSERT INTO contract_memory_delivery_history(event_id,snapshot,created) VALUES(?,?,?)', (event_id, encoded(row), time.time()))
        return {'queued': count, 'event_id': event_id, 'target_backend': 'native-v3'}

    async def start(self):
        async def loop():
            while True:
                await self.flush()
                await asyncio.sleep(3)
        self.worker = asyncio.create_task(loop())

    async def close(self):
        if self.worker:
            self.worker.cancel()
            try:
                await self.worker
            except asyncio.CancelledError:
                pass

    def parse_candidate(self, raw):
        if not isinstance(raw, dict):
            return None
        source_ids = raw.get('source_message_ids')
        if not isinstance(source_ids, list) or not source_ids or any(not isinstance(x, str) or not x for x in source_ids):
            return None
        events = []
        for mid in set(source_ids):
            row = self.store.one("SELECT d.data FROM contract_memory_deliveries d JOIN contract_memory_outbox o ON o.id=d.event_id WHERE d.backend='native-v3' AND d.l0_id=? AND d.status='l0_received'", (mid,))
            if not row:
                return None
            events.append(json.loads(row['data']))
        # A merged atomic cannot safely transfer conditions across multiple events.
        if len({x['event_id'] for x in events}) != 1:
            return None
        d = events[0]
        if not (d.get('note') or '').strip():
            return None
        metadata = raw.get('metadata') if isinstance(raw.get('metadata'), dict) else {}
        extracted = {k: [x for x in metadata[k] if isinstance(x, str)] for k in ('conditions', 'exceptions') if isinstance(metadata.get(k), list)}
        extracted['summary'] = raw.get('content') or ''
        d = {**d, **extracted}
        return {'id': raw.get('id'), 'version': d['revision'], 'workspace': d['workspace_id'], 'data': d}

    def allowed_case(self, u, team, c):
        d = c.get('data') if isinstance(c.get('data'), dict) else c
        binding, _, uid = self.memory.binding(u)
        if d.get('target') != [binding['core_url'], binding['service_id'], team['tdai_team_id'], team['agent_id'], uid]:
            return False
        workspace_id = c.get('workspace') or d.get('workspace_id')
        w = self.store.one('SELECT * FROM workspaces WHERE id=? AND user_id=? AND team_id=? AND deleted_at IS NULL', (workspace_id, u['id'], team['id']))
        if not w:
            return False
        # Validate the original immutable contract version and latest saved feedback.
        a = self.store.one('SELECT a.* FROM artifacts a JOIN workspaces w ON w.id=a.workspace_id WHERE a.id=? AND w.user_id=?', (d.get('report_id'), u['id']))
        if not a or a['workspace_id'] != w['id'] or a['source_hash'] != d.get('document_version'):
            return False
        doc = self.store.one('SELECT source_hash FROM documents WHERE id=? AND removed_at IS NULL', (w['document_id'],))
        if not doc or doc['source_hash'] != d.get('document_version'):
            return False
        for ref in d.get('document_refs', []):
            source = self.store.one('SELECT source_hash FROM documents WHERE id=? AND user_id=? AND workspace_id=? AND removed_at IS NULL', (ref.get('document_id'), u['id'], w['id']))
            if not source or source['source_hash'] != ref.get('version'):
                return False
        f = self.store.one('SELECT decision,note,revision FROM risk_feedback WHERE artifact_id=? AND risk_id=? AND user_id=? ORDER BY revision DESC LIMIT 1', (d.get('report_id'), d.get('risk_id'), u['id']))
        return bool(f and f['revision'] == d.get('revision') and f['decision'] == d.get('decision') and f['note'] == d.get('note') and f['decision'] not in {'待处理', '撤回'})

    def evaluate_case(self, current, c):
        d = c['data']
        version = int(d.get('revision') or c.get('version') or 1)
        note = d.get('note') or ''
        matching_points = list(d.get('matching_points') or [])
        differences = list(d.get('differences') or [])
        is_conditional = False

        if d.get('risk_id') == current.get('risk_id'):
            if not matching_points:
                matching_points.append(f"同属风险项「{current.get('risk_name') or d.get('risk_name') or d.get('risk_id')}」")
        else:
            is_conditional = True
            differences.append(f"历史案例针对「{d.get('risk_name') or d.get('risk_id')}」，与当前风险项不同")

        cur_role = current.get('our_role') or current.get('perspective')
        case_role = d.get('our_role') or d.get('perspective')
        cur_side = self.role_side(cur_role)
        case_side = self.role_side(case_role)
        if cur_side and case_side and cur_side == case_side:
            matching_points.append(f"我方交易角色一致（{d.get('our_role') or current.get('our_role')}）")
        else:
            is_conditional = True
            differences.append('当前合同或历史案例的交易角色未明确，需结合合同原文核对交易立场')

        if current.get('risk_definition_hash') and d.get('risk_definition_hash'):
            if current['risk_definition_hash'] == d['risk_definition_hash']:
                matching_points.append('风险审查标准定义一致')
            else:
                is_conditional = True
                differences.append('当前风险审查标准已变化，不能直接套用旧标准下的处置意见')
        else:
            is_conditional = True
            differences.append('缺少完整风险定义哈希比对依据，需核对现行审查标准')

        raw_conditions = list(d.get('conditions') or [])
        has_project_limit = any(k in note for k in PROJECT_SCOPE_KEYWORDS) or any(
            any(k in str(cond) for k in PROJECT_SCOPE_KEYWORDS) for cond in raw_conditions
        )
        has_condition_note = any(k in note for k in CONDITION_KEYWORDS)
        if has_project_limit:
            is_conditional = True
            differences.append('历史处置含“仅限本项目/本合同”等范围限制，不能跨合同直接视为批准')
        elif has_condition_note:
            is_conditional = True
            differences.append('历史处置附带特定前提条件，需核对当前合同是否满足相同条件')

        if not raw_conditions and note:
            clauses = [s.strip() for s in re.split(r'[；;。！!\n]+', note) if s.strip()]
            raw_conditions = [s for s in clauses if any(k in s for k in (*PROJECT_SCOPE_KEYWORDS, *CONDITION_KEYWORDS))]
            if not raw_conditions and is_conditional:
                raw_conditions = [note.strip()]

        raw_exceptions = list(d.get('exceptions') or [])
        if not raw_exceptions and note:
            clauses = [s.strip() for s in re.split(r'[；;。！!\n]+', note) if s.strip()]
            raw_exceptions = [s for s in clauses if any(k in s for k in EXCEPTION_KEYWORDS)]

        if raw_conditions or raw_exceptions or d.get('summary'):
            is_conditional = True
            differences.append('提炼内容、条件或例外尚未对当前合同核验')

        if d.get('relation') in {'applicable', 'conditional', 'insufficient'} and not is_conditional:
            relation = d['relation']
        else:
            relation = 'conditional' if is_conditional else 'applicable'

        reason = d.get('reason') or (
            '历史处置与当前风险标准、交易角色一致，可结合当前合同原文参考。'
            if relation == 'applicable'
            else '历史处置存在项目限定、标准差异或附加前提条件，需结合当前合同原文核对后参考。'
        )
        source_url = '/agent?artifact=' + str(d['report_id']) + '&risk=' + urllib.parse.quote(str(d['risk_id'])) + '#' + str(c['workspace'])
        return {
            'case_id': c['id'],
            'version': version,
            'workspace_id': c['workspace'],
            'report_id': d['report_id'],
            'risk_id': d['risk_id'],
            'decision': d['decision'],
            'note': note,
            'conditions': raw_conditions,
            'exceptions': raw_exceptions,
            'document_version': d['document_version'],
            'relation': relation,
            'matching_points': matching_points,
            'differences': differences,
            'reason': reason,
            'source_url': source_url,
            'summary': d.get('summary', ''),
            'source_label': '查看历史合同处理意见',
        }

    def rank_key(self, current, c, item):
        d = c['data']
        same_risk = 1 if d.get('risk_id') == current.get('risk_id') else 0
        same_topic = 1 if d.get('topic') and d.get('topic') == current.get('topic') else 0
        same_hash = 1 if current.get('risk_definition_hash') and d.get('risk_definition_hash') == current.get('risk_definition_hash') else 0
        cur_side = self.role_side(current.get('our_role') or current.get('perspective'))
        case_side = self.role_side(d.get('our_role') or d.get('perspective'))
        same_role = 1 if (cur_side and case_side and cur_side == case_side) else 0
        applicable = 1 if item.get('relation') == 'applicable' else 0
        return (same_risk, same_topic, same_hash, same_role, applicable, int(d.get('revision') or c.get('version') or 1))

    def usable_count(self, u, team, current, records):
        keys = set()
        for raw in records:
            case = self.parse_candidate(raw)
            if case and self.allowed_case(u, team, case) and case['workspace'] != current.get('workspace_id') and not self.is_opposite_role(current.get('our_role'), case['data'].get('our_role')):
                d = case['data']
                keys.add((d['workspace_id'], d['report_id'], d['risk_id'], d['revision']))
        return len(keys)

    async def recall(self, u, current):
        team = self.memory.member(u, current['team_id'])
        resolved_role = self.resolve_role(
            u, current.get('workspace_id'), current.get('document_version'),
            current.get('perspective'), current.get('our_role'),
        )
        current_ctx = {**current, 'our_role': resolved_role}
        query_parts = [
            DISPOSITION_HEADER,
            current_ctx.get('risk_id') or '',
            current_ctx.get('risk_name') or '',
            current_ctx.get('topic') or '',
            (current_ctx.get('clause_text') or '')[:200],
        ]
        query = ' '.join(p.strip() for p in query_parts if p and p.strip())[:2048]
        cache_key = fingerprint([u['id'], team['id'], current_ctx, self.memory.binding(u)[0]])
        cached = self.cache.get(cache_key)
        raw_items = json.loads(encoded(cached[1])) if cached and cached[0] > time.time() else []
        exhausted = bool(cached and cached[0] > time.time() and cached[2])
        hydrated = {}
        query_offset = 0
        # Search has no offset: at most three calls, 100 distinct candidates.
        for limit in (20, 50, 100):
            if self.usable_count(u, team, current_ctx, raw_items) >= 3 or exhausted:
                break
            data = await self.memory.remote(u, team, '/v3/atomic/search', {'query': query, 'limit': limit})
            records = data.get('items', [])[:limit]
            exhausted = len(records) < limit or limit == 100
            by_id = {x.get('id'): x for x in raw_items if x.get('id')}
            by_id.update({x['id']: x for x in records if x.get('id')})
            raw_items = list(by_id.values())[:100]
            missing = {x['id'] for x in raw_items if not x.get('source_message_ids')} - hydrated.keys()
            # A shared budget across all expansions: at most ten query pages.
            while missing and query_offset < 1000:
                page = await self.memory.remote(u, team, '/v3/atomic/query', {'limit': 100, 'offset': query_offset})
                entries = page.get('items', [])[:100]
                hydrated.update({x['id']: x for x in entries if x.get('id') and x.get('source_message_ids')})
                missing -= hydrated.keys()
                query_offset += len(entries)
                if not entries or query_offset >= page.get('total', query_offset):
                    query_offset = 1000
            raw_items = [hydrated.get(x.get('id'), x) for x in raw_items]
        if len(self.cache) > 128:
            self.cache.clear()
        self.cache[cache_key] = (time.time() + 60, json.loads(encoded(raw_items)), exhausted)
        # Membership, source ownership, deletion, source revision, and transaction role exclusion are checked locally.
        self.memory.member(u, team['id'])
        scored = []
        seen = set()
        unavailable_sources = 0
        for raw in raw_items:
            c = self.parse_candidate(raw)
            if not c:
                unavailable_sources += 1
                continue
            if not self.allowed_case(u, team, c):
                continue
            d = c['data']
            self.store.execute("UPDATE contract_memory_deliveries SET l1_id=? WHERE event_id=? AND backend='native-v3'", (c['id'], d['event_id']))
            if c['workspace'] == current_ctx.get('workspace_id'):
                continue
            if self.is_opposite_role(current_ctx.get('our_role') or current_ctx.get('perspective'), d.get('our_role') or d.get('perspective')):
                continue
            dedup_key = (d.get('report_id'), d.get('risk_id'), int(d.get('revision') or c.get('version') or 1))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            item = self.evaluate_case(current_ctx, c)
            scored.append((self.rank_key(current_ctx, c, item), item))
        if not scored:
            return {'items': [], 'schema_version': 2, 'unavailable_sources': unavailable_sources, 'notice': '本次有界检索未找到可用处置案例；普通对话或来源不能精确关联的记忆不可用作处置案例，不代表全库无有效案例'}
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return {'items': [item for _, item in scored[:3]], 'schema_version': 2, 'unavailable_sources': unavailable_sources}

    def migration_preview(self, u):
        rows = self.store.all('SELECT f.*,a.workspace_id FROM risk_feedback f JOIN artifacts a ON a.id=f.artifact_id JOIN workspaces w ON w.id=a.workspace_id WHERE f.user_id=? AND w.user_id=? AND w.deleted_at IS NULL ORDER BY f.created', (u['id'], u['id']))
        result = []
        for row in rows:
            reason = None
            try:
                a = self.store.one('SELECT * FROM artifacts WHERE id=?', (row['artifact_id'],))
                latest = self.store.one('SELECT MAX(revision) AS n FROM risk_feedback WHERE artifact_id=? AND risk_id=?', (a['id'], row['risk_id']))['n']
                if row['source_hash'] != a['source_hash']:
                    raise ValueError('反馈来源版本不一致')
                if row['revision'] != latest or row['decision'] in {'待处理', '撤回'}:
                    raise ValueError('已替代或撤回')
                report = json.loads((self.store.user_root(u['id']) / 'published' / a['id'] / 'report.json').read_text())
                context = self.current(u, a, report, row['risk_id'])
                content = self.format_disposition_message({**context, 'schema_version': 1, 'event_id': 'feedback_' + fingerprint([a['id'], row['risk_id'], row['revision']]), 'decision': row['decision'], 'note': row['note'], 'revision': row['revision'], 'created_at': datetime.datetime.fromtimestamp(row['created'], datetime.timezone.utc).isoformat()})
                if message_length(content) > 8192:
                    raise ValueError('完整事件超过原生正文上限')
                self.memory.binding(u)
                w = self.store.one('SELECT document_id FROM workspaces WHERE id=?', (a['workspace_id'],))
                doc = self.store.one('SELECT source_hash FROM documents WHERE id=? AND removed_at IS NULL', (w['document_id'],))
                if not doc or doc['source_hash'] != a['source_hash']:
                    raise ValueError('合同版本已变化')
                if report.get('execution_config', {}).get('model', {}).get('providerID') != PROVIDER:
                    raise ValueError('原报告未启用合同记忆')
                if not self.store.one('SELECT 1 FROM tdai_workspaces WHERE workspace_id=? AND user_id=?', (a['workspace_id'], u['id'])):
                    raise ValueError('Task 映射缺失')
            except (ValueError, OSError, HTTPException, KeyError):
                reason = '来源、版本、权限、长度或原处置状态不满足重建条件'
            eid = 'feedback_' + fingerprint([row['artifact_id'], row['risk_id'], row['revision']])
            delivery = self.store.one("SELECT status FROM contract_memory_deliveries WHERE event_id=? AND backend='native-v3'", (eid,))
            if delivery:
                reason = '原生管道已有投递记录：' + delivery['status']
            result.append({'target_backend': 'native-v3', 'event_id': eid, 'artifact_id': row['artifact_id'], 'risk_id': row['risk_id'], 'revision': row['revision'], 'decision': row['decision'], 'workspace_id': row['workspace_id'], 'eligible': reason is None, 'reason': reason, 'core_validation_pending': reason is None})
        return {'dry_run': True, 'schema_version': 2, 'items': result, 'writes': 0}

    def migrate(self, u, items):
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise HTTPException(422, '迁移选择无效')
        preview = self.migration_preview(u)['items']
        allowed = {(r['artifact_id'], r['risk_id'], r['revision']) for r in preview if r['eligible']}
        queued = []
        batch = 'migration-' + str(time.time_ns())
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for x in items:
                if not isinstance(x, dict) or set(x) != {'artifact_id', 'risk_id', 'revision'} or (x['artifact_id'], x['risk_id'], x['revision']) not in allowed:
                    raise HTTPException(409, '迁移来源已变化，请重新预检')
                a = dict(db.execute('SELECT * FROM artifacts WHERE id=?', (x['artifact_id'],)).fetchone())
                f = dict(db.execute('SELECT * FROM risk_feedback WHERE artifact_id=? AND risk_id=? ORDER BY revision DESC LIMIT 1', (a['id'], x['risk_id'])).fetchone())
                if f['revision'] != x['revision']:
                    raise HTTPException(409, '处置版本已变化')
                report = json.loads((self.store.user_root(u['id']) / 'published' / a['id'] / 'report.json').read_text())
                state = self.enqueue(db, u, a, report, x['risk_id'], f['decision'], f['note'], f['revision'], f['created'], batch=batch)
                if state != 'pending':
                    continue
                queued.append(fingerprint([a['id'], x['risk_id'], f['revision']]))
        return {'batch': batch, 'target_backend': 'native-v3', 'queued': len(queued), 'event_ids': ['feedback_' + i for i in queued]}

    def runtime_thread(self, token):
        t = self.store.one('SELECT t.* FROM threads t JOIN workspaces w ON w.id=t.workspace_id JOIN users u ON u.id=w.user_id WHERE t.save_token=? AND t.deleted_at IS NULL AND t.archived_at IS NULL AND w.deleted_at IS NULL AND u.active=1', (digest(token),))
        if not t:
            raise HTTPException(401, '会话读取凭据无效')
        w = self.store.one('SELECT * FROM workspaces WHERE id=?', (t['workspace_id'],))
        u = self.store.one('SELECT * FROM users WHERE id=?', (w['user_id'],))
        self.memory.member(u, w['team_id'])
        p = binding_directory(self.store, u['id']) / (t['session_id'] + '.json')
        binding = json.loads(p.read_text()) if p.is_file() else {}
        if not binding.get('enabled') or binding.get('session_id') != t['session_id']:
            raise HTTPException(403, '本轮未启用合同记忆')
        return u, w, t
