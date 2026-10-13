"""Local TencentDB Memory adapter. The independent service owns all memories."""
import asyncio
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException

from .settings import encoded

PROVIDER = 'tencentdb-memory'
ENDPOINTS = ('atomic/search', 'atomic/query', 'conversation/search', 'conversation/query', 'scenario/ls', 'scenario/read')


def binding_directory(store, uid):
    return store.user_root(uid) / 'opencode' / 'tdai-bindings'


def bridge_permissions(memory):
    if not memory or not memory.get('enabled'):
        return []
    base = memory['bridge_url']
    return [{'permission': 'bash', 'pattern': f'curl {flags} -X POST {quote}{base}/{endpoint}{quote} *', 'action': 'allow'}
            for flags in ('-sfk', '-sf', '-s', '-sS', '-sSk') for endpoint in ENDPOINTS for quote in ('', "'", '"')]


class TencentDBMemory:
    def __init__(self, store, models):
        self.store, self.models = store, models
        self.locks = {}
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tdai_users (
                  user_id TEXT PRIMARY KEY REFERENCES users(id), service_id TEXT NOT NULL,
                  core_url TEXT NOT NULL, proxy_url TEXT NOT NULL, gateway_secret TEXT,
                  tdai_user_id TEXT NOT NULL, team_id TEXT NOT NULL, agent_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tdai_workspaces (
                  workspace_id TEXT PRIMARY KEY REFERENCES workspaces(id) ON DELETE CASCADE,
                  user_id TEXT NOT NULL REFERENCES users(id), task_id TEXT NOT NULL, created REAL NOT NULL);
            ''')

    async def call(self, binding, path, body, key):
        headers = {'x-tdai-service-id': binding['service_id'], 'x-tdai-user-key': key,
                   'Authorization': 'Bearer ' + (self.models.decrypt(binding.get('gateway_secret')) or 'local')}
        try:
            async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
                response = await client.post(binding['core_url'].rstrip('/') + path, headers=headers, json=body)
            result = response.json()
            if response.is_error or result.get('code', 0) != 0:
                raise HTTPException(503, 'TencentDB 记忆身份或任务不可用，请检查独立记忆服务的账号与绑定')
            return result.get('data', result)
        except (httpx.HTTPError, ValueError):
            raise HTTPException(503, 'TencentDB 记忆服务暂时不可用，请检查独立服务连接') from None

    def write_binding(self, u, t, value):
        sid = t['session_id']
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,180}', sid):
            raise HTTPException(422, '记忆会话标识无效')
        folder = binding_directory(self.store, u['id'])
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
        path = folder / (sid + '.json')
        tmp = path.with_suffix('.tmp')
        tmp.write_text(encoded({'session_id': sid, **value}))
        tmp.chmod(0o600)
        tmp.replace(path)

    async def prepare(self, u, t, rt, model):
        off = {'enabled': False}
        if model['providerID'] != PROVIDER:
            self.write_binding(u, t, off)
            return off
        self.write_binding(u, t, off)
        if rt.config.get('e2b') or not rt.config.get('local', True):
            raise HTTPException(422, 'TencentDB Memory 当前接入仅支持本机运行，请选择其他模型或本机合同空间')
        if getattr(self, 'contracts', None):
            value = await self.contracts.prepare(u, t, rt, model)
            if value is not None: return value
        binding = self.store.one('SELECT * FROM tdai_users WHERE user_id=?', (u['id'],))
        provider = self.store.one('SELECT * FROM providers WHERE org_id=? AND id=? AND enabled=1', (self.models.scope(u), PROVIDER))
        if not binding or not provider or not provider.get('secret'):
            raise HTTPException(422, '此账号尚未配置 TencentDB Memory，请由管理员完成专用身份绑定')
        if provider['base_url'].rstrip('/') != binding['proxy_url'].rstrip('/'):
            raise HTTPException(422, 'TencentDB Memory 模型地址与身份绑定不一致，请重新配置')
        key = self.models.decrypt(provider['secret'])
        verified = await self.call(binding, '/v3/meta/auth/verify', {'user_key': key}, key)
        if verified.get('valid') is not True or (verified.get('user') or {}).get('user_id') != binding['tdai_user_id']:
            raise HTTPException(503, 'TencentDB Memory 用户凭据已失效，请重新配置')
        agent = await self.call(binding, '/v3/meta/agent/get', {'agent_id': binding['agent_id']}, key)
        if agent.get('team_id') != binding['team_id'] or agent.get('owner_user_id') != binding['tdai_user_id'] or agent.get('status') == 'archived':
            raise HTTPException(503, 'TencentDB Memory Agent 绑定已失效')
        async with self.locks.setdefault(t['workspace_id'], asyncio.Lock()):
            task = self.store.one('SELECT * FROM tdai_workspaces WHERE workspace_id=? AND user_id=?', (t['workspace_id'], u['id']))
            if not task:
                created = await self.call(binding, '/v3/meta/task/create', {
                    'team_id': binding['team_id'], 'creator_user_id': binding['tdai_user_id'],
                    'title': 'OpenHarvey 合同空间 ' + t['workspace_id'],
                    'metadata_json': encoded({'openharvey_workspace_id': t['workspace_id']}),
                    'linked_agents': [{'agent_id': binding['agent_id']}]}, key)
                task_id = created.get('task_id')
                if not task_id:
                    raise HTTPException(503, 'TencentDB Memory 未确认任务创建结果')
                self.store.execute('INSERT INTO tdai_workspaces VALUES(?,?,?,?)', (t['workspace_id'], u['id'], task_id, time.time()))
            else:
                task_id = task['task_id']
            current = await self.call(binding, '/v3/meta/task/get', {'task_id': task_id}, key)
            if current.get('team_id') != binding['team_id'] or current.get('creator_user_id') != binding['tdai_user_id'] or current.get('status') in {'archived', 'deleted'}:
                raise HTTPException(503, 'TencentDB Memory 合同任务绑定已失效')
        # Health check prevents a queued task from silently continuing without the proxy.
        parsed = urlsplit(binding['proxy_url'])
        bridge_url = f'{parsed.scheme}://{parsed.netloc}/memory-bridge/v3'
        try:
            async with httpx.AsyncClient(timeout=3, trust_env=False) as client:
                response = await client.get(f'{parsed.scheme}://{parsed.netloc}/health')
                response.raise_for_status()
        except httpx.HTTPError:
            raise HTTPException(503, 'TencentDB Memory Proxy 暂时不可用，请检查服务或主动选择其他模型') from None
        value = {'enabled': True, 'service_id': binding['service_id'], 'team_id': binding['team_id'],
                 'agent_id': binding['agent_id'], 'task_id': task_id, 'bridge_url': bridge_url}
        self.write_binding(u, t, value)
        return value

    @staticmethod
    def prompt(memory):
        if not memory.get('enabled'):
            return '\n本轮未启用外部记忆；不要调用记忆桥接或应用历史中的记忆工具结果。本轮用户指令与当前合同材料仍有效。'
        if memory.get('contract'):
            return ('\n本轮使用合同记忆。自动整理的经验和工作偏好先形成待确认建议，须由用户在建议卡片或“经验与偏好”页面确认后才能长期生效；'
                    '不要用对话中的口头承诺替代实际保存回执。原始记录仅用于恢复当前合同依据，未确认的偏好不能当成已生效工作约定。'
                    '正式个人经验和团队已发布经验可以只读召回，须核对当前交易角色、条件、例外和原文；都不代表合同事项已批准。'
                    '团队共享须经管理员审核，不开放原合同。用户增删改通过业务面板处理，不调用记忆写入接口。'
                    '遇到已识别风险，读取 context.json 的 historical_dispositions，用指定只读脚本查询同团队本人历史处置；核对差异再给本次建议。聊天中的接受/修改意见未在风险卡片保存前，不是历史处置案例；引导用户保存处理意见。'
                    '本轮不得调用旧个人 memory 工具；不能改变当前合同 Task；原文引用、风险方案与成果保存继续按现有规则执行。')
        return ('\n本轮通过独立 TencentDB Memory 服务使用记忆。记忆由后台异步提炼，口头确认不代表已落盘；'
                '只有实际查询到记录或在独立面板确认后，才能说明记忆已保存。历史记忆只作工作经验参考，'
                '须核对适用条件；不改变当前合同事实、风险方案、权限或审批状态。合同结论仍需当前原文依据。'
                '按需使用 Proxy 提供的只读记忆桥接说明；不要调用已移除的个人 memory 工具，'
                '不要输出旧 [[memory:ID:revision]] 标记。当前合同 Task 不可由模型切换。')

    async def connect(self, u, *, admin_key, core_url, proxy_url, service_id='default', username='openharvey-local', gateway_key='local'):
        for address in (core_url, proxy_url):
            url = urlsplit(address)
            if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError('请提供不含凭据的完整 Memory 服务地址')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', service_id):
            raise ValueError('Memory 实例标识无效')
        binding = {'core_url': core_url.rstrip('/'), 'proxy_url': proxy_url.rstrip('/'), 'service_id': service_id,
                   'gateway_secret': self.models.encrypt(gateway_key)}
        prior = self.store.one('SELECT * FROM tdai_users WHERE user_id=?', (u['id'],))
        if prior:
            if any(prior[k] != binding[k] for k in ('core_url', 'proxy_url', 'service_id')):
                raise ValueError('账号已有其他 Memory 服务绑定；请使用独立数据目录建立新实验')
            provider = self.store.one('SELECT * FROM providers WHERE org_id=? AND id=?', (self.models.scope(u), PROVIDER))
            if not provider or not provider.get('secret'):
                raise ValueError('现有 Memory 凭据缺失，无法安全复用绑定')
            key = self.models.decrypt(provider['secret'])
            binding.update({k: prior[k] for k in ('tdai_user_id', 'team_id', 'agent_id')})
        else:
            person = await self.call(binding, '/v3/meta/user/create', {'username': username}, admin_key)
            key = person['default_user_key']
            team = await self.call(binding, '/v3/meta/team/create', {'name': 'OpenHarvey', 'owner_user_id': person['user_id']}, key)
            agent = await self.call(binding, '/v3/meta/agent/create', {'team_id': team['team_id'], 'owner_user_id': person['user_id'],
                                        'name': '合同助手', 'visibility': 'private', 'description': 'OpenHarvey 单合同 Agent 的独立记忆'}, key)
            binding.update(tdai_user_id=person['user_id'], team_id=team['team_id'], agent_id=agent['agent_id'])
            self.store.execute('INSERT INTO tdai_users VALUES(?,?,?,?,?,?,?,?)',
                (u['id'], service_id, binding['core_url'], binding['proxy_url'], binding['gateway_secret'], person['user_id'], team['team_id'], agent['agent_id']))
        old = self.store.one('SELECT revision FROM providers WHERE org_id=? AND id=?', (self.models.scope(u), PROVIDER))
        result = self.models.save(u, {'id': PROVIDER, 'label': 'TencentDB Memory / DeepSeek', 'base_url': proxy_url.rstrip('/'),
                'protocol': 'openai', 'key': key, 'revision': old['revision'] if old else 0,
                'models': [{'id': 'deepseek-flash', 'label': 'DeepSeek V4.1 Flash（TencentDB Memory）', 'context': 1000000, 'output': 8192}]})
        # Provisioning uses explicit known model settings; native calls are verified separately.
        self.store.execute('UPDATE model_versions SET validated=1 WHERE org_id=? AND revision=?', (self.models.scope(u), result['revision']))
        return {'provider': PROVIDER, 'model': PROVIDER + '/deepseek-flash', **{k: binding[k] for k in ('tdai_user_id','team_id','agent_id')}}


def register_removed_memory(app):
    async def removed():
        raise HTTPException(410, '原有个人记忆功能已移除，请使用独立 TencentDB Memory 服务')
    app.add_api_route('/api/memories', removed, methods=['GET','POST'])
    app.add_api_route('/api/memories/{iid}', removed, methods=['GET','PATCH','DELETE'])
    app.add_api_route('/internal/memory', removed, methods=['POST'])
