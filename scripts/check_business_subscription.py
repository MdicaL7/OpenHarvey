#!/usr/bin/env python3
"""Explicit isolated OpenCode read-tool roundtrip; never uses Memory or fixtures."""
import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time

import httpx


def check(state, binary):
    cfg = json.loads((state/'bridge.json').read_text())
    model = cfg['subscription_models'][0]
    with tempfile.TemporaryDirectory(prefix='openharvey-subscription-smoke-') as tmp:
        root = Path(tmp).resolve();work = root/'work';work.mkdir()
        (work/'marker.txt').write_text('contract-business-ok')
        config = {'$schema': 'https://opencode.ai/config.json', 'share': 'disabled',
            'autoupdate': False, 'snapshot': False, 'plugin': [], 'default_agent': 'business-check',
            'model': 'business-subscription/'+model, 'small_model': 'business-subscription/'+model,
            'agent': {'business-check': {'mode': 'primary',
                'prompt': '仅按用户要求读取文件，然后回答文件内容。没有读取结果前不要猜测。',
                'permission': {'*': 'deny', 'read': 'allow', 'external_directory': {str(work)+'/*': 'allow'}}}},
            'provider': {'business-subscription': {'npm': '@ai-sdk/openai-compatible',
                'options': {'baseURL': f'http://127.0.0.1:{cfg["port"]}/v1', 'apiKey': cfg['bridge_token']},
                'models': {model: {'name': 'Subscription', 'limit': {'context': 128000, 'output': 8192}}}}},
            'enabled_providers': ['business-subscription']}
        path = root/'config.json';path.write_text(json.dumps(config));path.chmod(0o600)
        env = {k: v for k, v in os.environ.items() if not k.startswith(('CW_', 'OPENCODE_', 'OPENAI_', 'DEEPSEEK_', 'E2B_', 'ANTHROPIC_'))}
        for key, folder in [('XDG_CONFIG_HOME', 'config'), ('XDG_DATA_HOME', 'data'),
                            ('XDG_STATE_HOME', 'state'), ('XDG_CACHE_HOME', 'cache'), ('OPENCODE_TEST_HOME', 'home')]:
            env[key] = str(root/folder)
        secret = secrets.token_urlsafe(32)
        env.update(OPENCODE_CONFIG=str(path), OPENCODE_SERVER_PASSWORD=secret, OPENCODE_DISABLE_EXTERNAL_SKILLS='true')
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0));port = sock.getsockname()[1]
        with (root/'service.log').open('wb') as log:
            process = subprocess.Popen([str(binary), 'serve', '--hostname', '127.0.0.1', '--port', str(port)],
                cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            with httpx.Client(base_url=f'http://127.0.0.1:{port}', auth=('opencode', secret),
                             trust_env=False, timeout=15, headers={'x-opencode-directory': str(work)}) as client:
                for _ in range(100):
                    try:
                        if client.get('/global/health').status_code == 200:break
                    except httpx.HTTPError:pass
                    if process.poll() is not None:raise RuntimeError('隔离 OpenCode 启动失败')
                    time.sleep(.2)
                else:raise RuntimeError('隔离 OpenCode 健康检查超时')
                r = client.post('/session', json={});r.raise_for_status();sid = r.json()['id']
                # OpenCode matches ordinary read paths relative to worktree;
                # external_directory is independently and narrowly permitted.
                client.patch('/session/'+sid, json={'permission': [
                    {'permission': '*', 'pattern': '*', 'action': 'deny'},
                    {'permission': 'read', 'pattern': '*', 'action': 'allow'},
                    {'permission': 'external_directory', 'pattern': str(work)+'/*', 'action': 'allow'}]}).raise_for_status()
                client.post('/session/'+sid+'/prompt_async', json={
                    'model': {'providerID': 'business-subscription', 'modelID': model},
                    'agent': 'business-check', 'parts': [{'type': 'text', 'text':
                        '请实际调用 read 读取 '+str(work/'marker.txt')+'，然后只回复文件中的内容。'}]}).raise_for_status()
                end = time.monotonic()+240
                while time.monotonic() < end:
                    messages = client.get('/session/'+sid+'/message').json()
                    last = messages[-1] if messages else {};info = last.get('info', {})
                    if info.get('role') == 'assistant' and info.get('time', {}).get('completed') and info.get('finish') != 'tool-calls':
                        if info.get('error'):raise RuntimeError('业务回合失败')
                        tools = [p for m in messages for p in m.get('parts', []) if p.get('type') == 'tool']
                        answer = ''.join(p.get('text', '') for p in last.get('parts', []) if p.get('type') == 'text')
                        passed = any(p.get('tool') == 'read' and p.get('state', {}).get('status') == 'completed' for p in tools) and 'contract-business-ok' in answer
                        result = {'requested_model': model, 'passed': passed, 'memory_used': False,
                                  'tools': [{'name': p.get('tool'), 'status': p.get('state', {}).get('status')} for p in tools], 'answer': answer}
                        print(json.dumps(result, ensure_ascii=False))
                        if not passed:raise RuntimeError('原生工具往返未通过')
                        return result
                    time.sleep(.5)
                raise RuntimeError('原生工具往返超时')
        finally:
            process.terminate()
            try:process.wait(timeout=10)
            except subprocess.TimeoutExpired:process.kill();process.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--state', type=Path, default=Path.home()/'.local/share/openharvey/chatgpt-business')
    parser.add_argument('--opencode-bin', type=Path, default=Path.home()/'CodeDir/TencentDB-Agent-Memory/deploy/local-deployment/state/opencode/node_modules/.bin/opencode')
    args = parser.parse_args()
    if not args.execute:
        print('离线：显式 --execute 才启动隔离 OpenCode，用独立临时文本验证真实 read 工具；不访问合同、记忆或测试包。')
    else:
        check(args.state, args.opencode_bin)
