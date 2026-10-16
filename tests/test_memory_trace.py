import copy
import json
import threading
import time
import unittest
from unittest.mock import patch
import httpx
from contract_web import memory_trace as mt
from contract_web.subscription_model import make_server


class MemoryTraceTests(unittest.TestCase):
    def tracer(self, send=None, full=False):
        return mt.LocalTrace({'run_id':'synthetic-run','enabled':True,'include_content':full,'synthetic_data':full,
            'scopes':[{'instanceId':'i','teamId':'t','agentId':'a'}]},
            {'host':'http://127.0.0.1:3000','public_key':'test','secret_key':'test'}, send=send or (lambda payload: None))

    def test_scope_and_summaries_and_secrets(self):
        c=self.tracer()
        self.assertIsNone(c.context({'instanceId':'i','teamId':'other','agentId':'a'}))
        ctx=c.context({'instanceId':'i','teamId':'t','agentId':'a'}, {'run_id':'forged','authorization':'secret'})
        self.assertEqual(ctx['run_id'],'synthetic-run')
        self.assertNotIn('authorization',ctx)
        self.assertEqual(c.content({'content':'private'})['capture'],'hash_only')
        full=self.tracer(full=True)
        self.assertEqual(full.content({'authorization':'Bearer password','x':'sk-abcdefghijklmn'})['authorization'],'[REDACTED]')
        self.assertTrue(full.content('x'*530000)['truncated'])

    def test_local_only(self):
        with self.assertRaises(ValueError):
            mt.LocalTrace({}, {'host':'https://cloud.langfuse.com','public_key':'x','secret_key':'x'})

    def test_failed_export_is_bounded_and_visible(self):
        def fail(payload): raise OSError('synthetic endpoint failure')
        c=self.tracer(send=fail)
        c.emit('synthetic',c.context({'instanceId':'i','teamId':'t','agentId':'a'}),data={'source_message_ids':['one','two']})
        status=c.flush()
        self.assertEqual(status['failed'],1)
        self.assertEqual(status['last_error'],'EXPORT_FAILED')
        self.assertEqual(status['queued'],0)

    def test_bridge_physical_attempts_identical_request_and_no_replay(self):
        sent=[]
        def fail(payload):
            sent.append(payload)
            raise OSError('synthetic exporter unavailable')
        c=self.tracer(send=fail,full=True)
        config={'bridge_token':'x'*40,'subscription_models':['script-model'],'timeout_seconds':2}
        calls=[]
        def infer(body,config):
            calls.append(copy.deepcopy(body))
            return {'id':'script','model':'script-model','choices':[{'message':{'role':'assistant','content':'synthetic output'}}],
                'usage':{'prompt_tokens':11,'completion_tokens':3,'total_tokens':14}}
        server=make_server(config,port=0,infer=infer)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        body={'model':'script-model','messages':[{'role':'user','content':'synthetic input'}],'temperature':0.2,'stream':False}
        url='http://127.0.0.1:'+str(server.server_port)
        try:
            for enabled in (False,True):
                with patch.object(mt,'client',return_value=c if enabled else None):
                    r=httpx.post(url+'/v1/chat/completions',json=body,headers={'Authorization':'Bearer '+'x'*40,
                        'x-memory-trace-context':json.dumps({'instanceId':'i','teamId':'t','agentId':'a','logical_call_id':'same-logical','trace_id':'1'*32})},trust_env=False)
                    self.assertEqual(r.status_code,200)
                    self.assertEqual(r.json()['usage']['total_tokens'],14)
            c.flush()
            self.assertEqual(calls,[body,body])
            self.assertEqual(server.admission.snapshot()['inference_started'],2)
            self.assertEqual(c.failed,1)
            spans=sent[0]['resourceSpans'][0]['scopeSpans'][0]['spans']
            self.assertEqual(len(spans),1)
            attrs={x['key']:x['value']['stringValue'] for x in spans[0]['attributes']}
            self.assertEqual(json.loads(attrs['langfuse.observation.usage_details']),{'input':11,'output':3})
            self.assertNotIn('langfuse.observation.cost_details',attrs)
            meta=json.loads(attrs['langfuse.observation.metadata'])
            self.assertEqual(meta['logical_call_id'],'same-logical')
            self.assertTrue(meta['inference_started'])
        finally:
            server.shutdown();server.server_close();thread.join()

    def test_real_http_export_fault_keeps_production_outbox_receipt(self):
        # Dedicated unreachable exporter, temporary application DB, no inference.
        # Shared Langfuse and real test services are never stopped or altered.
        import asyncio
        from unittest.mock import AsyncMock
        from test_contract_precedents import PrecedentTests
        case=PrecedentTests(methodName='test_real_l0_receipt_and_body')
        case.setUp()
        try:
            u,_,_,aid=case.prepared()
            tracer=mt.LocalTrace({'enabled':True,'run_id':'http-fault','app_user_ids':[u['id']]},
                {'host':'http://127.0.0.1:1','public_key':'synthetic','secret_key':'synthetic'})
            with patch.object(mt,'client',return_value=tracer):
                self.assertEqual(case.save_feedback(aid).status_code,200)
                p=case.app.state.precedents
                with patch.object(p.memory,'remote',AsyncMock(return_value={'accepted_ids':['fault-l0'],'total_count':1})) as remote:
                    asyncio.run(p.flush());asyncio.run(p.flush())
                self.assertEqual(remote.await_count,1)
                status=tracer.flush()
                self.assertGreater(status['failed'],0)
                self.assertEqual(status['queued'],0)
                self.assertEqual(p.status(aid,'TEST-1',u['id'])['status'],'l0_received')
                self.assertEqual(p.status(aid,'TEST-1',u['id'])['l0_id'],'fault-l0')
                self.assertEqual(case.store.one('SELECT attempts FROM contract_memory_deliveries')['attempts'],1)
        finally:
            case.tearDown()

    def test_cli_prompt_and_schema_are_exactly_unchanged_and_passively_captured(self):
        import hashlib
        from test_subscription_model import SubscriptionModelTests
        from contract_web.subscription_model import completion
        fixture=SubscriptionModelTests();fixture.setUp()
        fixture.body={'model':'gpt-6.1-sol','messages':[{'role':'user','content':'synthetic only'}]}
        captured=[]
        tracer=self.tracer(send=captured.append,full=True)
        bodies=[]
        schemas=[]
        def run(cmd,**kw):
            from pathlib import Path
            bodies.append(kw['input']);schemas.append(Path(cmd[cmd.index('--output-schema')+1]).read_bytes())
            return fixture.fake({'content':'synthetic result','tool_calls':[]})(cmd,**kw)
        for enabled in (False,True):
            token=mt._current.set(tracer.context({'instanceId':'i','teamId':'t','agentId':'a'}) if enabled else None)
            try:
                with patch.object(mt,'client',return_value=tracer if enabled else None):
                    response=completion(fixture.body,fixture.config,run=run)
                    self.assertEqual(response['usage']['total_tokens'],15)
            finally:
                mt._current.reset(token)
        tracer.flush()
        self.assertEqual(bodies[0],bodies[1]);self.assertEqual(schemas[0],schemas[1])
        spans=[p['resourceSpans'][0]['scopeSpans'][0]['spans'][0] for p in captured]
        self.assertEqual([s['name'] for s in spans],['subscription_bridge.cli_input','subscription_bridge.cli_response'])
        attrs={a['key']:a['value']['stringValue'] for a in spans[0]['attributes']}
        actual=json.loads(attrs['langfuse.observation.input'])
        self.assertEqual(actual['prompt'],bodies[1])
        meta=json.loads(attrs['langfuse.observation.metadata'])
        self.assertEqual(meta['prompt_sha256'],hashlib.sha256(bodies[1].encode()).hexdigest())
        self.assertNotIn('langfuse.observation.usage_details',attrs)

    def test_explicit_unselected_scope_cannot_inherit_another_requests_context(self):
        sent=[]
        c=self.tracer(send=sent.append,full=True)
        ctx=c.context({'instanceId':'i','teamId':'t','agentId':'a'})
        token=mt._current.set(ctx)
        try:
            with patch.object(mt,'client',return_value=c):
                self.assertIsNone(mt.emit('unselected',None,input='must never be exported'))
                mt.emit('selected')
            c.flush()
            self.assertEqual(len(sent),1)
            self.assertEqual(sent[0]['resourceSpans'][0]['scopeSpans'][0]['spans'][0]['name'],'selected')
        finally:
            mt._current.reset(token)
