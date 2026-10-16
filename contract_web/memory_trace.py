"""Opt-in local OTLP adapter. No model calls, business persistence, or retries.

Core uses its existing OTel SDK; this small adapter covers the Python application
and subscription bridge without introducing a second telemetry runtime.
"""
import base64
import contextvars
import hashlib
import json
import logging
import os
import queue
import re
import secrets
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)
_current = contextvars.ContextVar('memory_trace', default=None)
_FIELDS = {'run_id', 'attempt_id', 'test_case_id', 'request_id', 'pipeline_task_id', 'retry_count',
           'instanceId', 'teamId', 'userId', 'agentId', 'taskId', 'sessionId', 'app_user_id',
           'event_id', 'logical_call_id', 'trace_id', 'parent_span_id', 'expected_result_ref'}
_SECRET = re.compile(r'authorization|api.?key|password|secret|credential|access.?token|refresh.?token|bridge_token', re.I)


def sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def safe(value):
    if isinstance(value, dict):
        return {k: '[REDACTED]' if _SECRET.search(k) else safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe(v) for v in value]
    if isinstance(value, str):
        return re.sub(r'\bsk-[A-Za-z0-9_-]{12,}', '[REDACTED]', re.sub(r'Bearer\s+[^\s"\\]+', 'Bearer [REDACTED]', value, flags=re.I))
    return value


class LocalTrace:
    def __init__(self, config, credentials, *, send=None):
        self.config = config
        host = credentials['host'].rstrip('/')
        url = urlparse(host)
        if url.scheme not in ('http', 'https') or url.hostname not in ('localhost', '127.0.0.1', 'host.docker.internal') or url.username or url.password:
            raise ValueError('Tracing requires an explicit local Langfuse host')
        self.url = host + '/api/public/otel/v1/traces'
        self.auth = 'Basic ' + base64.b64encode((credentials['public_key'] + ':' + credentials['secret_key']).encode()).decode()
        self.full = config.get('include_content') is True and config.get('synthetic_data') is True
        self.pending = queue.Queue(maxsize=128)
        self.sent = self.failed = self.dropped = 0
        self.last_error = None
        self._send = send
        self.thread = threading.Thread(target=self._export, daemon=True, name='local-langfuse-export')
        self.thread.start()

    def selected(self, scope):
        if scope.get('app_user_id') in self.config.get('app_user_ids', []):
            return True
        return any(all(scope.get(k) == v for k, v in s.items()) for s in self.config.get('scopes', []) if s)

    def context(self, scope, incoming=None):
        if not self.selected(scope):
            return None
        incoming = incoming or {}
        # Peer metadata never overrides server-bound identity or run metadata.
        return {**{k: v for k, v in incoming.items() if k in _FIELDS and isinstance(v, (str, int))},
                **{k: v for k, v in self.config.items() if k in _FIELDS}, **scope}

    def content(self, value):
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        if not self.full or len(raw.encode()) > 524288:
            return {'capture': 'hash_only', 'sha256': sha(value), 'bytes': len(raw.encode()), 'truncated': len(raw.encode()) > 524288}
        return safe(value)

    def emit(self, name, ctx, *, data=None, input=None, output=None, usage=None, model=None, start_ns=None, end_ns=None, error=False, span_id=None):
        if not ctx:
            return None
        try:
            ctx = {**{k: v for k, v in self.config.items() if k in _FIELDS}, **ctx}
            trace_id = ctx.get('trace_id') or secrets.token_hex(16)
            span_id = span_id or secrets.token_hex(8)
            metadata = safe({**ctx, **(data or {}), 'capture_policy': 'full_synthetic_redacted' if self.full else 'hash_only',
                             'versions': self.config.get('versions', {}), 'runtime_version': os.getenv('OH_RUNTIME_REVISION', 'unknown'),
                             'usage_owner': 'subscription_bridge', 'cost_status': 'unknown'})
            attrs = {'langfuse.trace.name': name, 'langfuse.environment': 'native-test-20261015',
                     'langfuse.trace.metadata': json.dumps(metadata, ensure_ascii=False),
                     'langfuse.observation.metadata': json.dumps(metadata, ensure_ascii=False),
                     'langfuse.observation.type': 'generation' if usage is not None else 'span'}
            for key, source in [('user.id', 'userId'), ('session.id', 'sessionId')]:
                if ctx.get(source): attrs[key] = ctx[source]
            if input is not None: attrs['langfuse.observation.input'] = json.dumps(self.content(input), ensure_ascii=False)
            if output is not None: attrs['langfuse.observation.output'] = json.dumps(self.content(output), ensure_ascii=False)
            if model: attrs['langfuse.observation.model.name'] = model
            if usage is not None:
                attrs['langfuse.observation.usage_details'] = json.dumps({k: v for k, v in usage.items() if isinstance(v, (int, float)) and not isinstance(v, bool)})
            if error: attrs['langfuse.observation.level'] = 'ERROR'
            stamp = time.time_ns()
            span = {'traceId': trace_id, 'spanId': span_id, 'name': name, 'kind': 1,
                    'startTimeUnixNano': str(start_ns or stamp), 'endTimeUnixNano': str(end_ns or stamp),
                    'attributes': [{'key': k, 'value': {'stringValue': str(v)}} for k, v in attrs.items()]}
            if ctx.get('parent_span_id'): span['parentSpanId'] = ctx['parent_span_id']
            self.pending.put_nowait(span)
            return {'trace_id': trace_id, 'span_id': span_id}
        except queue.Full:
            self.dropped += 1
            self.last_error = 'QUEUE_FULL'
            log.warning('memory_trace.export_incomplete code=QUEUE_FULL')
        except Exception:
            self.failed += 1
            self.last_error = 'SERIALIZE_FAILED'
            log.warning('memory_trace.export_incomplete code=SERIALIZE_FAILED')

    def _export(self):
        with httpx.Client(timeout=2, trust_env=False, follow_redirects=False) as client:
            while True:
                span = self.pending.get()
                try:
                    payload = {'resourceSpans': [{'resource': {'attributes': []}, 'scopeSpans': [{'scope': {'name': 'openharvey.local-trace', 'version': '1'}, 'spans': [span]}]}]}
                    if self._send:
                        self._send(payload)
                    else:
                        response = client.post(self.url, json=payload, headers={'Authorization': self.auth})
                        response.raise_for_status()
                        if response.json().get('partialSuccess', {}).get('rejectedSpans', 0):
                            raise ValueError('Partial export')
                    self.sent += 1
                except Exception:
                    self.failed += 1
                    self.last_error = 'EXPORT_FAILED'
                    log.warning('memory_trace.export_incomplete code=EXPORT_FAILED trace_id=%s span_id=%s', span['traceId'], span['spanId'])
                finally:
                    self.pending.task_done()

    def flush(self, timeout=3):
        deadline = time.monotonic() + min(max(timeout, 0), 3)
        while self.pending.unfinished_tasks and time.monotonic() < deadline:
            time.sleep(.01)
        return self.status()

    def status(self):
        return {'sent': self.sent, 'failed': self.failed, 'dropped': self.dropped, 'queued': self.pending.unfinished_tasks, 'last_error': self.last_error}


