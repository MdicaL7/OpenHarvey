import asyncio
import json
import unittest
import fnmatch
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from contract_web.app import create_app
from contract_web.tencentdb_memory import PROVIDER, bridge_permissions, binding_directory
import test_workbench as fixtures


class TencentDBMemoryTests(unittest.TestCase):
    setUp = fixtures.WorkbenchTests.setUp
    tearDown = fixtures.WorkbenchTests.tearDown
    login = fixtures.WorkbenchTests.login
    make_workspace = fixtures.WorkbenchTests.make_workspace

    def setup_binding(self):
        u = self.store.one('SELECT * FROM users WHERE id=?', (self.uid,))
        self.app.state.models.save(u, {'id':PROVIDER,'label':'Memory','base_url':'http://127.0.0.1:8096/opencode/default/v1',
            'models':[{'id':'deepseek-flash','label':'Flash'}],'key':'synthetic-user-key','revision':0})
        self.store.execute('INSERT INTO tdai_users VALUES(?,?,?,?,?,?,?,?)',
            (self.uid,'default','http://127.0.0.1:8420','http://127.0.0.1:8096/opencode/default/v1',None,'tdai-user','team','agent'))
        return u

    async def healthy(self, *args, **kwargs):
        import httpx
        return httpx.Response(200, request=httpx.Request('GET','http://127.0.0.1:8096/health'), json={'status':'ok'})

    def test_retired_api_and_tables_labs_and_legacy_history(self):
        tables={r['name'] for r in self.store.all("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse({'personal_memories','memory_capabilities','memory_receipts'} & tables)
        for method,path in [('GET','/api/memories'),('POST','/api/memories'),('PATCH','/api/memories/old'),('DELETE','/api/memories/old'),('POST','/internal/memory')]:
            r=self.client.request(method,path,json={},headers=self.headers)
            self.assertEqual(r.status_code,410,r.text)
        status=self.client.get('/api/settings/labs').json()
        self.assertNotIn('memory_enabled',status)
        self.assertEqual(self.client.patch('/api/settings/labs',json={'memory_enabled':True,'revision':status['revision']},headers=self.headers).status_code,422)
        self.store.execute('CREATE TABLE personal_memories (id TEXT, content TEXT)')
        self.store.execute('INSERT INTO personal_memories VALUES(?,?)',('old','Retained historical preference'))
        create_app(self.store.root, runtime_factory=fixtures.FakeRuntime)
        self.assertEqual(self.store.one('SELECT content FROM personal_memories WHERE id=?',('old',))['content'],'Retained historical preference')

    def test_tasks_reused_within_contract_and_distinct_across_contracts(self):
        u=self.setup_binding();w,a=self.make_workspace();w2,b=self.make_workspace()
        a=self.store.one('SELECT * FROM threads WHERE id=?',(a['id'],));b=self.store.one('SELECT * FROM threads WHERE id=?',(b['id'],))
        a2={**a,'session_id':'ses_independent'};tdai=self.app.state.tdai;created=[]
        async def call(binding,path,body,key):
            if path.endswith('auth/verify'):return {'valid':True,'user':{'user_id':'tdai-user'}}
            if path.endswith('agent/get'):return {'team_id':'team','owner_user_id':'tdai-user'}
            if path.endswith('task/create'):
                created.append(body);return {'task_id':'task-'+str(len(created))}
            if path.endswith('task/get'):return {'team_id':'team','creator_user_id':'tdai-user'}
            raise AssertionError(path)
        async def exercise():
            with patch.object(tdai,'call',side_effect=call),patch('httpx.AsyncClient.get',self.healthy):
                return await asyncio.gather(*(tdai.prepare(u,t,SimpleNamespace(config={'local':True}),{'providerID':PROVIDER}) for t in [a,b,a2,a]))
        values=asyncio.run(exercise())
        self.assertEqual(len(created),2);self.assertEqual(values[0]['task_id'],values[2]['task_id']);self.assertNotEqual(values[0]['task_id'],values[1]['task_id'])
        raw=(binding_directory(self.store,self.uid)/(a['session_id']+'.json')).read_text()
        self.assertNotIn('synthetic-user-key',raw);self.assertNotIn('gateway_secret',raw)
        self.assertTrue(bridge_permissions(values[0]));self.assertEqual(bridge_permissions({'enabled':False}),[])
        canonical = "curl -sf -X POST 'http://127.0.0.1:8096/memory-bridge/v3/atomic/search' --data-raw '{}'"
        self.assertTrue(any(fnmatch.fnmatchcase(canonical,r['pattern']) for r in bridge_permissions(values[0])))
        self.assertFalse(any(fnmatch.fnmatchcase(canonical.replace('127.0.0.1:8096','example.com'),r['pattern']) for r in bridge_permissions(values[0])))
        off=asyncio.run(tdai.prepare(u,a,SimpleNamespace(config={'local':True}),{'providerID':'direct'}))
        self.assertFalse(off['enabled']);self.assertFalse(json.loads((binding_directory(self.store,self.uid)/(a['session_id']+'.json')).read_text())['enabled'])

    def test_missing_binding_cloud_and_invalid_task_fail_closed(self):
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));_,t=self.make_workspace();t=self.store.one('SELECT * FROM threads WHERE id=?',(t['id'],));tdai=self.app.state.tdai
        for rt in [SimpleNamespace(config={'local':True}),SimpleNamespace(config={'e2b':True})]:
            with self.assertRaises(HTTPException):asyncio.run(tdai.prepare(u,t,rt,{'providerID':PROVIDER}))
        u=self.setup_binding();self.store.execute('INSERT INTO tdai_workspaces VALUES(?,?,?,0)',(t['workspace_id'],self.uid,'stale'))
        async def call(binding,path,body,key):
            if path.endswith('auth/verify'):return {'valid':True,'user':{'user_id':'tdai-user'}}
            if path.endswith('agent/get'):return {'team_id':'team','owner_user_id':'tdai-user'}
            if path.endswith('task/get'):return {'team_id':'wrong-team','creator_user_id':'tdai-user'}
            raise AssertionError('Stale tasks must never be recreated silently')
        with patch.object(tdai,'call',side_effect=call),self.assertRaises(HTTPException):
            asyncio.run(tdai.prepare(u,t,SimpleNamespace(config={'local':True}),{'providerID':PROVIDER}))
        self.assertFalse(json.loads((binding_directory(self.store,self.uid)/(t['session_id']+'.json')).read_text())['enabled'])

    def test_proxy_failure_invalidates_binding_without_model_fallback(self):
        import httpx
        u=self.setup_binding();_,t=self.make_workspace();t=self.store.one('SELECT * FROM threads WHERE id=?',(t['id'],));tdai=self.app.state.tdai
        self.store.execute('INSERT INTO tdai_workspaces VALUES(?,?,?,0)',(t['workspace_id'],self.uid,'task'))
        async def call(binding,path,body,key):
            if path.endswith('auth/verify'):return {'valid':True,'user':{'user_id':'tdai-user'}}
            if path.endswith('agent/get'):return {'team_id':'team','owner_user_id':'tdai-user'}
            if path.endswith('task/get'):return {'team_id':'team','creator_user_id':'tdai-user'}
            raise AssertionError(path)
        with patch.object(tdai,'call',side_effect=call),patch('httpx.AsyncClient.get',side_effect=httpx.ConnectError('offline')):
            with self.assertRaises(HTTPException) as error:
                asyncio.run(tdai.prepare(u,t,SimpleNamespace(config={'local':True}),{'providerID':PROVIDER}))
        self.assertEqual(error.exception.status_code,503)
        self.assertFalse(json.loads((binding_directory(self.store,self.uid)/(t['session_id']+'.json')).read_text())['enabled'])


if __name__=='__main__':unittest.main()
