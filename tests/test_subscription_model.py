import json
from pathlib import Path
from types import SimpleNamespace
import threading
import unittest
import subprocess
from unittest.mock import patch

import httpx

from contract_web.subscription_model import completion, make_server, SubscriptionError, stream_chunks


class SubscriptionModelTests(unittest.TestCase):
    def setUp(self):
        self.config = {'subscription_models': ['gpt-6.1-sol'], 'codex_binary': '/fake/codex',
                       'bridge_token': 'local-private-token-'+'x'*40}
        self.body = {'model': 'gpt-6.1-sol', 'messages': [{'role': 'user', 'content': '请检查当前合同'}]}

    def fake(self, answer, *, extra=None, finished=True, code=0):
        def run(cmd, **kw):
            self.cmd, self.kw = cmd, kw
            Path(cmd[cmd.index('-o')+1]).write_text(json.dumps(answer))
            events = [{'type': 'item.completed', 'item': {'type': 'agent_message', 'text': json.dumps(answer)}}]
            if extra:
                events.append(extra)
            if finished:
                events.append({'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 5}})
            return SimpleNamespace(returncode=code, stdout='\n'.join(json.dumps(e) for e in events))
        return run

    def test_text_uses_subscription_and_no_operator_context(self):
        response = completion(self.body, self.config, run=self.fake({'content': '需要先读取原文', 'tool_calls': []}))
        self.assertEqual(response['choices'][0]['finish_reason'], 'stop')
        self.assertEqual(response['usage']['total_tokens'], 15)
        self.assertIn('forced_login_method="chatgpt"', self.cmd)
        self.assertIn('--ignore-user-config', self.cmd)
        self.assertIn('--ignore-rules', self.cmd)
        self.assertIn('--ephemeral', self.cmd)
        self.assertIn('shell_tool', self.cmd)
        self.assertNotIn('OPENAI_API_KEY', self.kw['env'])
        self.assertNotIn('DEEPSEEK_API_KEY', self.kw['env'])
        self.assertFalse(Path(self.cmd[self.cmd.index('--cd')+1]).exists())

    def test_tool_reply_roundtrip_preserves_evidence_and_is_not_executed(self):
        body = {**self.body, 'tools': [{'type': 'function', 'function': {'name': 'read', 'parameters': {'type': 'object'}}}]}
        response = completion(body, self.config, run=self.fake({'content': None, 'tool_calls': [{'name': 'read', 'arguments': '{"filePath":"document.json"}'}]}))
        call = response['choices'][0]['message']['tool_calls'][0]
        self.assertEqual(call['function']['name'], 'read')
        self.assertEqual(response['choices'][0]['finish_reason'], 'tool_calls')
        next_body = {**body, 'messages': [*body['messages'], response['choices'][0]['message'],
            {'role': 'tool', 'tool_call_id': call['id'], 'content': '版本 R2，第6条【段落 002】：迟延费0.05%'}]}
        answer = completion(next_body, self.config, run=self.fake({'content': 'R2第6条为0.05%【段落 002】', 'tool_calls': []}))
        self.assertIn('版本 R2', self.kw['input'])
        self.assertIn('0.05%', answer['choices'][0]['message']['content'])

    def test_disallows_tools_outside_opencode_request(self):
        with self.assertRaises(SubscriptionError):
            completion(self.body, self.config, run=self.fake({'content': None, 'tool_calls': [{'name': 'bash', 'arguments': '{}'}]}))

    def test_rejects_codex_native_tool_execution(self):
        with self.assertRaises(SubscriptionError):
            completion(self.body, self.config, run=self.fake({'content': 'x', 'tool_calls': []}, extra={'type': 'item.completed', 'item': {'type': 'command_execution'}}))

    def test_rejects_failed_or_incomplete_turns(self):
        for kwargs in ({'code': 1}, {'finished': False}, {'extra': {'type': 'turn.failed'}}):
            with self.subTest(kwargs=kwargs), self.assertRaises(SubscriptionError):
                completion(self.body, self.config, run=self.fake({'content': 'x', 'tool_calls': []}, **kwargs))

    def test_only_exact_optional_subsystem_notice_is_nonfatal(self):
        notice = ('Code Mode is unavailable because code-mode host is disabled. '
                  'Code mode will fail closed; enable `features.code_mode_host` '
                  'and install `codex-code-mode-host`.')
        r = completion(self.body, self.config, run=self.fake({'content': 'x', 'tool_calls': []},
            extra={'type': 'item.completed', 'item': {'type': 'error', 'message': notice}}))
        self.assertEqual(r['choices'][0]['message']['content'], 'x')
        with self.assertRaises(SubscriptionError):
            completion(self.body, self.config, run=self.fake({'content': 'x', 'tool_calls': []},
                extra={'type': 'item.completed', 'item': {'type': 'error', 'message': 'Authentication failed'}}))

    def test_rejects_unknown_model_without_running_anything(self):
        def run(*a, **k):
            raise AssertionError('Must fail before inference')
        with self.assertRaises(SubscriptionError):
            completion({**self.body, 'model': 'deepseek-flash'}, self.config, run=run)

    def test_timeout_does_not_fallback_or_return_success(self):
        def run(*a, **k):
            raise subprocess.TimeoutExpired('codex', 240)
        with self.assertRaisesRegex(SubscriptionError, '超时'):
            completion(self.body, self.config, run=run)

    def test_deepseek_passthrough_uses_only_upstream_credential(self):
        captured = {}
        class UpstreamResponse:
            is_error = False
            status_code = 200
            headers = {'Content-Type': 'text/event-stream'}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def iter_bytes(self): yield b'data: {"deepseek":true}\n\ndata: [DONE]\n\n'
        class UpstreamClient:
            def __init__(self, *a, **k): pass
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def stream(self, method, url, **kwargs):
                captured.update(method=method, url=url, **kwargs)
                return UpstreamResponse()
        cfg = {**self.config, 'passthrough_models': ['deepseek-flash'],
               'passthrough_url': 'https://api.deepseek.com/chat/completions', 'passthrough_key': 'fake-api-key'}
        def infer(*args): raise AssertionError('Explicit DeepSeek must not invoke subscription')
        server = make_server(cfg, port=0, infer=infer)
        t = threading.Thread(target=server.serve_forever, daemon=True);t.start()
        try:
            with httpx.Client(base_url='http://127.0.0.1:'+str(server.server_port), trust_env=False) as client:
                with patch('contract_web.subscription_model.httpx.Client', UpstreamClient):
                    r = client.post('/v1/chat/completions', headers={'Authorization': 'Bearer '+cfg['bridge_token'], 'x-user-id': 'private-user'}, json={**self.body, 'model': 'deepseek-flash', 'stream': True})
                self.assertEqual(r.status_code, 200)
                self.assertIn('[DONE]', r.text)
                self.assertEqual(captured['headers'], {'Authorization': 'Bearer fake-api-key'})
                self.assertEqual(captured['json']['model'], 'deepseek-flash')
        finally:
            server.shutdown();server.server_close();t.join()

    def test_rejects_nontext_inputs_before_inference(self):
        with self.assertRaises(SubscriptionError):
            completion({**self.body, 'messages': [{'role': 'user', 'content': [{'type': 'image_url', 'image_url': 'secret'}]}]}, self.config)

    def test_honors_tool_choice_and_parallel_setting(self):
        tools = [{'type': 'function', 'function': {'name': 'read'}}, {'type': 'function', 'function': {'name': 'write'}}]
        cases = [('none', [{'name': 'read', 'arguments': '{}'}]), ('required', []),
                 ({'type': 'function', 'function': {'name': 'read'}}, [{'name': 'write', 'arguments': '{}'}])]
        for choice, calls in cases:
            with self.subTest(choice=choice), self.assertRaises(SubscriptionError):
                completion({**self.body, 'tools': tools, 'tool_choice': choice}, self.config, run=self.fake({'content': 'x', 'tool_calls': calls}))
        with self.assertRaises(SubscriptionError):
            completion({**self.body, 'tools': tools, 'parallel_tool_calls': False}, self.config,
                run=self.fake({'content': None, 'tool_calls': [{'name': 'read', 'arguments': '{}'}]*2}))

    def test_malformed_arguments_and_empty_answer_fail(self):
        for content, calls in [('', []), (None, [{'name': 'read', 'arguments': '[]'}]), (None, [{'name': 'read', 'arguments': '{broken'}])]:
            with self.assertRaises(SubscriptionError):
                completion({**self.body, 'tools': [{'type': 'function', 'function': {'name': 'read'}}]}, self.config, run=self.fake({'content': content, 'tool_calls': calls}))

    def test_sse_tool_call_fields_match_openai_protocol(self):
        response = completion({**self.body, 'tools': [{'type': 'function', 'function': {'name': 'read'}}]}, self.config,
            run=self.fake({'content': None, 'tool_calls': [{'name': 'read', 'arguments': '{}'}]}))
        chunks = list(stream_chunks(response))
        self.assertEqual(chunks[1]['choices'][0]['delta']['tool_calls'][0]['index'], 0)
        self.assertEqual(chunks[2]['choices'][0]['finish_reason'], 'tool_calls')
        self.assertEqual(chunks[3]['choices'], [])

    def test_local_server_authentication_stream_and_unknown_models(self):
        invocations = []
        def infer(body, cfg):
            invocations.append(body)
            return completion(body, cfg, run=self.fake({'content': '已收到', 'tool_calls': []}))
        server = make_server(self.config, port=0, infer=infer)
        thread = threading.Thread(target=server.serve_forever, daemon=True);thread.start()
        try:
            with httpx.Client(base_url='http://127.0.0.1:'+str(server.server_port), trust_env=False) as client:
                self.assertEqual(client.post('/v1/chat/completions', json=self.body).status_code, 401)
                self.assertFalse(invocations)
                self.assertFalse(client.get('/health').json()['inference_verified'])
                headers = {'Authorization': 'Bearer '+self.config['bridge_token']}
                r = client.post('/v1/chat/completions', headers=headers, json={**self.body, 'stream': True})
                self.assertEqual(r.status_code, 200)
                self.assertIn('data: [DONE]', r.text)
                self.assertEqual(client.post('/v1/chat/completions', headers=headers, json={**self.body, 'model': 'unknown'}).status_code, 400)
                self.assertEqual(len(invocations), 1)
        finally:
            server.shutdown();server.server_close();thread.join()


if __name__ == '__main__':
    unittest.main()