_client = None
_loaded = False


def client():
    global _client, _loaded
    if not _loaded:
        _loaded = True
        try:
            file = os.getenv('MEMORY_TRACE_CONFIG_FILE')
            if file:
                config = json.loads(Path(file).read_text())
                if config.get('enabled') is True:
                    credentials = json.loads(Path(os.environ['LANGFUSE_CREDENTIALS_FILE']).read_text())
                    _client = LocalTrace(config, credentials)
        except Exception:
            log.warning('memory_trace.disabled code=CONFIG_FAILED')
    return _client


def context(scope, incoming=None):
    c = client()
    return c.context(scope, incoming) if c else None


_UNSET = object()


def emit(name, ctx=_UNSET, **kwargs):
    c = client()
    selected = _current.get() if ctx is _UNSET else ctx
    return c.emit(name, selected, **kwargs) if c else None


def headers():
    ctx = _current.get()
    return {'x-memory-trace-context': json.dumps({k: v for k, v in ctx.items() if k in _FIELDS}, separators=(',', ':'))} if ctx else {}


def incoming(raw):
    try:
        data = json.loads(raw or '{}') if len(raw or '') <= 8192 else {}
        result = {k: v for k, v in data.items() if k in _FIELDS and isinstance(v, (str, int))}
        for field, length in [('trace_id', 32), ('parent_span_id', 16)]:
            if field in result and not re.fullmatch('[0-9a-f]{'+str(length)+'}', str(result[field])): result.pop(field)
        return result
    except (ValueError, AttributeError):
        return {}
