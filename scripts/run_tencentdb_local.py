#!/usr/bin/env python3
"""Provision/reuse the local experiment, then serve OpenHarvey on loopback."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', type=Path, default=Path.home()/'.local/share/openharvey/tencentdb-experiment')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--memory-control-key-file', type=Path, help='仅控制端读取的合同记忆管理凭据')
    parser.add_argument('--contract-memory', action='store_true', help='启用带确认流程的合同记忆')
    parser.add_argument('--opencode-bin', type=Path, default=Path.home()/'CodeDir/TencentDB-Agent-Memory/deploy/local-deployment/state/opencode/node_modules/.bin/opencode')
    parser.add_argument('--admin-key-file', type=Path, default=Path.home()/'CodeDir/TencentDB-Agent-Memory/deploy/global-images/.admin-key')
    parser.add_argument('--core-url', default='http://127.0.0.1:8420')
    parser.add_argument('--proxy-url', default='http://127.0.0.1:8096/opencode/default/v1')
    args = parser.parse_args()
    if not args.opencode_bin.is_file():
        raise SystemExit('请用 --opencode-bin 指定隔离 OpenCode 1.16.2 可执行文件')
    os.umask(0o077)
    origin = f'http://127.0.0.1:{args.port}'
    os.environ.update(CW_DATA_DIR=str(args.data.resolve()), CW_SANDBOX_BACKEND='local', CW_LOCAL_DEV_USER='openharvey-local',
                      CW_SECURE_COOKIE='0', CW_PUBLIC_ORIGIN=origin,
                      PATH=str(args.opencode_bin.parent)+os.pathsep+os.environ.get('PATH',''))
    os.environ['CW_TDAI_ADMIN_KEY_FILE'] = str(args.admin_key_file.resolve())
    if args.contract_memory:
        control=args.memory_control_key_file or args.admin_key_file.parent/'control.key'
        if not control.is_file():raise SystemExit('缺少合同组件控制凭据，请先启动独立 contract-memory 组件')
        os.environ['CW_TDAI_CONTROL_KEY_FILE']=str(control.resolve())
    from contract_web.store import Store
    from contract_web.settings import Settings
    from contract_web.model_settings import Models
    from contract_web.tencentdb_memory import TencentDBMemory
    from contract_web.runtime_manager import RuntimeManager
    store = Store(args.data)
    u = store.one("SELECT * FROM users WHERE username='openharvey-local'")
    created = u is None
    if not u:
        password = secrets.token_urlsafe(24)
        uid = store.add_user('openharvey-local', password)
        store.execute("UPDATE users SET role='admin' WHERE id=?", (uid,))
        u = store.one('SELECT * FROM users WHERE id=?', (uid,))
        path = store.root/'login.json'
        path.write_text(json.dumps({'username':'openharvey-local','password':password}))
        path.chmod(0o600)
    settings = Settings(store, ROOT/'runtime/skills')
    from contract_web.risk_settings import RiskSettings
    RiskSettings(settings, ROOT/"runtime/library")
    from contract_web.accounts import Accounts
    Accounts(store, settings)  # Run the platform-admin migration before bootstrapping this new local admin.
    if created:
        store.execute("UPDATE users SET role='admin' WHERE id=?", (u['id'],))
    u = store.one('SELECT * FROM users WHERE id=?', (u['id'],))
    if not u['active'] or u['role'] != 'admin':
        raise SystemExit('本地实验账号不可用；请使用新的独立数据目录')
    models = Models(settings)
    adapter = TencentDBMemory(store, models)
    async def prepare():
        if not store.one('SELECT 1 FROM tdai_users WHERE user_id=?', (u['id'],)):
            result = await adapter.connect(u, admin_key=args.admin_key_file.read_text().strip(),
                core_url=args.core_url, proxy_url=args.proxy_url)
            store.execute('UPDATE users SET model=? WHERE id=?', (result['model'], u['id']))
        row = store.one('SELECT * FROM tdai_users WHERE user_id=?', (u['id'],))
        provider = store.one("SELECT secret FROM providers WHERE org_id=? AND id='tencentdb-memory'", (models.scope(u),))
        login = {'username':'openharvey-local','user_key':models.decrypt(provider['secret']),
                 'team_id':row['team_id'],'agent_id':row['agent_id']}
        path=store.root/'memory-login.json';path.write_text(json.dumps(login,indent=2));path.chmod(0o600)
        if args.contract_memory:
            current=store.one("SELECT * FROM providers WHERE org_id=? AND id='tencentdb-memory'",(models.scope(u),))
            options=json.loads(current.get('extra_body') or '{}')
            if options.get('thinking')!={'type':'disabled'}:
                result=models.save(u,{'id':'tencentdb-memory','label':'合同记忆 / DeepSeek','base_url':current['base_url'],'protocol':'openai','revision':current['revision'],'extra_body':{**options,'thinking':{'type':'disabled'}},'models':[{**m,'label':m['label'].replace('TencentDB Memory','合同记忆')} for m in json.loads(current['models'])]})
                store.execute('UPDATE model_versions SET validated=1 WHERE org_id=? AND revision=?',(models.scope(u),result['revision']))
            from contract_web.contract_memory import ContractMemory
            await ContractMemory(store,models,adapter).upgrade(u)
        await RuntimeManager(settings,models).ensure(u)
    asyncio.run(prepare())
    print(f'OpenHarvey 本机实验：{origin}/spaces', flush=True)
    print('专用账号：openharvey-local；本机浏览器自动登录。记忆登录凭据位于数据目录 memory-login.json。', flush=True)
    import uvicorn
    uvicorn.run('contract_web.app:create_app', factory=True, host='127.0.0.1', port=args.port, timeout_graceful_shutdown=3)


if __name__ == '__main__':
    main()
