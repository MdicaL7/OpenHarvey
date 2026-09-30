"""Knowledge publication must be explicit and independent of Agent output."""
import json
import secrets
import unittest
from pathlib import Path
from types import SimpleNamespace
import asyncio
from fastapi.testclient import TestClient
from contract_web.app import create_app
from contract_web.store import Store
from contract_web.memory import Memory
from contract_web.presentation import PublicView
import tempfile

from contract_web.runtime import Runtime

import test_workbench as fixtures


class KnowledgeTests(unittest.TestCase):
    setUp=fixtures.WorkbenchTests.setUp
    tearDown=fixtures.WorkbenchTests.tearDown
    login=fixtures.WorkbenchTests.login
    make_workspace=fixtures.WorkbenchTests.make_workspace

    def enroll(self):
        self.store.execute("UPDATE users SET role='admin' WHERE id=?",(self.uid,))
        u=self.store.one('SELECT * FROM users WHERE id=?',(self.uid,))
        self.app.state.knowledge.set_member(u,self.uid,{'role':'maintainer','active':True})
        self.app.state.knowledge.set_member(u,self.bid,{'role':'member','active':True})
        return u

    def test_explicit_membership_and_maintainer_publication(self):
        body={'scope':'organization','kind':'rule','title':'付款期限',
              'content':'收到发票后 30 日付款','metadata':{},'sources':[]}
        self.assertEqual(self.client.post('/api/knowledge/items',json=body,headers=self.headers).status_code,403)
        self.enroll()
        self.login('bob')
        created=self.client.post('/api/knowledge/items',json=body,headers=self.headers)
        self.assertEqual(created.status_code,200,created.text)
        proposal=created.json()['proposal']
        self.assertEqual(self.client.get('/api/knowledge/items?scope=organization',headers=self.headers).json()['items'],[])
        denied=self.client.post(f"/api/knowledge/proposals/{proposal['id']}/decide",
            json={'decision':'confirm','proposal_revision':1},headers=self.headers)
        self.assertEqual(denied.status_code,403)
        self.login('alice')
        applied=self.client.post(f"/api/knowledge/proposals/{proposal['id']}/decide",
            json={'decision':'confirm','proposal_revision':1},headers=self.headers)
        self.assertEqual(applied.status_code,200,applied.text)
        iid=applied.json()['item']['id']
        self.assertEqual(self.client.get('/api/knowledge/items?scope=organization',headers=self.headers).json()['items'][0]['id'],iid)
        self.assertTrue(applied.json()['item']['status']=='active')
        repeated=self.client.post(f"/api/knowledge/proposals/{proposal['id']}/decide",
            json={'decision':'confirm','proposal_revision':1},headers=self.headers)
        self.assertTrue(repeated.json()['already_processed'])

    def test_maintainer_role_does_not_grant_platform_admin(self):
        admin=self.enroll()
        self.app.state.knowledge.set_member(admin,self.bid,{'role':'maintainer','active':True,'revision':1})
        self.login('bob')
        created=self.client.post('/api/knowledge/items',json={
            'scope':'organization','kind':'template','title':'验收文本',
            'content':'交付后十日内书面反馈。','metadata':{},'sources':[]},headers=self.headers)
        self.assertEqual(created.status_code,200,created.text)
        self.assertIn('item',created.json())
        self.assertEqual(self.client.get('/api/admin/users',headers=self.headers).status_code,403)

    def test_personal_confirmation_version_conflict_and_disable(self):
        self.enroll()
        proposed=self.client.post('/api/knowledge/proposals',json={
            'scope':'personal','kind':'preference','action':'create','content':'Start with the answer.'},headers=self.headers).json()
        self.assertEqual(self.client.get('/api/knowledge/items?scope=personal',headers=self.headers).json()['items'],[])
        confirmed=self.client.post(f"/api/knowledge/proposals/{proposed['id']}/decide",
            json={'decision':'confirm','proposal_revision':1},headers=self.headers).json()
        iid=confirmed['item']['id']
        stale=self.client.put(f'/api/knowledge/items/personal/preference/{iid}',
            json={'revision':0,'content':'Stale'},headers=self.headers)
        self.assertEqual(stale.status_code,409)
        disabled=self.client.post(f'/api/knowledge/items/personal/preference/{iid}/disable',
            json={'revision':1},headers=self.headers)
        self.assertEqual(disabled.status_code,200,disabled.text)
        self.assertEqual(self.client.get('/api/knowledge/items?scope=personal',headers=self.headers).json()['items'],[])
        restored=self.client.post(f'/api/knowledge/items/personal/preference/{iid}/restore',
            json={'revision':2},headers=self.headers)
        self.assertEqual(restored.status_code,200,restored.text)
        self.assertEqual(restored.json()['revision'],3)

    def test_org_rule_matching_unknown_metadata_and_frozen_execution(self):
        u=self.enroll()
        rule=self.client.post('/api/knowledge/items',json={
            'scope':'organization','kind':'rule','title':'供应合同付款',
            'content':'收到发票后 30 日付款','metadata':{'contract_type':'采购','category':'付款'},
            'sources':[]},headers=self.headers)
        self.assertEqual(rule.status_code,200,rule.text)
        rid=rule.json()['item']['id']
        w,t=self.make_workspace()
        self.assertEqual(self.app.state.knowledge.applicable_rules(u,{'contract_type':'服务'}),[])
        unknown=self.app.state.knowledge.applicable_rules(u,{})
        self.assertEqual(unknown[0]['applicability_unknown'],['contract_type'])
        self.client.put(f"/api/knowledge/workspaces/{w['id']}/context",
                        json={'contract_type':'采购'},headers=self.headers)
        rules=self.app.state.risks.choose(u,None,w['id'])['rules']
        self.assertIn('ORG-'+rid,{r['id'] for r in rules})

    def test_old_risk_feedback_cannot_be_claimed_as_approval(self):
        self.enroll()
        claim=self.client.post('/api/knowledge/items',json={
            'scope':'organization','kind':'case','title':'历史批准','content':'曾批准 90 天账期',
            'metadata':{'decision_type':'approval'},'sources':[]},headers=self.headers)
        self.assertEqual(claim.status_code,422)
        advisory=self.client.post('/api/knowledge/items',json={
            'scope':'organization','kind':'case','title':'审查意见','content':'需核对付款期限',
            'metadata':{'decision_type':'review'},'sources':[{'excerpt':'需核对付款期限','filename':'人工审查记录'}]},headers=self.headers)
        self.assertEqual(advisory.status_code,200,advisory.text)

    def test_document_import_and_stage_event_are_visible_queued_work(self):
        self.enroll()
        imported=self.client.post('/api/knowledge/imports',content='第一条 付款期限为30日。'.encode(),
            headers={**self.headers,'X-Filename':'policy.txt','X-Knowledge-Kind':'rule'})
        self.assertEqual(imported.status_code,200,imported.text)
        source=imported.json()
        self.assertEqual(source['status'],'saved')
        self.assertEqual(self.client.get('/api/workspaces',headers=self.headers).json(),[])
        extraction=self.client.post(f"/api/knowledge/imports/{source['workspace_id']}/extract",
            json={'kind':'rule'},headers=self.headers)
        self.assertEqual(extraction.status_code,200,extraction.text)
        self.assertEqual(extraction.json()['status'],'queued')
        w,t=self.make_workspace()
        stage_body={'stage':'review','note':'仅完成审查，尚未正式批准','request_id':'b'*24}
        stage=self.client.post(f"/api/threads/{t['id']}/knowledge-stage",
            json=stage_body,headers=self.headers)
        self.assertEqual(stage.status_code,200,stage.text)
        self.assertEqual(stage.json()['status'],'queued')
        repeated=self.client.post(f"/api/threads/{t['id']}/knowledge-stage",json=stage_body,headers=self.headers)
        self.assertEqual(repeated.json()['queue_id'],stage.json()['queue_id'])
        conflict=self.client.post(f"/api/threads/{t['id']}/knowledge-stage",
            json={**stage_body,'note':'不同补充说明'},headers=self.headers)
        self.assertEqual(conflict.status_code,409)

    def test_scoped_native_proposal_checks_exact_source_and_requires_human(self):
        u=self.enroll();w,t=self.make_workspace()
        thread=self.store.one('SELECT * FROM threads WHERE id=?',(t['id'],))
        cfg={'work_root':str(self.store.user_root(self.uid)/'threads'),
             'save_url':'http://testserver/internal/artifacts'}
        execution=self.app.state.risks.execution(u,thread,{},[],{})
        self.app.state.memory.prepare(u,thread,Runtime(cfg),execution,'msg_user')
        self.app.state.knowledge.prepare(u,thread,Runtime(cfg),execution,'msg_user')
        cap=json.loads((self.store.user_root(self.uid)/'threads'/t['id']/'.knowledge-capability').read_text())
        doc=self.store.one('SELECT * FROM documents WHERE id=?',(w['document_id'],))
        mapping=json.loads((self.store.user_root(self.uid)/'sources'/doc['id']/'document.json').read_text())
        segment=mapping['segments'][0]
        req={'request_id':secrets.token_hex(32),'execution_id':execution['id'],'thread_id':t['id'],
             'session_id':thread['session_id'],'message_id':'msg_assistant','action':'propose_create',
             'kind':'rule','title':'付款测试规则','content':'验收后 30 日付款',
             'metadata':{},'sources':[{'document_id':doc['id'],'source_hash':doc['source_hash'],
                 'block_id':segment['id'],'excerpt':segment['text']} ]}
        headers={'Authorization':'Bearer '+cap['token']}
        first=self.client.post('/internal/knowledge',json=req,headers=headers)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()['status'],'pending_confirmation')
        self.assertEqual(self.client.post('/internal/knowledge',json=req,headers=headers).json()['proposal_id'],
                         first.json()['proposal_id'])
        self.assertEqual(self.client.get('/api/knowledge/items?scope=organization',headers=self.headers).json()['items'],[])
        invalid={**req,'request_id':secrets.token_hex(32),
                 'sources':[{**req['sources'][0],'excerpt':'不存在于原文中的句子'}]}
        self.assertEqual(self.client.post('/internal/knowledge',json=invalid,headers=headers).status_code,422)
        self.assertEqual(self.client.post('/internal/knowledge',json=req,headers={'Authorization':'Bearer bad'}).status_code,403)
        proposal=first.json()['proposal_id']
        self.assertEqual(self.store.one('SELECT source_message_id FROM knowledge_proposals WHERE id=?',(proposal,))['source_message_id'],'msg_assistant')
        confirmed=self.client.post(f'/api/knowledge/proposals/{proposal}/decide',
            json={'decision':'confirm','proposal_revision':1},headers=self.headers)
        self.assertEqual(confirmed.status_code,200,confirmed.text)
        item=confirmed.json()['item']['id']
        self.assertEqual(self.client.get('/api/knowledge/items?scope=organization',headers=self.headers).json()['items'][0]['id'],item)
        looked_up=self.client.post('/internal/knowledge',json={**req,'request_id':secrets.token_hex(32),
            'action':'get','kind':'rule','id':item},headers=headers)
        self.assertEqual(looked_up.status_code,200,looked_up.text)
        view=PublicView(knowledge=self.app.state.knowledge.projector(u,thread))
        view.info({'id':'msg_assistant','role':'assistant','parentID':'msg_user'})
        references=view.part({'type':'text','messageID':'msg_assistant',
            'text':f'[[knowledge:{item}:1]] [[knowledge:{"f"*24}:1]]'})
        self.assertEqual(len(references['knowledge_references']),1)
        self.assertEqual(references['knowledge_references'][0]['kind'],'rule')
        self.assertEqual(references['knowledge_references'][0]['scope'],'organization')
        detail=self.client.get(f'/api/knowledge/items/organization/rule/{item}?revision=1',headers=self.headers).json()
        self.assertEqual(detail['current_status'],'active')
        self.assertEqual(detail['revision'],1)
        self.assertTrue(detail['sources'][0]['source_available'])
        (self.store.user_root(self.uid)/'sources'/doc['id']/'document.json').unlink()
        preserved=self.client.get(f'/api/knowledge/items/organization/rule/{item}',headers=self.headers).json()
        self.assertFalse(preserved['sources'][0]['source_available'])
        self.assertEqual(preserved['sources'][0]['excerpt'],segment['text'])

    def test_revocation_blocks_new_reads_and_e2b_exchange_retries(self):
        admin=self.enroll();w,t=self.make_workspace()
        thread=self.store.one('SELECT * FROM threads WHERE id=?',(t['id'],))
        execution=self.app.state.risks.execution(admin,thread,{},[],{})
        rt=Runtime({'work_root':str(self.store.user_root(self.uid)/'threads'),'e2b':True,
                    'save_url':'http://testserver/internal/artifacts'})
        self.app.state.knowledge.prepare(admin,thread,rt,execution,'msg_user')
        req={'request_id':secrets.token_hex(32),'execution_id':execution['id'],'thread_id':t['id'],
             'session_id':thread['session_id'],'message_id':'msg_assistant','action':'search','q':'付款'}
        path='/workspace/exchange/knowledge/'+req['request_id']+'.request.json'
        content={path:json.dumps(req).encode()}
        class Files:
            async def list(self,*args,**kwargs):return [SimpleNamespace(name=Path(p).name,path=p,size=len(v)) for p,v in list(content.items())]
            async def read(self,p,**kwargs):return content[p]
            async def write(self,p,v):content[p]=v.encode()
            async def remove(self,p):content.pop(p,None)
        sbx=SimpleNamespace(files=Files())
        asyncio.run(self.app.state.knowledge.collect(admin,w,sbx))
        receipt=json.loads(content[path.replace('.request.','.receipt.')])
        self.assertEqual(receipt['action'],'search')
        self.app.state.knowledge.set_member(admin,self.bid,{'role':'member','active':False,'revision':1})
        self.login('bob')
        self.assertEqual(self.client.get('/api/knowledge/items?scope=organization',headers=self.headers).status_code,403)
        self.assertEqual(self.client.get('/api/knowledge/parties',headers=self.headers).status_code,403)

    def test_counterparty_names_do_not_merge_and_index_can_be_corrected(self):
        self.enroll()
        first=self.client.post('/api/knowledge/parties',json={'name':'同名公司','legal_identifier':'A001'},headers=self.headers)
        second=self.client.post('/api/knowledge/parties',json={'name':'同名公司','legal_identifier':'B002'},headers=self.headers)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(second.status_code,200,second.text)
        self.assertNotEqual(first.json()['id'],second.json()['id'])
        changed=self.client.put('/api/knowledge/parties/'+first.json()['id'],
            json={'name':'同名公司（一）','legal_identifier':'A001','status':'inactive','revision':1},headers=self.headers)
        self.assertEqual(changed.status_code,200,changed.text)
        active=self.client.get('/api/knowledge/parties',headers=self.headers).json()['items']
        self.assertEqual([p['id'] for p in active],[second.json()['id']])

    def test_batch_conflict_does_not_discard_other_proposals(self):
        self.enroll()
        ids=[]
        for title in ('合同甲','合同乙'):
            result=self.client.post('/api/knowledge/proposals',json={
                'scope':'organization','kind':'rule','action':'create','title':title,
                'content':'验收后 30 日付款','metadata':{},'sources':[]},headers=self.headers)
            self.assertEqual(result.status_code,200,result.text)
            ids.append(result.json()['id'])
        response=self.client.post('/api/knowledge/proposals/batch',json={'items':[
            {'id':ids[0],'decision':'confirm','proposal_revision':1},
            {'id':ids[1],'decision':'confirm','proposal_revision':0}]},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['results'][1]['status'],409)
        self.assertEqual(len(self.client.get('/api/knowledge/items?scope=organization',headers=self.headers).json()['items']),1)
        self.assertEqual(len(self.client.get('/api/knowledge/proposals?scope=organization',headers=self.headers).json()['items']),1)

    def test_legacy_personal_row_migrates_once_with_original_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Store(root)
            uid=store.add_user('legacy','temporary-test-password')
            Memory(store)
            iid='a'*24
            store.execute('''INSERT INTO personal_memories
                (id,user_id,content,revision,created,updated,source,source_thread_id,source_message_id)
                VALUES(?,?,?,?,?,?,?,?,?)''',(iid,uid,'Legacy preference',2,1.0,2.0,'manual',None,None))
            app=create_app(root)
            self.assertEqual(app.state.memory.items(store.one('SELECT * FROM users WHERE id=?',(uid,)))[0]['id'],iid)
            self.assertEqual(store.one('SELECT status FROM personal_memories WHERE id=?',(iid,))['status'],'active')
            self.assertEqual(store.one('SELECT revision FROM personal_memory_versions WHERE memory_id=?',(iid,))['revision'],2)
            create_app(root)
            self.assertEqual(len(store.all('SELECT * FROM personal_memory_versions WHERE memory_id=?',(iid,))),1)

    def test_source_upload_survives_missing_model_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=Store(root)
            uid=store.add_user('admin','temporary-test-password')
            store.execute("UPDATE users SET role='admin' WHERE id=?",(uid,))
            app=create_app(root,fixtures.FakeRuntime,self.library)
            with TestClient(app) as client:
                headers={'X-Workbench-Request':'1'}
                self.assertEqual(client.post('/api/login',json={'username':'admin','password':'temporary-test-password'},
                                             headers=headers).status_code,200)
                uploaded=client.post('/api/knowledge/imports',content='第一条 付款期限为30日。'.encode(),
                    headers={**headers,'X-Filename':'policy.txt','X-Knowledge-Kind':'rule'})
                self.assertEqual(uploaded.status_code,200,uploaded.text)
                self.assertEqual(uploaded.json()['status'],'saved_without_runtime')
                attempt=client.post(f"/api/knowledge/imports/{uploaded.json()['workspace_id']}/extract",
                    json={'kind':'rule'},headers=headers)
                self.assertEqual(attempt.status_code,422)
                self.assertIn('模型',attempt.json()['detail'])

    def test_multi_type_query_filtering_sorting_and_permissions(self):
        admin=self.enroll()
        # Create 2 rules
        r1=self.client.post('/api/knowledge/items',json={
            'scope':'organization','kind':'rule','title':'违约金上限标准',
            'content':'违约金总额不得超过合同总价的20%','metadata':{},'sources':[]},headers=self.headers)
        self.assertEqual(r1.status_code,200)
        import time; time.sleep(0.01)
        # Create template 1
        t1=self.client.post('/api/knowledge/items',json={
            'scope':'organization','kind':'template','title':'保密协议范本条款',
            'content':'双方对商业秘密与技术资料承担保密义务','metadata':{},'sources':[]},headers=self.headers)
        self.assertEqual(t1.status_code,200)
        time.sleep(0.01)
        # Create rule 2
        r2=self.client.post('/api/knowledge/items',json={
            'scope':'organization','kind':'rule','title':'争议解决管辖约定',
            'content':'双方发生争议向原告所在地人民法院起诉','metadata':{},'sources':[]},headers=self.headers)
        self.assertEqual(r2.status_code,200)
        time.sleep(0.01)
        # Create template 2
        t2=self.client.post('/api/knowledge/items',json={
            'scope':'organization','kind':'template','title':'知识产权归属条款',
            'content':'合作开发成果的知识产权归委托方所有','metadata':{},'sources':[]},headers=self.headers)
        self.assertEqual(t2.status_code,200)
        time.sleep(0.01)
        # Create 1 case
        c1=self.client.post('/api/knowledge/items',json={
            'scope':'organization','kind':'case','title':'特批账期案例决策',
            'content':'由于战略合作特批60天付款周期','metadata':{'decision_type':'review'},
            'sources':[{'excerpt':'特批60天付款周期'}]},headers=self.headers)
        self.assertEqual(c1.status_code,200)

        # 1. Multi-type filtering: kinds=rule,template
        res=self.client.get('/api/knowledge/items?scope=organization&kinds=rule,template',headers=self.headers)
        self.assertEqual(res.status_code,200)
        items=res.json()['items']
        self.assertEqual(len(items),4)
        item_kinds={it['kind'] for it in items}
        self.assertEqual(item_kinds,{'rule','template'})
        self.assertNotIn(c1.json()['item']['id'],{it['id'] for it in items})

        # Comma-separated in kind param
        res_kind_comma=self.client.get('/api/knowledge/items?scope=organization&kind=rule,template',headers=self.headers)
        self.assertEqual(res_kind_comma.status_code,200)
        self.assertEqual(len(res_kind_comma.json()['items']),4)

        # Multiple kind params
        res_multi_param=self.client.get('/api/knowledge/items?scope=organization&kind=rule&kind=template',headers=self.headers)
        self.assertEqual(res_multi_param.status_code,200)
        self.assertEqual(len(res_multi_param.json()['items']),4)

        # 2. Server-side unified sorting (updated DESC)
        updated_times=[it['updated'] for it in items]
        self.assertEqual(updated_times,sorted(updated_times,reverse=True))
        self.assertEqual(items[0]['id'],t2.json()['item']['id'])
        self.assertEqual(items[1]['id'],r2.json()['item']['id'])
        self.assertEqual(items[2]['id'],t1.json()['item']['id'])
        self.assertEqual(items[3]['id'],r1.json()['item']['id'])

        # 3. Unified search across multiple types
        # Title match on template
        search_title=self.client.get('/api/knowledge/items?scope=organization&kinds=rule,template&q=知识产权',headers=self.headers)
        self.assertEqual(search_title.status_code,200)
        self.assertEqual(len(search_title.json()['items']),1)
        self.assertEqual(search_title.json()['items'][0]['id'],t2.json()['item']['id'])
        self.assertEqual(search_title.json()['items'][0]['match_reason'],'标题匹配')

        # Content match on rule
        search_content=self.client.get('/api/knowledge/items?scope=organization&kinds=rule,template&q=原告所在地',headers=self.headers)
        self.assertEqual(search_content.status_code,200)
        self.assertEqual(len(search_content.json()['items']),1)
        self.assertEqual(search_content.json()['items'][0]['id'],r2.json()['item']['id'])
        self.assertEqual(search_content.json()['items'][0]['match_reason'],'正文匹配')

        # 4. Validation: mixed list must NOT contain case
        mixed_case1=self.client.get('/api/knowledge/items?scope=organization&kinds=rule,case',headers=self.headers)
        self.assertEqual(mixed_case1.status_code,422)
        self.assertIn('混合列表不得包含案例',mixed_case1.json()['detail'])

        mixed_case2=self.client.get('/api/knowledge/items?scope=organization&kind=template,case',headers=self.headers)
        self.assertEqual(mixed_case2.status_code,422)
        self.assertIn('混合列表不得包含案例',mixed_case2.json()['detail'])

        mixed_case3=self.client.get('/api/knowledge/items?scope=organization&kinds=rule,template,case',headers=self.headers)
        self.assertEqual(mixed_case3.status_code,422)
        self.assertIn('混合列表不得包含案例',mixed_case3.json()['detail'])

        # Invalid kind validation
        invalid_kind=self.client.get('/api/knowledge/items?scope=organization&kinds=rule,unknown',headers=self.headers)
        self.assertEqual(invalid_kind.status_code,422)

        # 5. Legacy single-type compatibility
        single_rule=self.client.get('/api/knowledge/items?scope=organization&kind=rule',headers=self.headers)
        self.assertEqual(single_rule.status_code,200)
        self.assertEqual(len(single_rule.json()['items']),2)
        self.assertTrue(all(it['kind']=='rule' for it in single_rule.json()['items']))

        single_template=self.client.get('/api/knowledge/items?scope=organization&kind=template',headers=self.headers)
        self.assertEqual(single_template.status_code,200)
        self.assertEqual(len(single_template.json()['items']),2)
        self.assertTrue(all(it['kind']=='template' for it in single_template.json()['items']))

        single_case=self.client.get('/api/knowledge/items?scope=organization&kind=case',headers=self.headers)
        self.assertEqual(single_case.status_code,200)
        self.assertEqual(len(single_case.json()['items']),1)
        self.assertTrue(all(it['kind']=='case' for it in single_case.json()['items']))

        no_kind=self.client.get('/api/knowledge/items?scope=organization',headers=self.headers)
        self.assertEqual(no_kind.status_code,200)
        self.assertEqual(len(no_kind.json()['items']),5)

        # 6. Organization permissions
        # Active member can query
        self.login('bob')
        bob_query=self.client.get('/api/knowledge/items?scope=organization&kinds=rule,template',headers=self.headers)
        self.assertEqual(bob_query.status_code,200)
        self.assertEqual(len(bob_query.json()['items']),4)

        # Revoked member cannot query
        self.app.state.knowledge.set_member(admin,self.bid,{'role':'member','active':False,'revision':1})
        revoked_query=self.client.get('/api/knowledge/items?scope=organization&kinds=rule,template',headers=self.headers)
        self.assertEqual(revoked_query.status_code,403)


    def test_counterparty_business_identifier_maps_to_current_org_id(self):
        u=self.enroll();knowledge=self.app.state.knowledge
        party=knowledge.create_party(u,{'name':'临沄数研技术有限公司','legal_identifier':'MOCK-PARTY-A'})
        child=knowledge.create_party(u,{'name':'临沄数研（华东）科技有限公司','legal_identifier':'MOCK-PARTY-A-EAST'})
        body={'title':'四小时通知','content':'发现安全事件后四小时内通知。',
              'metadata':{'counterparty_id':'MOCK-PARTY-A','valid_from':'2026-03-01','valid_to':'2026-12-31'},
              'sources':[{'excerpt':'四小时内通知','filename':'专项约定.md'}]}
        p=knowledge.propose(u,'organization','rule','create',body,request_id='map-party')
        self.assertEqual(p['content']['metadata']['counterparty_id'],party['id'])
        self.assertEqual(p['counterparty_resolution']['status'],'resolved')
        self.assertEqual(knowledge.propose(u,'organization','rule','create',body,request_id='map-party')['id'],p['id'])
        result=knowledge.decide(u,p['id'],{'decision':'confirm','proposal_revision':1})
        item=knowledge.item(u,'organization','rule',result['item']['id'])
        self.assertEqual(item['metadata']['counterparty_id'],party['id'])
        self.assertEqual(knowledge.applicable_rules(u,{'counterparty_id':child['id']}),[])
        by_name=knowledge.propose(u,'organization','rule','create',{
            **body,'metadata':{'counterparty_id':party['name']}})
        self.assertEqual(by_name['content']['metadata']['counterparty_id'],party['id'])

    def test_unresolved_or_ambiguous_counterparty_requires_human_selection(self):
        u=self.enroll();knowledge=self.app.state.knowledge
        a=knowledge.create_party(u,{'name':'同名公司','legal_identifier':'SAME'})
        knowledge.create_party(u,{'name':'同名公司','legal_identifier':'SAME'})
        self.store.execute("INSERT INTO knowledge_parties VALUES(?,?,?,?,?, 'active',1,0,0)",
            ('f'*24,'other-org','外部公司','OTHER','[]'))
        inactive=knowledge.create_party(u,{'name':'已停用','legal_identifier':'INACTIVE'})
        knowledge.update_party(u,inactive['id'],{'name':'已停用','legal_identifier':'INACTIVE','status':'inactive','revision':1})
        for ref,expected in [('SAME','ambiguous'),('同名公司','ambiguous'),('MISSING','not_found'),
                             ('INACTIVE','not_found'),('OTHER','not_found'),('f'*24,'not_found')]:
            p=knowledge.propose(u,'organization','rule','create',{
                'title':'限定主体规则','content':'仅适用指定主体','metadata':{'counterparty_id':ref}})
            self.assertEqual(p['counterparty_resolution']['status'],expected)
            rejected=self.client.post(f"/api/knowledge/proposals/{p['id']}/decide",
                headers=self.headers,json={'decision':'confirm','proposal_revision':1})
            self.assertEqual(rejected.status_code,422,rejected.text)
            self.assertIn('选择',rejected.json()['detail'])
            self.assertEqual(self.store.one('SELECT status FROM knowledge_proposals WHERE id=?',(p['id'],))['status'],'pending')
        self.assertEqual(self.store.one('SELECT COUNT(*) AS n FROM knowledge_items')['n'],0)
        selected=knowledge.edit_proposal(u,p['id'],{'proposal_revision':1,'metadata':{'counterparty_id':a['id']}})
        self.assertEqual(selected['counterparty_resolution']['status'],'resolved')
        confirmed=knowledge.decide(u,p['id'],{'decision':'confirm','proposal_revision':2})
        self.assertEqual(knowledge.item(u,'organization','rule',confirmed['item']['id'])['metadata']['counterparty_id'],a['id'])

    def test_proposal_partial_edit_keeps_metadata_dates_and_full_sources(self):
        u=self.enroll();knowledge=self.app.state.knowledge
        source={'excerpt':'第一行\n第二行','filename':'专项约定.md','document_id':'d'*12,
                'source_hash':'h'*64,'block_id':'B2','owner_user_id':self.uid,'location':{'page':2}}
        metadata={'valid_from':'2026-03-01','valid_to':'2026-12-31','category':'安全',
                  'future_field':{'nested':['retained']},'department':'信息技术部'}
        p=knowledge.propose(u,'organization','rule','create',{
            'title':'原题','content':'原规则','metadata':metadata,'sources':[source]})
        edited=self.client.put(f"/api/knowledge/proposals/{p['id']}",headers=self.headers,
            json={'proposal_revision':1,'content':'修改正文','metadata':{'department':'数据运营部'},
                  'sources':[{'excerpt':source['excerpt']}]})
        self.assertEqual(edited.status_code,200,edited.text)
        payload=edited.json()['content']
        self.assertEqual(payload['title'],'原题')
        self.assertEqual(payload['metadata'],{**metadata,'department':'数据运营部'})
        self.assertEqual(payload['sources'],[source])
        stale=self.client.put(f"/api/knowledge/proposals/{p['id']}",headers=self.headers,
            json={'proposal_revision':1,'content':'过期修改'})
        self.assertEqual(stale.status_code,409)
        # Omission preserves sources, and an explicit null clears just that field.
        edited=knowledge.edit_proposal(u,p['id'],{'proposal_revision':2,'metadata':{'department':None}})
        self.assertNotIn('department',edited['content']['metadata'])
        self.assertEqual(edited['content']['sources'],[source])
        published=knowledge.decide(u,p['id'],{'decision':'confirm','proposal_revision':3})
        item=knowledge.item(u,'organization','rule',published['item']['id'])
        self.assertEqual(item['metadata']['valid_to'],'2026-12-31')
        stored=self.store.one('SELECT sources FROM knowledge_versions WHERE item_id=?',(item['id'],))
        self.assertEqual(json.loads(stored['sources']),[source])

    def test_published_knowledge_partial_edit_keeps_hidden_fields(self):
        u=self.enroll();knowledge=self.app.state.knowledge
        sources=[{'excerpt':'原文','filename':'政策.md','block_id':'B1','custom':{'kept':True}}]
        metadata={'category':'付款','valid_to':'2026-12-31','custom':['保留']}
        created=knowledge.manual(u,'organization','rule','create',{
            'title':'原题','content':'原文','metadata':metadata,'sources':sources})
        iid=created['item']['id']
        edited=self.client.put(f'/api/knowledge/items/organization/rule/{iid}',headers=self.headers,
            json={'revision':1,'content':'新正文','metadata':{'department':'信息技术部'}})
        self.assertEqual(edited.status_code,200,edited.text)
        item=knowledge.item(u,'organization','rule',iid)
        self.assertEqual(item['metadata'],{**metadata,'department':'信息技术部'})
        self.assertEqual(item['sources'][0]['custom'],{'kept':True})
        self.login('bob');member=self.store.one('SELECT * FROM users WHERE id=?',(self.bid,))
        suggestion=knowledge.manual(member,'organization','rule','update',{'revision':2,'content':'成员建议'},iid)['proposal']
        self.assertEqual(suggestion['content']['sources'],sources)
        self.assertEqual(suggestion['content']['metadata'],item['metadata'])
        edited=knowledge.edit_proposal(member,suggestion['id'],{'proposal_revision':1,
            'metadata':{'department':None}})
        self.assertNotIn('department',edited['content']['metadata'])
        approved=knowledge.decide(u,suggestion['id'],{'decision':'confirm','proposal_revision':2})
        self.assertEqual(approved['item']['revision'],3)
        self.assertNotIn('department',knowledge.item(u,'organization','rule',iid)['metadata'])


if __name__=='__main__':unittest.main()
