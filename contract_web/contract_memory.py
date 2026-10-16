from . import memory_trace
"""Business identities and source authorization; Memory owns all memory content."""
import asyncio
import json
import os
import secrets
from pathlib import Path
import httpx
from fastapi import HTTPException, Request, Query
from fastapi.responses import FileResponse
from .settings import encoded, admin
from .tencentdb_memory import PROVIDER

CONTRACT_AGENT_META = {'prompt_mode': 'contract', 'managed_by': 'OpenHarvey'}
STANDARD_ENDPOINTS = {
    'list': '/v3/scenario/ls', 'candidates': '/v3/atomic/query',
    'detail': '/v3/scenario/read', 'sources': '/v3/atomic/query',
}


def resolve_endpoint(action):
    endpoint = STANDARD_ENDPOINTS.get(action, action)
    if endpoint not in {'/v3/' + path for path in (
        'conversation/add', 'atomic/query', 'atomic/search', 'scenario/ls',
        'scenario/read', 'scenario/write', 'core/read')}:
        raise HTTPException(501, '此操作尚未接入标准记忆协议')
    return endpoint


class MemoryTransportError(HTTPException):
    """Sanitized client failure with explicit pre-send evidence."""
    def __init__(self, cause):
        self.transport_kind = type(cause).__name__
        self.safe_to_retry = isinstance(cause, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout))
        detail = ('连接尚未建立或尚未取得连接，请修复服务后安全重试' if self.safe_to_retry
                  else '请求可能已被接收，须核对远端结果；禁止盲目重发')
        super().__init__(503, self.transport_kind + '：' + detail)


