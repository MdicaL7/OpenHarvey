#!/usr/bin/env python3
"""Prepare, serve, activate or undo the local business subscription bridge."""
import argparse
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import urllib.request
from urllib.parse import urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def private_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.parent.chmod(0o700)
    path.write_text(text)
    path.chmod(0o600)


def docker(args):
    result = subprocess.run(['docker', *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Docker 操作失败，请检查本机合同 Proxy')
    return result.stdout


def prepare(args):
    binary = shutil.which('codex')
    if not binary:
        raise RuntimeError('请先安装官方 Codex CLI')
    result = subprocess.run([binary, 'login', 'status'], capture_output=True, text=True)
    if result.returncode or 'chatgpt' not in (result.stdout+result.stderr).lower():
        raise RuntimeError('请先运行 codex login，选择 ChatGPT 订阅登录')
    state = args.state.resolve()
    settings_path, backup = state/'bridge.json', state/'proxy-backup.json'
    mount = json.loads(docker(['inspect', args.proxy_container]))[0]
    paths = [m['Source'] for m in mount['Mounts'] if m['Destination'] == '/data/config.yaml']
    if len(paths) != 1:
        raise RuntimeError('无法确认合同 Proxy 配置挂载，未修改配置')
    path = Path(paths[0])
    # Docker Desktop reports macOS bind paths with its VM /host_mnt prefix.
    if not path.exists() and str(path).startswith('/host_mnt/'):
        path = Path(str(path)[len('/host_mnt'):])
    original = path.read_text()
    proxy = yaml.safe_load(original)
    if backup.exists():
        saved = json.loads(backup.read_text())
        if saved['proxy_path'] != str(path) or saved['proxy_container'] != args.proxy_container:
            raise RuntimeError('此状态目录已绑定其他 Proxy，请使用新的状态目录')
        previous = yaml.safe_load(saved['yaml'])
    else:
        previous = proxy
    if previous.get('upstream', {}).get('agents', {}).get('opencode'):
        raise RuntimeError('Proxy 已有 OpenCode 单独路由，请先统一路由配置')
    upstream = previous.get('upstream', {})
    target = urlsplit(upstream.get('url', ''))
    if target.scheme != 'https' or target.hostname != 'api.deepseek.com' or not upstream.get('apiKey'):
        raise RuntimeError('现有上游不是已确认的 DeepSeek 配置，未修改')
    # No default-Core extraction settings are touched.
    cfg = json.loads(settings_path.read_text()) if settings_path.exists() else {'bridge_token': secrets.token_urlsafe(48)}
    passthrough = upstream['url'].rstrip('/')
    if not passthrough.endswith('/chat/completions'):
        passthrough += '/chat/completions'
    cfg.update(subscription_models=[args.model], passthrough_models=['deepseek-flash'],
               passthrough_url=passthrough, passthrough_key=upstream['apiKey'],
               codex_binary=binary, timeout_seconds=240, concurrency=2,
               host=args.host, port=args.port)
    if not backup.exists():
        private_write(backup, json.dumps({'proxy_path': str(path), 'proxy_container': args.proxy_container, 'yaml': original}))
    private_write(settings_path, json.dumps(cfg, indent=2))
    print('本机订阅桥接已准备；凭据仅保存在私有状态目录。未调用模型。')


def activate(args):
    from contract_web.store import Store
    from contract_web.settings import Settings
    from contract_web.model_settings import Models
    from contract_web.tencentdb_memory import PROVIDER
    cfg = json.loads((args.state/'bridge.json').read_text())
    with urllib.request.urlopen(f'http://127.0.0.1:{cfg["port"]}/health', timeout=3) as response:
        if json.load(response).get('provider') != 'codex-subscription-bridge':
            raise RuntimeError('此端口不是订阅桥接服务')
    saved = json.loads((args.state/'proxy-backup.json').read_text())
    store = Store(args.data)
    u = store.one('SELECT * FROM users WHERE username=? AND active=1', (args.username,))
    if not u:
        raise RuntimeError('指定本机业务账号不存在')
    models = Models(Settings(store, ROOT/'runtime/skills'))
    provider = store.one('SELECT * FROM providers WHERE org_id=? AND id=? AND enabled=1', (models.scope(u), PROVIDER))
    binding = store.one('SELECT * FROM memory_identities WHERE user_id=?', (u['id'],))
    if not provider or not binding:
        raise RuntimeError('此账号未接入受管理的合同记忆，未切换业务模型')
    # Reject instance overrides that would bypass this bridge. Read-only check.
    from contract_web.tencentdb_memory import TencentDBMemory
    import asyncio
    admin_file = args.memory_control_key_file
    if not admin_file or not admin_file.is_file():
        raise RuntimeError('请指定 --memory-control-key-file 核对实例上游设置')
    memory = TencentDBMemory(store, models)
    bound = json.loads(binding['binding'])
    result = asyncio.run(memory.call(bound, '/v3/internal/meta/instance-upstream/list', {}, admin_file.read_text().strip()))
    if any(r.get('type') == 'conversation' and r.get('mode') != 'official'
           and r.get('agent_source') in {'default', 'opencode'} for r in result.get('items', [])):
        raise RuntimeError('实例已有自定义业务上游，会覆盖桥接；未修改配置')
    registry_backup = args.state/'registry-backup.json'
    if not registry_backup.exists():
        private_write(registry_backup, json.dumps({'data': str(args.data.resolve()), 'user': u['id'],
            'model': u['model'], 'provider': {k: provider[k] for k in ('label', 'models', 'extra_body')}}))
    else:
        b = json.loads(registry_backup.read_text())
        if b['data'] != str(args.data.resolve()) or b['user'] != u['id']:
            raise RuntimeError('此桥接仅绑定一个实验账号，请使用独立状态目录')
    path = Path(saved['proxy_path'])
    proxy = yaml.safe_load(path.read_text())
    proxy['upstream']['url'] = f'http://host.docker.internal:{cfg["port"]}/v1/chat/completions'
    proxy['upstream']['apiKey'] = cfg['bridge_token']
    # Preserve inode for the existing Docker bind mount.
    path.write_text(yaml.safe_dump(proxy, allow_unicode=True, sort_keys=False));path.chmod(0o600)
    docker(['restart', saved['proxy_container']])
    choices = json.loads(provider['models'])
    existing = {m['id'] for m in choices}
    for model in cfg['subscription_models']:
        if model not in existing:
            choices.insert(0, {'id': model, 'label': 'ChatGPT 订阅 · '+model+'（合同记忆）',
                               'context': 128000, 'output': 8192, 'native': {'tool_call': True}})
    new = models.save(u, {'id': PROVIDER, 'label': '合同记忆 / ChatGPT 与 DeepSeek',
        'base_url': provider['base_url'], 'protocol': 'openai', 'revision': provider['revision'],
        'models': choices, 'extra_body': json.loads(provider['extra_body'])})
    store.execute('UPDATE model_versions SET validated=1 WHERE org_id=? AND revision=?', (models.scope(u), new['revision']))
    store.execute('UPDATE users SET model=? WHERE id=?', (PROVIDER+'/'+cfg['subscription_models'][0], u['id']))
    print('业务模型已配置为 ChatGPT 订阅，DeepSeek 可手动选择。既有会话的显式模型选择保持原值。')


def rollback(args):
    saved = json.loads((args.state/'proxy-backup.json').read_text())
    b = json.loads((args.state/'registry-backup.json').read_text())
    if str(args.data.resolve()) != b['data']:
        raise RuntimeError('恢复数据目录不匹配')
    from contract_web.store import Store
    from contract_web.settings import Settings
    from contract_web.model_settings import Models
    from contract_web.tencentdb_memory import PROVIDER
    store = Store(args.data);u = store.one('SELECT * FROM users WHERE id=?', (b['user'],))
    models = Models(Settings(store, ROOT/'runtime/skills'))
    old = store.one('SELECT * FROM providers WHERE org_id=? AND id=?', (models.scope(u), PROVIDER))
    # The backup is single-owner and is never fed to Agent sessions.
    new = models.save(u, {'id': PROVIDER, 'label': b['provider']['label'], 'base_url': old['base_url'],
        'protocol': 'openai', 'revision': old['revision'], 'models': json.loads(b['provider']['models']),
        'extra_body': json.loads(b['provider']['extra_body'])})
    store.execute('UPDATE model_versions SET validated=1 WHERE org_id=? AND revision=?', (models.scope(u), new['revision']))
    store.execute('UPDATE users SET model=? WHERE id=?', (b['model'], u['id']))
    path = Path(saved['proxy_path']);path.write_text(saved['yaml']);path.chmod(0o600)
    docker(['restart', saved['proxy_container']])
    print('业务默认模型与 Proxy 已恢复为原配置。合同记忆数据未改动。')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare', 'serve', 'activate', 'rollback'])
    parser.add_argument('--state', type=Path, default=Path.home()/'.local/share/openharvey/chatgpt-business')
    parser.add_argument('--data', type=Path, default=Path.home()/'.local/share/openharvey/contract-memory-lab')
    parser.add_argument('--username', default='openharvey-local')
    parser.add_argument('--model', default='gpt-6.1-sol')
    parser.add_argument('--host', default='0.0.0.0', help='Docker Desktop 访问本机桥接；请求必须携带私有 token')
    parser.add_argument('--port', type=int, default=8767)
    parser.add_argument('--proxy-container', default='tdai-contract-proxy')
    parser.add_argument('--memory-control-key-file', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == 'prepare':
        prepare(args)
    elif args.action == 'activate':
        activate(args)
    elif args.action == 'rollback':
        rollback(args)
    else:
        from contract_web.subscription_model import make_server
        cfg = json.loads((args.state/'bridge.json').read_text())
        server = make_server(cfg, cfg['host'], cfg['port'])
        print(f'业务订阅桥接已启动，端口 {cfg["port"]}。健康检查不代表模型推理已验证。', flush=True)
        server.serve_forever()


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1)
    except Exception:
        # Exceptions from libraries can embed provider credentials or URLs.
        print('操作失败，未确认接入成功；请核对本机账号、Codex 登录、端口和组件配置。', file=sys.stderr)
        raise SystemExit(1)
