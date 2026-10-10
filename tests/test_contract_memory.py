import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
import test_workbench as fixtures

class ContractMemoryTests(unittest.TestCase):
    setUp=fixtures.WorkbenchTests.setUp
    tearDown=fixtures.WorkbenchTests.tearDown
    login=fixtures.WorkbenchTests.login
    make_workspace=fixtures.WorkbenchTests.make_workspace
    publish=fixtures.WorkbenchTests.publish
    native=fixtures.WorkbenchTests.native
    def team(self):
        service=self.app.state.contract_memory
        self.store.execute('INSERT INTO teams VALUES(?,?,?,?,?,?)',('team-a','default','业务A',self.uid,'up-team','agent'))
        self.store.execute('INSERT INTO team_members VALUES(?,?,?,1)',('team-a',self.uid,'member'))
        return service
    def test_team_memberships_are_per_team_and_enterprise_role_does_not_grant_membership(self):
        s=self.team();u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        self.assertEqual(s.member(u,'team-a')['role'],'member')
        self.store.execute('INSERT INTO teams VALUES(?,?,?,?,?,?)',('team-b','default','业务B',self.uid,'up-b','agent-b'))
        with self.assertRaises(HTTPException):s.member({**u,'role':'admin'},'team-b')
        self.store.execute('UPDATE team_members SET active=0 WHERE team_id=?',('team-a',))
        with self.assertRaises(HTTPException):s.member(u,'team-a')
    def test_browser_identity_fields_rejected_and_review_needs_team_admin(self):
        s=self.team()
        with patch.object(s,'remote',AsyncMock(return_value={'saved':True})) as remote:
            r=self.client.post('/api/contract-memory/create',headers=self.headers,json={'team_id':'team-a','user_id':'other','operation_id':'x','data':{}})
            self.assertEqual(r.status_code,422);remote.assert_not_called()
            r=self.client.post('/api/contract-memory/review',headers=self.headers,json={'team_id':'team-a','id':'p','approved':True,'operation_id':'x'})
            self.assertEqual(r.status_code,403)
    def test_contract_upload_binds_selected_team_and_other_user_still_cannot_read(self):
        s=self.team();self.client.post('/api/contract-memory/team-selection',json={'team_id':'team-a'},headers=self.headers).raise_for_status()
        w,t=self.make_workspace();self.assertEqual(self.store.one('SELECT team_id FROM workspaces WHERE id=?',(w['id'],))['team_id'],'team-a')
        self.login('bob');self.assertEqual(self.client.get('/api/workspaces/'+w['id']).status_code,404)
    def test_candidate_session_filter_cannot_be_retargeted_to_another_contract_team(self):
        s=self.team();w,t=self.make_workspace()
        with patch.object(s,'remote',AsyncMock(return_value={'items':[]})) as remote:
            r=self.client.get('/api/contract-memory/candidates',params={'team_id':'team-a','thread_id':t['id']})
            self.assertEqual(r.status_code,200);self.assertEqual(remote.call_args.args[3]['session_id'],t['session_id'])
            self.login('bob');r=self.client.get('/api/contract-memory/candidates',params={'team_id':'team-a','thread_id':t['id']});self.assertEqual(r.status_code,403)
    def test_source_details_never_expose_another_users_title_document_or_fragment(self):
        s=self.team();u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        with patch.object(s,'remote',AsyncMock(return_value={'items':[{'context':{'workspace_id':'someone-elses','documents':[{'document_id':'private-doc'}]}}]})):
            result=asyncio.run(s.safe_sources(u,s.member(u,'team-a'),'entry'))
            self.assertEqual(result,[{'restricted':True,'label':'来源合同受限'}])
    def test_legacy_upgrade_preserves_task_and_conversation_ids(self):
        from contract_web.settings import encoded
        from contract_web.tencentdb_memory import PROVIDER
        service=self.app.state.contract_memory
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        self.app.state.models.save(u,{'id':PROVIDER,'label':'Memory','base_url':'http://127.0.0.1:8106/opencode/default/v1','models':[{'id':'deepseek-flash','label':'Flash'}],'key':'synthetic-key','revision':0})
        self.store.execute('INSERT INTO tdai_users VALUES(?,?,?,?,?,?,?,?)',(self.uid,'default','http://127.0.0.1:8430','http://127.0.0.1:8106/opencode/default/v1',None,'up-user','up-team','code-agent'))
        w,t=self.make_workspace();self.store.execute('INSERT INTO tdai_workspaces VALUES(?,?,?,?)',(w['id'],self.uid,'old-task',1))
        async def call(binding,path,body,key):return {'agent_id':'contract-agent'} if path.endswith('agent/create') else {'ok':True}
        with patch.object(service.tdai,'call',AsyncMock(side_effect=call)) as remote:
            mapped=asyncio.run(service.upgrade(u));again=asyncio.run(service.upgrade(u))
            self.assertEqual(mapped['id'],again['id']);self.assertEqual(remote.await_count,2)
        self.assertEqual(self.store.one('SELECT task_id FROM tdai_workspaces WHERE workspace_id=?',(w['id'],))['task_id'],'old-task')
        self.assertEqual(self.store.one('SELECT session_id FROM threads WHERE id=?',(t['id'],))['session_id'],t['session_id'])
        self.assertEqual(self.store.one('SELECT agent_id FROM tdai_users WHERE user_id=?',(self.uid,))['agent_id'],'code-agent')
        self.assertEqual(self.store.one('SELECT team_id FROM workspaces WHERE id=?',(w['id'],))['team_id'],mapped['id'])
    def test_provider_mismatch_fails_closed_and_ordinary_provider_has_no_memory(self):
        from types import SimpleNamespace
        from contract_web.tencentdb_memory import PROVIDER,binding_directory
        from contract_web.settings import encoded
        s=self.team();u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));w,t=self.make_workspace()
        binding={'core_url':'http://127.0.0.1:8430','proxy_url':'http://127.0.0.1:8106/opencode/default/v1','service_id':'default'}
        self.store.execute('INSERT INTO memory_identities VALUES(?,?,?,?)',(self.uid,'up-user',self.app.state.models.encrypt('correct-key'),encoded(binding)))
        self.app.state.models.save(u,{'id':PROVIDER,'label':'Memory','base_url':binding['proxy_url'],'models':[{'id':'deepseek-flash','label':'Flash'}],'key':'wrong-key','revision':0})
        rt=SimpleNamespace(config={'local':True})
        with self.assertRaises(HTTPException) as error:asyncio.run(self.app.state.tdai.prepare(u,t,rt,{'providerID':PROVIDER}))
        self.assertEqual(error.exception.status_code,422)
        result=asyncio.run(self.app.state.tdai.prepare(u,t,rt,{'providerID':'ordinary'}))
        self.assertEqual(result,{'enabled':False})
    def test_team_contract_can_publish_and_removed_member_cannot_use_save_capability(self):
        self.team();w,t=self.make_workspace()
        body={'kind':'document','title':'团队合同报告','format':'md','source_hash':self.store.one('SELECT source_hash FROM documents WHERE id=?',(w['document_id'],))['source_hash'],'content':'原文引用保持当前合同。'}
        r=self.publish(t,body);self.assertEqual(r.status_code,200,r.text);self.assertTrue(r.json()['saved'])
        self.store.execute('UPDATE team_members SET active=0 WHERE team_id=? AND user_id=?',('team-a',self.uid))
        self.assertEqual(self.publish(t,body).status_code,403)