class ContractMemory:
    def __init__(self, store, models, tdai):
        self.store, self.models, self.tdai = store, models, tdai
        self.lock = asyncio.Lock()
        with store.connect() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS memory_identities(user_id TEXT PRIMARY KEY,tdai_user_id TEXT NOT NULL,secret TEXT NOT NULL,binding TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS teams(id TEXT PRIMARY KEY,org_id TEXT NOT NULL,name TEXT NOT NULL,owner_id TEXT NOT NULL,tdai_team_id TEXT NOT NULL,agent_id TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS team_members(team_id TEXT NOT NULL,user_id TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN ('admin','member')),active INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(team_id,user_id));
              CREATE TABLE IF NOT EXISTS team_preferences(user_id TEXT PRIMARY KEY,team_id TEXT NOT NULL);
            ''')
            if 'team_id' not in {r[1] for r in db.execute('PRAGMA table_info(workspaces)')}:
                db.execute('ALTER TABLE workspaces ADD COLUMN team_id TEXT REFERENCES teams(id)')

    def binding(self, u):
        i = self.store.one('SELECT * FROM memory_identities WHERE user_id=?', (u['id'],))
        if not i:
            raise HTTPException(422, '此账号尚未连接合同记忆，请联系管理员')
        return json.loads(i['binding']), self.models.decrypt(i['secret']), i['tdai_user_id']

    def member(self, u, tid, role=None):
        t = self.store.one('SELECT t.*,m.role FROM teams t JOIN team_members m ON m.team_id=t.id WHERE t.id=? AND t.org_id=? AND m.user_id=? AND m.active=1 AND EXISTS(SELECT 1 FROM users u WHERE u.id=m.user_id AND u.active=1)', (tid, u['org_id'], u['id']))
        if not t:
            raise HTTPException(403, '没有此团队的访问权限')
        if role and t['role'] != role:
            raise HTTPException(403, '需要团队管理员身份')
        return t

    def teams(self, u):
        return self.store.all('SELECT t.id,t.name,m.role FROM teams t JOIN team_members m ON m.team_id=t.id WHERE t.org_id=? AND m.user_id=? AND m.active=1 ORDER BY t.name', (u['org_id'], u['id']))

    def selected(self, u):
        row = self.store.one('SELECT team_id FROM team_preferences WHERE user_id=?', (u['id'],))
        if row:
            try:
                return self.member(u, row['team_id'])
            except HTTPException:
                pass
        teams = self.teams(u)
        return self.member(u, teams[0]['id']) if teams else None

    async def remote(self, u, t, action, body=None):
        if not self.store.one('SELECT 1 FROM users WHERE id=? AND active=1', (u['id'],)):
            raise HTTPException(403, '账号已停用')
        self.member(u, t['id'])
        binding, key, uid = self.binding(u)
        endpoint = resolve_endpoint(action)
        payload = {**(body or {}), 'team_id': t['tdai_team_id'], 'agent_id': t['agent_id'], 'user_id': uid}
        control_file = os.environ.get('CW_TDAI_CONTROL_KEY_FILE')
        controller = Path(control_file).read_text().strip() if control_file else self.models.decrypt(binding.get('gateway_secret')) or 'local'
        headers = {**memory_trace.headers(), 'Authorization': 'Bearer ' + controller, 'x-tdai-service-id': binding['service_id'], 'x-tdai-user-key': key}
        try:
            async with httpx.AsyncClient(timeout=20, trust_env=False, follow_redirects=False) as client:
                response = await client.post(binding['core_url'].rstrip('/') + endpoint, json=payload, headers=headers)
            result = response.json()
            if response.is_error or result.get('code', 0):
                raise HTTPException(response.status_code if response.is_error else 503, result.get('message', '记忆服务暂时不可用'))
            self.member(self.store.one('SELECT * FROM users WHERE id=? AND active=1', (u['id'],)) or {'id': '', 'org_id': ''}, t['id'])
            return result.get('data', {})
        except httpx.HTTPError as exc:
            raise MemoryTransportError(exc) from exc
        except ValueError as exc:
            raise MemoryTransportError(exc) from exc

    async def identity(self, u, owner):
        if self.store.one('SELECT 1 FROM memory_identities WHERE user_id=?', (u['id'],)):
            return
        b, _, _ = self.binding(owner)
        keyfile = os.environ.get('CW_TDAI_ADMIN_KEY_FILE')
        if not keyfile:
            raise HTTPException(503, '请配置只用于初始化的 Memory 管理凭据文件')
        result = await self.tdai.call(b, '/v3/meta/user/create', {'username': 'oh-' + u['id']}, Path(keyfile).read_text().strip())
        self.store.execute('INSERT INTO memory_identities VALUES(?,?,?,?)', (u['id'], result['user_id'], self.models.encrypt(result['default_user_key']), encoded(b)))
        # Runtime receives only this user's normal credential, never the initialization key.
        result = self.models.save(u, {'id': PROVIDER, 'label': '合同记忆 / DeepSeek', 'base_url': b['proxy_url'], 'protocol': 'openai', 'extra_body': {'thinking': {'type': 'disabled'}}, 'models': [{'id': 'deepseek-flash', 'label': 'DeepSeek V4.1 Flash（合同记忆）', 'context': 1000000, 'output': 8192}], 'key': result['default_user_key'], 'revision': 0})
        self.store.execute('UPDATE model_versions SET validated=1 WHERE org_id=? AND revision=?', (self.models.scope(u), result['revision']))

    async def upgrade(self, u):
        """Explicit migration: preserves existing Task/Conversation IDs and code data."""
        async with self.lock:
            if self.teams(u):
                return self.teams(u)[0]
            old = self.store.one('SELECT * FROM tdai_users WHERE user_id=?', (u['id'],))
            if not old:
                raise HTTPException(422, '请先配置 TencentDB Memory')
            provider = self.store.one('SELECT * FROM providers WHERE org_id=? AND id=?', (self.models.scope(u), PROVIDER))
            key = self.models.decrypt(provider['secret'])
            self.store.execute('INSERT OR IGNORE INTO memory_identities VALUES(?,?,?,?)', (u['id'], old['tdai_user_id'], self.models.encrypt(key), encoded(old)))
            agent = await self.tdai.call(old, '/v3/meta/agent/create', {'team_id': old['team_id'], 'owner_user_id': old['tdai_user_id'], 'name': '合同助手 · contract', 'visibility': 'team', 'metadata_json': encoded(CONTRACT_AGENT_META)}, key)
            for prior in self.store.all('SELECT task_id FROM tdai_workspaces WHERE user_id=?', (u['id'],)):
                await self.tdai.call(old, '/v3/meta/task-agent/link', {'task_id': prior['task_id'], 'agent_id': agent['agent_id'], 'role_in_task': '合同助手'}, key)
            tid = secrets.token_hex(12)
            with self.store.connect() as db:
                db.execute('INSERT INTO teams VALUES(?,?,?,?,?,?)', (tid, u['org_id'], '默认实验团队', u['id'], old['team_id'], agent['agent_id']))
                db.execute('INSERT INTO team_members VALUES(?,?,?,1)', (tid, u['id'], 'admin'))
                db.execute('UPDATE workspaces SET team_id=? WHERE user_id=? AND team_id IS NULL', (tid, u['id']))
                db.execute('INSERT OR REPLACE INTO team_preferences VALUES(?,?)', (u['id'], tid))
            return self.member(u, tid)

    async def sync_status(self, actor, target, active):
        admin(actor)
        if target['org_id'] != actor['org_id']:
            raise HTTPException(403, '不能管理其他企业的用户')
        # Native meta has no user/status route. Account suspension is local;
        # revoking separately held Memory credentials requires Memory administration.
        if not active:
            for thread in self.store.all('SELECT t.* FROM threads t JOIN workspaces w ON w.id=t.workspace_id WHERE w.user_id=?', (target['id'],)):
                self.tdai.write_binding(target, thread, {'enabled': False})
        return {'local_only': True, 'remote_revocation': 'unsupported'}

    async def create_team(self, u, name):
        admin(u)
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise HTTPException(422, '请填写团队名称（最多80字）')
        b, key, uid = self.binding(u)
        team = await self.tdai.call(b, '/v3/meta/team/create', {'name': name.strip(), 'owner_user_id': uid}, key)
        agent = await self.tdai.call(b, '/v3/meta/agent/create', {'team_id': team['team_id'], 'owner_user_id': uid, 'name': '合同助手', 'visibility': 'team', 'metadata_json': encoded(CONTRACT_AGENT_META)}, key)
        tid = secrets.token_hex(12)
        with self.store.connect() as db:
            db.execute('INSERT INTO teams VALUES(?,?,?,?,?,?)', (tid, u['org_id'], name.strip(), u['id'], team['team_id'], agent['agent_id']))
            db.execute('INSERT INTO team_members VALUES(?,?,?,1)', (tid, u['id'], 'admin'))
        return self.member(u, tid)

    async def set_member(self, u, tid, uid, role, active):
        admin(u)
        team = self.store.one('SELECT * FROM teams WHERE id=? AND org_id=?', (tid, u['org_id']))
        target = self.store.one('SELECT * FROM users WHERE id=? AND org_id=? AND active=1', (uid, u['org_id']))
        if not team or not target:
            raise HTTPException(404, '团队或用户不存在')
        if role not in {'admin', 'member'} or not isinstance(active, bool):
            raise HTTPException(422, '成员设置无效')
        if uid == team['owner_id'] and (not active or role != 'admin'):
            raise HTTPException(422, '首版需保留团队创建者的管理员身份')
        owner = self.store.one('SELECT * FROM users WHERE id=? AND active=1', (team['owner_id'],))
        if not owner:
            raise HTTPException(503, '团队维护账号不可用')
        await self.identity(target, owner)
        b, key, _ = self.binding(owner)
        _, _, targetid = self.binding(target)
        # Reconcile idempotently after an uncertain response from either database.
        existing = None
        offset = 0
        while True:
            page = await self.tdai.call(b, '/v3/meta/team-member/list', {'team_id': team['tdai_team_id'], 'limit': 100, 'offset': offset}, key)
            existing = next((m for m in page.get('items', []) if m['user_id'] == targetid), None)
            offset += len(page.get('items', []))
            if existing or offset >= page.get('total', 0) or not page.get('items'):
                break
        already = existing and ((active and existing['status'] == 'active' and existing['role'] == role) or (not active and existing['status'] != 'active'))
        if not already:
            await self.tdai.call(b, '/v3/meta/team-member/' + ('add' if active else 'remove'), {'team_id': team['tdai_team_id'], 'user_id': targetid, **({'role': role} if active else {})}, key)
        self.store.execute('INSERT INTO team_members VALUES(?,?,?,?) ON CONFLICT(team_id,user_id) DO UPDATE SET role=excluded.role,active=excluded.active', (tid, uid, role, int(active)))
        return {'saved': True}

    async def prepare(self, u, t, rt, model):
        w = self.store.one('SELECT * FROM workspaces WHERE id=? AND user_id=?', (t['workspace_id'], u['id']))
        if not w or not w['team_id']:
            return None
        team = self.member(u, w['team_id'])
        b, key, uid = self.binding(u)
        if rt.config.get('e2b') or not rt.config.get('local', True):
            raise HTTPException(422, '合同记忆首版仅支持本机运行')
        self.tdai.write_binding(u, t, {'enabled': False})
        provider = self.store.one('SELECT * FROM providers WHERE org_id=? AND id=? AND enabled=1', (self.models.scope(u), PROVIDER))
        if not provider or provider['base_url'].rstrip('/') != b['proxy_url'].rstrip('/') or self.models.decrypt(provider['secret']) != key:
            raise HTTPException(422, '模型地址或用户凭据与合同记忆绑定不一致')
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                health = await client.get(b['proxy_url'].split('/opencode/')[0] + '/health')
                health.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503, '合同记忆 Proxy 暂时不可用，请检查独立组件或主动选择普通模型') from None
        meta_json = encoded(CONTRACT_AGENT_META)
        async with self.lock:
            if not team.get('agent_id'):
                agent = await self.tdai.call(b, '/v3/meta/agent/create', {
                    'team_id': team['tdai_team_id'], 'owner_user_id': uid,
                    'name': '合同助手', 'visibility': 'team', 'metadata_json': meta_json}, key)
                team['agent_id'] = agent['agent_id']
                self.store.execute('UPDATE teams SET agent_id=? WHERE id=?', (team['agent_id'], team['id']))
            else:
                agent = await self.tdai.call(b, '/v3/meta/agent/get', {'agent_id': team['agent_id']}, key)
                raw_meta = agent.get('metadata_json') if isinstance(agent, dict) else None
                parsed_meta = json.loads(raw_meta) if isinstance(raw_meta, str) and raw_meta else (raw_meta if isinstance(raw_meta, dict) else {})
                if parsed_meta.get('prompt_mode') != 'contract':
                    await self.tdai.call(b, '/v3/meta/agent/update', {'agent_id': team['agent_id'], 'metadata_json': meta_json}, key)
            row = self.store.one('SELECT * FROM tdai_workspaces WHERE workspace_id=? AND user_id=?', (w['id'], u['id']))
            if not row:
                task = await self.tdai.call(b, '/v3/meta/task/create', {
                    'team_id': team['tdai_team_id'], 'creator_user_id': uid,
                    'title': 'OpenHarvey 合同空间 ' + w['id'],
                    'metadata_json': encoded({'openharvey_workspace_id': w['id']}),
                    'linked_agents': [{'agent_id': team['agent_id']}]}, key)
                self.store.execute('INSERT INTO tdai_workspaces VALUES(?,?,?,?)', (w['id'], u['id'], task['task_id'], __import__('time').time()))
                taskid = task['task_id']
            else:
                taskid = row['task_id']
        self.member(u, w['team_id'])
        value = {
            'enabled': True, 'contract': True, 'memory_version': 2,
            'service_id': b['service_id'], 'team_id': team['tdai_team_id'],
            'agent_id': team['agent_id'], 'task_id': taskid,
            'bridge_url': b['proxy_url'].split('/opencode/')[0] + '/memory-bridge/v3',
        }
        trace_ctx = memory_trace.context({'instanceId': b['service_id'], 'teamId': team['tdai_team_id'],
            'userId': uid, 'agentId': team['agent_id'], 'taskId': taskid, 'sessionId': t['session_id'], 'app_user_id': u['id']}, memory_trace._current.get())
        if trace_ctx:
            value['trace_context'] = trace_ctx
        self.tdai.write_binding(u, t, value)
        return value

    @staticmethod
    def view_entry(kind, identity, title, content, raw):
        return {'id': identity, 'level': kind, 'read_only': True,
                'version': raw.get('version'), 'updated': raw.get('updated_at'),
                'data': {'kind': kind, 'title': title, 'content': content or '',
                         'conditions': [], 'exceptions': []}}

    async def atomic_entries(self, u, t, body=None):
        body = dict(body or {})
        limit, offset = body.setdefault('limit', 20), body.setdefault('offset', 0)
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or not 0 <= offset <= 1000000:
            raise HTTPException(422, '分页参数无效')
        result = await self.remote(u, t, '/v3/atomic/query', body)
        items = [self.view_entry('atomic', 'atomic:' + x['id'], x.get('type', 'L1'), x.get('content'), x)
                 for x in result.get('items', [])]
        total = result.get('total')
        more = offset + len(items) < total if isinstance(total, int) else len(items) == limit
        return {'items': items, 'read_only': True, 'total': total, 'limit': limit, 'offset': offset, 'next_offset': offset + len(items) if more and items else None}

    async def list_memories(self, u, t, scope='personal', limit=20, offset=0):
        if scope in {'personal', 'atomic'}:
            return await self.atomic_entries(u, t, {'limit': limit, 'offset': offset})
        if scope == 'legacy':
            return {'items': [], 'notice': '旧版内容未迁移；请使用迁移预检，原投递历史保留。'}
        if scope != 'team':
            raise HTTPException(422, '内容范围无效')
        scenarios = await self.remote(u, t, '/v3/scenario/ls', {})
        core = await self.remote(u, t, '/v3/core/read', {})
        items = [self.view_entry('scenario', 'scenario:' + x['path'], x['path'], x.get('summary'), x)
                 for x in scenarios.get('entries', []) if not x['path'].endswith('/')]
        if core.get('content') is not None:
            items.append(self.view_entry('core', 'core', '团队工作偏好与约定', core['content'], core))
        return {'items': items, 'read_only': True, 'notice': 'L2 场景与 L3 偏好属于团队共享范围；个人确认与团队审批暂不可用。'}

    async def detail(self, u, t, eid):
        if eid == 'core':
            result = await self.remote(u, t, '/v3/core/read', {})
        elif eid.startswith('scenario:'):
            result = await self.remote(u, t, '/v3/scenario/read', {'path': eid[len('scenario:'):]})
        else:
            raise HTTPException(501, '原子记忆来源请通过合同历史案例查询核验')
        return {**result, 'versions': [], 'sources': [{'restricted': True, 'label': '标准场景正文不提供可核验的合同来源关联'}]}

    async def safe_sources(self, u, t, eid):
        return [{'restricted': True, 'label': '来源尚未可靠关联，不可用'}]


def register_contract_memory(app, user, service, root):
    @app.get('/experience')
    async def page():
        return FileResponse(root / 'static/experience.html')

    @app.get('/api/contract-memory/teams')
    async def teams(request: Request):
        u = user(request)
        selected = service.selected(u)
        return {'items': service.teams(u), 'selected': selected['id'] if selected else None, 'enterprise_admin': u['role'] == 'admin'}

    @app.post('/api/contract-memory/teams')
    async def create(request: Request):
        return await service.create_team(user(request), (await request.json()).get('name'))

    @app.post('/api/contract-memory/team-selection')
    async def select(request: Request):
        u = user(request)
        tid = (await request.json()).get('team_id')
        service.member(u, tid)
        service.store.execute('INSERT OR REPLACE INTO team_preferences VALUES(?,?)', (u['id'], tid))
        return {'saved': True}

    @app.get('/api/contract-memory/teams/{tid}/members')
    async def members(tid: str, request: Request):
        u = user(request)
        admin(u)
        if not service.store.one('SELECT 1 FROM teams WHERE id=? AND org_id=?', (tid, u['org_id'])):
            raise HTTPException(404, '团队不存在')
        return {'items': service.store.all('SELECT u.id,u.username,m.role,COALESCE(m.active,0) AS active FROM users u LEFT JOIN team_members m ON m.user_id=u.id AND m.team_id=? WHERE u.org_id=? AND u.active=1', (tid, u['org_id']))}

    @app.put('/api/contract-memory/teams/{tid}/members/{uid}')
    async def member(tid: str, uid: str, request: Request):
        b = await request.json()
        return await service.set_member(user(request), tid, uid, b.get('role'), b.get('active'))

    @app.get('/api/contract-memory/list')
    async def listing(request: Request, team_id: str, scope: str = 'personal', limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000)):
        u = user(request)
        return await service.list_memories(u, service.member(u, team_id), scope, limit, offset)

    @app.get('/api/contract-memory/candidates')
    async def candidates(request: Request, team_id: str, thread_id: str | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=1000000)):
        u = user(request)
        t = service.member(u, team_id)
        b = {'limit': limit, 'offset': offset}
        if thread_id:
            thread = service.store.one('SELECT t.session_id,w.team_id FROM threads t JOIN workspaces w ON w.id=t.workspace_id WHERE t.id=? AND w.user_id=? AND w.deleted_at IS NULL', (thread_id, u['id']))
            if not thread or thread['team_id'] != team_id:
                raise HTTPException(404, '会话不存在')
            b['session_id'] = thread['session_id']
        return await service.atomic_entries(u, t, b)

    @app.get('/api/contract-memory/proposals')
    async def proposals(request: Request, team_id: str):
        u = user(request)
        service.member(u, team_id)
        return {'items': [], 'notice': '本地共享申请与审批尚未实现，暂不可用。'}

    @app.get('/api/contract-memory/detail/{eid:path}')
    async def detail(eid: str, request: Request, team_id: str):
        u = user(request)
        t = service.member(u, team_id)
        return await service.detail(u, t, eid)

    for action in ('create', 'update', 'delete', 'confirm', 'ignore', 'propose', 'review', 'retry'):
        def route(op):
            async def handler(request: Request):
                u = user(request)
                b = await request.json()
                if any(k in b for k in ('user_id', 'agent_id', 'task_id', 'session_id')):
                    raise HTTPException(422, '请求不得覆盖业务身份')
                t = service.member(u, b.get('team_id'), 'admin' if op == 'review' else None)
                raise HTTPException(501, '个人编辑、确认、忽略、共享审批和整理重试尚未接入，暂不可用；未修改记忆')
            return handler
        app.add_api_route('/api/contract-memory/' + action, route(action), methods=['POST'])
