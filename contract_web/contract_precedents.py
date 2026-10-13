"""Saved risk dispositions: durable delivery and permission-checked precedent reads."""
import asyncio
import hashlib
import json
import re
from pathlib import Path
import time
from fastapi import HTTPException
from .settings import encoded
from .store import digest
from .tencentdb_memory import PROVIDER, binding_directory


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


class ContractPrecedents:
    def __init__(self, memory, risks=None):
        self.memory, self.store = memory, memory.store
        self.risks=risks
        self.worker = None
        self.cache = {}
        self.lock = asyncio.Lock()
        with self.store.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS contract_memory_outbox (
              id TEXT PRIMARY KEY,user_id TEXT,team_id TEXT,workspace_id TEXT,artifact_id TEXT,risk_id TEXT,
              data TEXT,status TEXT,attempts INTEGER DEFAULT 0,next_attempt REAL DEFAULT 0,error TEXT,created REAL);
            ''')

    def document_refs(self, u, report):
        result = []
        for ref in report.get('evidence', []):
            doc = self.store.one('SELECT * FROM documents WHERE id=? AND user_id=? AND removed_at IS NULL', (ref.get('document_id'), u['id']))
            if not doc or doc['source_hash'] != ref.get('source_hash'):
                raise HTTPException(409, '历史处置引用的文档版本已变化')
            p = self.store.user_root(u['id'])/'sources'/doc['id']/'document.json'
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
        primary=self.store.one('SELECT source_hash FROM documents WHERE id=? AND user_id=? AND removed_at IS NULL',(w['document_id'],u['id']))
        if not primary or primary['source_hash']!=row['source_hash']:raise HTTPException(409,'报告对应的主合同版本已变化，请重新审查')
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
                live=self.risks.choose(u,scheme.get('id'))
                rule=next((x for x in live['rules'] if x['id']==rid),{})
                scheme=live
            except (ValueError,HTTPException):
                rule={};scheme={'revision':None}
        refs = self.document_refs(u, f)
        # Labels such as 甲方/乙方 alone do not establish transaction roles.
        perspective = report.get('perspective')
        role = perspective if perspective and perspective not in {'甲方', '乙方'} else None
        if role is None and perspective in {'甲方','乙方'}:
            path=self.store.user_root(u['id'])/'sources'/w['document_id']/'document.json'
            if path.is_file():
                source=json.loads(path.read_text())
                if source.get('source_hash')==row['source_hash']:
                    pattern=re.compile(re.escape(perspective)+r'[（(](采购方|供货方|供应方|买方|卖方|委托方|受托方|服务方)[）)]')
                    for segment in source.get('segments',[]):
                        match=pattern.search(segment['text'])
                        if match:role=match[1];break
        return {'workspace_id': w['id'], 'team_id': w['team_id'], 'risk_id': rid,
                'contract_title':w['title'], 'contract_filename':(self.store.one('SELECT filename FROM documents WHERE id=?',(w['document_id'],)) or {}).get('filename'),
                'risk_name': f.get('risk_name', rule.get('name', rid)),
                'topic': f.get('category', rule.get('category', rule.get('name', rid))),
                'risk_definition': rule, 'risk_definition_hash': fingerprint(rule or {'id': rid, 'name': f.get('risk_name', rid)}),
                'risk_scheme_version': scheme.get('revision', scheme.get('version')), 'perspective': perspective,
                'our_role': role, 'document_version': row['source_hash'], 'document_refs': refs,
                'clause_text': '\n'.join(r['quote'] for r in refs), 'verdict': f.get('verdict'), 'report_id': row['id']}

    def enqueue(self, db, u, row, report, rid, decision, note, revision, created):
        w = self.store.one('SELECT * FROM workspaces WHERE id=? AND user_id=?', (row['workspace_id'], u['id']))
        if not w or not w.get('team_id'):
            return 'not_connected'
        # Only reports actually run through the managed Memory provider produce events.
        if report.get('execution_config', {}).get('model', {}).get('providerID') != PROVIDER:
            return 'not_enabled'
        current = self.current(u, row, report, rid)
        _, _, uid = self.memory.binding(u)
        thread = self.store.one('SELECT * FROM threads WHERE id=?', (row['thread_id'],))
        task = self.store.one('SELECT task_id FROM tdai_workspaces WHERE workspace_id=? AND user_id=?', (w['id'], u['id']))
        event_id = 'feedback_'+fingerprint([row['id'], rid, revision])
        payload = {**current, 'event_id': event_id, 'actor_user_id': uid, 'session_id': thread['session_id'],
                   'task_id': task['task_id'] if task else None, 'decision': decision, 'note': note,
                   'revision': revision, 'created': __import__('datetime').datetime.fromtimestamp(created, __import__('datetime').timezone.utc).isoformat()}
        db.execute('INSERT OR IGNORE INTO contract_memory_outbox(id,user_id,team_id,workspace_id,artifact_id,risk_id,data,status,created) VALUES(?,?,?,?,?,?,?,?,?)',
                   (event_id, u['id'], w['team_id'], w['id'], row['id'], rid, encoded(payload), 'pending', created))
        return 'pending'

    def status(self, aid, rid, uid):
        r = self.store.one('SELECT id AS event_id,status,attempts FROM contract_memory_outbox WHERE artifact_id=? AND risk_id=? AND user_id=? ORDER BY created DESC,rowid DESC LIMIT 1', (aid, rid, uid))
        return r or {'status': 'not_enabled'}

    async def flush(self):
        async with self.lock:
            rows = self.store.all("SELECT * FROM contract_memory_outbox WHERE status IN ('pending','failed') AND next_attempt<=? AND attempts<5 ORDER BY created LIMIT 10", (time.time(),))
            for r in rows:
                try:
                    u = self.store.one('SELECT * FROM users WHERE id=? AND active=1', (r['user_id'],))
                    if not u:
                        raise HTTPException(403, '账号已停用')
                    team = self.memory.member(u, r['team_id'])
                    w = self.store.one('SELECT * FROM workspaces WHERE id=? AND user_id=? AND deleted_at IS NULL', (r['workspace_id'], u['id']))
                    if not w or w['team_id'] != team['id']:
                        raise HTTPException(403, '原合同已移除')
                    payload = json.loads(r['data'])
                    if not payload['task_id']:
                        raise HTTPException(409, '合同 Task 映射缺失，等待管理员修复')
                    result = await self.memory.remote(u, team, 'review-events', {'task_id': payload['task_id'], 'event': payload})
                    if not result.get('saved') or not result.get('case_id'):
                        raise HTTPException(503, '记忆组件未确认事件落盘')
                    self.store.execute("UPDATE contract_memory_outbox SET status='synced',error=NULL WHERE id=?", (r['id'],))
                except Exception as e:
                    attempts = r['attempts']+1
                    self.store.execute("UPDATE contract_memory_outbox SET status='failed',attempts=?,next_attempt=?,error=? WHERE id=?", (attempts, time.time()+min(300, 2**attempts), str(getattr(e, 'detail', '记忆同步失败')), r['id']))

    async def start(self):
        async def loop():
            while True:
                await self.flush()
                await asyncio.sleep(3)
        self.worker = asyncio.create_task(loop())

    async def close(self):
        if self.worker:
            self.worker.cancel()
            try:await self.worker
            except asyncio.CancelledError:pass

    def allowed_case(self, u, team, c):
        d = c['data']
        w = self.store.one('SELECT * FROM workspaces WHERE id=? AND user_id=? AND team_id=? AND deleted_at IS NULL', (c['workspace'], u['id'], team['id']))
        if not w:return False
        # Validate the original immutable contract version and latest saved feedback.
        a = self.store.one('SELECT a.* FROM artifacts a JOIN workspaces w ON w.id=a.workspace_id WHERE a.id=? AND w.user_id=?', (d['report_id'], u['id']))
        if not a or a['workspace_id'] != w['id'] or a['source_hash'] != d['document_version']:return False
        doc = self.store.one('SELECT source_hash FROM documents WHERE id=? AND removed_at IS NULL', (w['document_id'],))
        if not doc or doc['source_hash'] != d['document_version']:return False
        for ref in d.get('document_refs',[]):
            source=self.store.one('SELECT source_hash FROM documents WHERE id=? AND user_id=? AND workspace_id=? AND removed_at IS NULL',(ref.get('document_id'),u['id'],w['id']))
            if not source or source['source_hash']!=ref.get('version'):return False
        f = self.store.one('SELECT decision,note,revision FROM risk_feedback WHERE artifact_id=? AND risk_id=? AND user_id=? ORDER BY revision DESC LIMIT 1', (d['report_id'], d['risk_id'], u['id']))
        return bool(f and f['revision'] == d['revision'] and f['decision'] == d['decision'] and f['note'] == d['note'] and f['decision'] != '待处理')

    async def recall(self, u, current):
        team = self.memory.member(u, current['team_id'])
        await self.memory.sync_resources(u,team)
        data = await self.memory.remote(u, team, 'case-list')
        eligible = [c for c in data.get('items', []) if self.allowed_case(u, team, c)]
        if not eligible:return {'items': [], 'schema_version': 2}
        cache_key=fingerprint([u['id'],team['id'],current,[(c['id'],c['version']) for c in eligible]])
        cached=self.cache.get(cache_key)
        result=json.loads(encoded(cached[1])) if cached and cached[0]>time.time() else await self.memory.remote(u, team, 'precedents', {'current': current, 'allowed_case_ids': [c['id'] for c in eligible]})
        if len(self.cache)>128:self.cache.clear()
        self.cache[cache_key]=(time.time()+60,json.loads(encoded(result)))
        # Membership, source ownership, deletion and source revision are checked again after inference.
        self.memory.member(u, team['id'])
        await self.memory.sync_resources(u,team)
        live = await self.memory.remote(u, team, 'case-list')
        allowed = {(c['id'], c['version']) for c in live.get('items', []) if self.allowed_case(u, team, c)}
        result['items'] = [{**x, 'source_url': '/agent?artifact='+x['report_id']+'&risk='+__import__('urllib.parse',fromlist=['quote']).quote(x['risk_id'])+'#'+x['workspace_id'], 'source_label': '查看历史合同处理意见'}
                           for x in result.get('items', []) if (x['case_id'], x['version']) in allowed][:3]
        return result

    def migration_preview(self, u):
        rows=self.store.all('SELECT f.*,a.workspace_id FROM risk_feedback f JOIN artifacts a ON a.id=f.artifact_id JOIN workspaces w ON w.id=a.workspace_id WHERE f.user_id=? AND w.user_id=? AND w.deleted_at IS NULL ORDER BY f.created',(u['id'],u['id']))
        result=[]
        for row in rows:
            reason=None
            try:
                a=self.store.one('SELECT * FROM artifacts WHERE id=?',(row['artifact_id'],))
                latest=self.store.one('SELECT MAX(revision) AS n FROM risk_feedback WHERE artifact_id=? AND risk_id=?',(a['id'],row['risk_id']))['n']
                if row['source_hash']!=a['source_hash']:raise ValueError('反馈来源版本不一致')
                if row['revision']!=latest or row['decision']=='待处理':raise ValueError('已替代或撤回')
                report=json.loads((self.store.user_root(u['id'])/'published'/a['id']/'report.json').read_text())
                current=self.current(u,a,report,row['risk_id'])
                self.memory.binding(u)
                w=self.store.one('SELECT document_id FROM workspaces WHERE id=?',(a['workspace_id'],))
                doc=self.store.one('SELECT source_hash FROM documents WHERE id=? AND removed_at IS NULL',(w['document_id'],))
                if not doc or doc['source_hash']!=a['source_hash']:raise ValueError('合同版本已变化')
                if report.get('execution_config',{}).get('model',{}).get('providerID')!=PROVIDER:raise ValueError('原报告未启用合同记忆')
                if not self.store.one('SELECT 1 FROM tdai_workspaces WHERE workspace_id=? AND user_id=?',(a['workspace_id'],u['id'])):raise ValueError('Task 映射缺失')
            except (ValueError,OSError,HTTPException,KeyError):reason='来源、版本、权限或原处置状态不满足重建条件'
            result.append({'artifact_id':row['artifact_id'],'risk_id':row['risk_id'],'revision':row['revision'],'decision':row['decision'],'workspace_id':row['workspace_id'],'eligible':reason is None,'reason':reason,'core_validation_pending':reason is None})
        return {'dry_run':True,'schema_version':2,'items':result,'writes':0}

    def migrate(self,u,items):
        if not isinstance(items,list) or not 1<=len(items)<=100:raise HTTPException(422,'迁移选择无效')
        preview=self.migration_preview(u)['items']
        allowed={(r['artifact_id'],r['risk_id'],r['revision']) for r in preview if r['eligible']}
        queued=[]
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            for x in items:
                if not isinstance(x,dict) or set(x)!={'artifact_id','risk_id','revision'} or (x['artifact_id'],x['risk_id'],x['revision']) not in allowed:raise HTTPException(409,'迁移来源已变化，请重新预检')
                a=dict(db.execute('SELECT * FROM artifacts WHERE id=?',(x['artifact_id'],)).fetchone())
                f=dict(db.execute('SELECT * FROM risk_feedback WHERE artifact_id=? AND risk_id=? ORDER BY revision DESC LIMIT 1',(a['id'],x['risk_id'])).fetchone())
                if f['revision']!=x['revision']:raise HTTPException(409,'处置版本已变化')
                report=json.loads((self.store.user_root(u['id'])/'published'/a['id']/'report.json').read_text())
                self.enqueue(db,u,a,report,x['risk_id'],f['decision'],f['note'],f['revision'],f['created'])
                queued.append(fingerprint([a['id'],x['risk_id'],f['revision']]))
        return {'queued':len(queued),'event_ids':['feedback_'+i for i in queued]}

    def runtime_thread(self, token):
        t = self.store.one('SELECT t.* FROM threads t JOIN workspaces w ON w.id=t.workspace_id JOIN users u ON u.id=w.user_id WHERE t.save_token=? AND t.deleted_at IS NULL AND t.archived_at IS NULL AND w.deleted_at IS NULL AND u.active=1', (digest(token),))
        if not t:raise HTTPException(401, '会话读取凭据无效')
        w = self.store.one('SELECT * FROM workspaces WHERE id=?', (t['workspace_id'],))
        u = self.store.one('SELECT * FROM users WHERE id=?', (w['user_id'],))
        self.memory.member(u, w['team_id'])
        p = binding_directory(self.store, u['id'])/(t['session_id']+'.json')
        binding = json.loads(p.read_text()) if p.is_file() else {}
        if not binding.get('enabled') or binding.get('session_id') != t['session_id']:
            raise HTTPException(403, '本轮未启用合同记忆')
        return u, w, t
