import asyncio,json,time,unittest
from unittest.mock import AsyncMock,patch
from pathlib import Path
from fastapi import HTTPException
import test_workbench as fixtures
import test_contract_memory as team_fixtures
from contract_web.tencentdb_memory import PROVIDER,binding_directory
from contract_web.settings import encoded

class PrecedentTests(unittest.TestCase):
 setUp=fixtures.WorkbenchTests.setUp;tearDown=fixtures.WorkbenchTests.tearDown;login=fixtures.WorkbenchTests.login;make_workspace=fixtures.WorkbenchTests.make_workspace;publish=fixtures.WorkbenchTests.publish;read_all=fixtures.WorkbenchTests.read_all;report=fixtures.WorkbenchTests.report;review_fixture=fixtures.WorkbenchTests.review_fixture;team=team_fixtures.ContractMemoryTests.team;native=fixtures.WorkbenchTests.native
 def prepared(self):
  self.team();u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,));s=self.app.state.contract_memory
  self.store.execute('INSERT INTO memory_identities VALUES(?,?,?,?)',(self.uid,'up-user',self.app.state.models.encrypt('fake'),encoded({'service_id':'default','core_url':'http://unused','proxy_url':'http://unused'})))
  w,t,report,aid=self.review_fixture();self.store.execute('INSERT INTO tdai_workspaces VALUES(?,?,?,?)',(w['id'],self.uid,'task',time.time()))
  path=self.store.user_root(self.uid)/'published'/aid/'report.json';data=json.loads(path.read_text());data.setdefault('execution_config',{})['model']={'providerID':PROVIDER};path.write_text(json.dumps(data))
  return u,w,t,aid
 def save_feedback(self,aid,note='20%预付款，仅本项目',revision=0,decision='接受风险'):
  row=self.store.one('SELECT * FROM artifacts WHERE id=?',(aid,));return self.client.put(f'/api/artifacts/{aid}/risks/TEST-1/feedback',headers=self.headers,json={'source_hash':row['source_hash'],'decision':decision,'note':note,'revision':revision})
 def test_feedback_and_outbox_commit_together_and_versions_do_not_duplicate(self):
  u,w,t,aid=self.prepared();r=self.save_feedback(aid);self.assertEqual(r.status_code,200,r.text);self.assertEqual(r.json()['memory_sync']['status'],'pending')
  q=self.store.all('SELECT * FROM contract_memory_outbox');self.assertEqual(len(q),1);event=json.loads(q[0]['data']);self.assertEqual(event['decision'],'接受风险');self.assertEqual(event['actor_user_id'],'up-user');self.assertEqual(event['document_refs'][0]['version'],event['document_version'])
  self.assertEqual(self.save_feedback(aid).status_code,409);self.assertEqual(len(self.store.all('SELECT * FROM contract_memory_outbox')),1)
  self.assertEqual(self.save_feedback(aid,revision=1,decision='要求修改').status_code,200);self.assertEqual(len(self.store.all('SELECT * FROM contract_memory_outbox')),2)
 def test_enqueue_failure_rolls_back_feedback_in_same_transaction(self):
  _,_,_,aid=self.prepared()
  with patch.object(self.app.state.precedents,'enqueue',side_effect=HTTPException(409,'来源变化')):
   r=self.save_feedback(aid);self.assertEqual(r.status_code,409)
  self.assertEqual(self.store.all('SELECT * FROM risk_feedback'),[]);self.assertEqual(self.store.all('SELECT * FROM contract_memory_outbox'),[])
 def test_delivery_failure_is_observable_and_retry_idempotent(self):
  _,_,_,aid=self.prepared();self.save_feedback(aid);p=self.app.state.precedents
  with patch.object(p.memory,'remote',AsyncMock(side_effect=HTTPException(503,'组件离线'))):asyncio.run(p.flush())
  q=self.store.one('SELECT * FROM contract_memory_outbox');self.assertEqual(q['status'],'failed');self.assertEqual(len(self.store.all('SELECT * FROM risk_feedback')),1)
  self.store.execute('UPDATE contract_memory_outbox SET next_attempt=0')
  with patch.object(p.memory,'remote',AsyncMock(return_value={'saved':True,'case_id':'case-1'})) as remote:asyncio.run(p.flush());self.assertEqual(remote.call_args.args[3]['event']['event_id'],q['id'])
  self.assertEqual(p.status(aid,'TEST-1',self.uid)['status'],'synced')
 def test_revoked_member_prevents_delivery_without_losing_feedback(self):
  _,_,_,aid=self.prepared();self.save_feedback(aid);self.store.execute('UPDATE team_members SET active=0')
  with patch.object(self.app.state.contract_memory,'remote',AsyncMock()) as remote:asyncio.run(self.app.state.precedents.flush());remote.assert_not_called()
  self.assertEqual(self.store.one('SELECT status FROM contract_memory_outbox')['status'],'failed')
 def test_current_report_cannot_be_forged_and_other_user_cannot_query(self):
  _,_,_,aid=self.prepared();self.login('bob');self.assertEqual(self.client.get(f'/api/artifacts/{aid}/risks/TEST-1/precedents').status_code,404)
  self.login('alice');self.assertEqual(self.client.get(f'/api/artifacts/{aid}/risks/no-risk/precedents').status_code,404)
 def test_precedent_sources_are_checked_after_model_wait_and_on_cache_hit(self):
  u,w,t,aid=self.prepared();self.save_feedback(aid);p=self.app.state.precedents;q=self.store.one('SELECT * FROM contract_memory_outbox');event=json.loads(q['data']);case={'id':'case-1','version':1,'workspace':w['id'],'data':event};current={**event,'workspace_id':'other','team_id':'team-a'}
  async def remote(actor,team,action,body=None):
   if action=='resources':return {'saved':True}
   if action=='case-list':return {'items':[case]}
   return {'items':[{'case_id':'case-1','version':1,'workspace_id':w['id'],'report_id':aid,'risk_id':'TEST-1','decision':'接受风险','note':event['note'],'relation':'conditional','matching_points':['风险相似'],'differences':['项目限制'],'conditions':[],'exceptions':[]}]}
  with patch.object(p.memory,'remote',AsyncMock(side_effect=remote)) as mock:
   result=asyncio.run(p.recall(u,current));self.assertEqual(len(result['items']),1);self.assertIn('?artifact=',result['items'][0]['source_url'])
   asyncio.run(p.recall(u,current));self.assertEqual(sum(c.args[2]=='precedents' for c in mock.call_args_list),1)
   self.store.execute('UPDATE workspaces SET deleted_at=? WHERE id=?',(time.time(),w['id']));self.assertEqual(asyncio.run(p.recall(u,current))['items'],[])
 def test_changed_feedback_during_inference_drops_stale_case(self):
  u,w,t,aid=self.prepared();self.save_feedback(aid);p=self.app.state.precedents;event=json.loads(self.store.one('SELECT data FROM contract_memory_outbox')['data']);case={'id':'case-1','version':1,'workspace':w['id'],'data':event}
  async def remote(actor,team,action,body=None):
   if action=='resources':return {'saved':True}
   if action=='case-list':return {'items':[case]}
   self.store.execute("UPDATE risk_feedback SET decision='待处理'")
   return {'items':[{'case_id':'case-1','version':1,'workspace_id':w['id'],'report_id':aid,'risk_id':'TEST-1'}]}
  with patch.object(p.memory,'remote',AsyncMock(side_effect=remote)):self.assertEqual(asyncio.run(p.recall(u,{**event,'team_id':'team-a'}))['items'],[])
 def test_readonly_preview_has_no_writes_and_runtime_requires_memory_binding(self):
  u,w,t,aid=self.prepared();self.save_feedback(aid);p=self.app.state.precedents;before=self.store.all('SELECT * FROM contract_memory_outbox');self.assertEqual(p.migration_preview(u)['writes'],0);self.assertEqual(before,self.store.all('SELECT * FROM contract_memory_outbox'))
  token=(self.store.user_root(self.uid)/'threads'/t['id']/'.publish-token').read_text().strip()
  with self.assertRaises(HTTPException):p.runtime_thread(token)
  self.app.state.tdai.write_binding(u,t,{'enabled':True});self.assertEqual(p.runtime_thread(token)[1]['id'],w['id'])
  self.store.execute('UPDATE team_members SET active=0');with_error=False
  with self.assertRaises(HTTPException):p.runtime_thread(token)
 def test_migration_preview_validates_and_explicit_enqueue_deduplicates(self):
  u,w,t,aid=self.prepared();self.save_feedback(aid);p=self.app.state.precedents;preview=p.migration_preview(u);self.assertTrue(preview['items'][0]['eligible']);self.assertEqual(preview['writes'],0)
  selected={'artifact_id':aid,'risk_id':'TEST-1','revision':1};self.assertEqual(p.migrate(u,[selected])['queued'],1);self.assertEqual(len(self.store.all('SELECT * FROM contract_memory_outbox')),1)
  self.store.execute('UPDATE documents SET source_hash=? WHERE id=?',('new-version',w['document_id']));self.assertFalse(p.migration_preview(u)['items'][0]['eligible'])
  with self.assertRaises(HTTPException):p.migrate(u,[selected])
 def test_ordinary_report_does_not_create_memory_event(self):
  u,w,t,aid=self.prepared();path=self.store.user_root(self.uid)/'published'/aid/'report.json';d=json.loads(path.read_text());d['execution_config']['model']['providerID']='ordinary';path.write_text(json.dumps(d));r=self.save_feedback(aid);self.assertEqual(r.status_code,200);self.assertEqual(self.store.all('SELECT * FROM contract_memory_outbox'),[])
