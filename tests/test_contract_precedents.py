import asyncio, json, time, unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException
import test_workbench as fixtures
import test_contract_memory as team_fixtures
from contract_web.tencentdb_memory import PROVIDER
from contract_web.contract_precedents import DISPOSITION_HEADER, METADATA_KEYS
from contract_web.settings import encoded


class PrecedentTests(unittest.TestCase):
    setUp = fixtures.WorkbenchTests.setUp
    tearDown = fixtures.WorkbenchTests.tearDown
    login = fixtures.WorkbenchTests.login
    make_workspace = fixtures.WorkbenchTests.make_workspace
    publish = fixtures.WorkbenchTests.publish
    read_all = fixtures.WorkbenchTests.read_all
    report = fixtures.WorkbenchTests.report
    review_fixture = fixtures.WorkbenchTests.review_fixture
    team = team_fixtures.ContractMemoryTests.team
    native = fixtures.WorkbenchTests.native

    def prepared(self):
        self.team()
        u = self.store.one('SELECT * FROM users WHERE id=?', (self.uid,))
        self.store.execute(
            'INSERT INTO memory_identities VALUES(?,?,?,?)',
            (self.uid, 'up-user', self.app.state.models.encrypt('fake'), encoded({'service_id': 'default', 'core_url': 'http://unused', 'proxy_url': 'http://unused'})),
        )
        w, t, report, aid = self.review_fixture()
        self.store.execute('INSERT INTO tdai_workspaces VALUES(?,?,?,?)', (w['id'], self.uid, 'task', time.time()))
        path = self.store.user_root(self.uid) / 'published' / aid / 'report.json'
        data = json.loads(path.read_text())
        data.setdefault('execution_config', {})['model'] = {'providerID': PROVIDER}
        path.write_text(json.dumps(data))
        return u, w, t, aid

    def save_feedback(self, aid, note='20%预付款，仅本项目', revision=0, decision='接受风险'):
        row = self.store.one('SELECT * FROM artifacts WHERE id=?', (aid,))
        return self.client.put(
            f'/api/artifacts/{aid}/risks/TEST-1/feedback',
            headers=self.headers,
            json={'source_hash': row['source_hash'], 'decision': decision, 'note': note, 'revision': revision},
        )

    def test_feedback_and_outbox_commit_together_and_versions_do_not_duplicate(self):
        u, w, t, aid = self.prepared()
        r = self.save_feedback(aid)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['memory_sync']['status'], 'pending')
        q = self.store.all('SELECT * FROM contract_memory_outbox')
        self.assertEqual(len(q), 1)
        event = json.loads(q[0]['data'])
        self.assertEqual(event['decision'], '接受风险')
        self.assertEqual(event['actor_user_id'], 'up-user')
        self.assertEqual(event['document_refs'][0]['version'], event['document_version'])
        self.assertTrue(event['message'].startswith(DISPOSITION_HEADER))
        self.assertIn('METADATA_JSON:', event['message'])
        for key in METADATA_KEYS:
            self.assertIn(key, event['metadata'])
        self.assertEqual(self.save_feedback(aid).status_code, 409)
        self.assertEqual(len(self.store.all('SELECT * FROM contract_memory_outbox')), 1)
        self.assertEqual(self.save_feedback(aid, revision=1, decision='要求修改').status_code, 200)
        self.assertEqual(len(self.store.all('SELECT * FROM contract_memory_outbox')), 2)

    def test_enqueue_failure_rolls_back_feedback_in_same_transaction(self):
        _, _, _, aid = self.prepared()
        with patch.object(self.app.state.precedents, 'enqueue', side_effect=HTTPException(409, '来源变化')):
            r = self.save_feedback(aid)
            self.assertEqual(r.status_code, 409)
        self.assertEqual(self.store.all('SELECT * FROM risk_feedback'), [])
        self.assertEqual(self.store.all('SELECT * FROM contract_memory_outbox'), [])

    def accepted_atom(self, content='提炼摘要', **extra):
        p = self.app.state.precedents
        with patch.object(p.memory, 'remote', AsyncMock(return_value={'accepted_ids': ['msg-1'], 'total_count': 1})):
            asyncio.run(p.flush())
        return {'id': 'atom-1', 'version': 1, 'type': 'episodic', 'content': content, 'source_message_ids': ['msg-1'], **extra}

    def test_delivery_receipt_and_uncertain_timeout_no_auto_retry(self):
        _, _, _, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        with patch.object(p.memory, 'remote', AsyncMock(side_effect=HTTPException(503, '超时'))) as remote:
            asyncio.run(p.flush())
            asyncio.run(p.flush())
            self.assertEqual(remote.await_count, 1)
        self.assertEqual(p.status(aid, 'TEST-1', self.uid)['status'], 'uncertain')
        self.assertEqual(len(self.store.all('SELECT * FROM risk_feedback')), 1)

    def test_real_l0_receipt_and_body(self):
        _, _, t, aid = self.prepared()
        note = '  用户原文\n条件不可删  '
        self.save_feedback(aid, note=note)
        p = self.app.state.precedents
        with patch.object(p.memory, 'remote', AsyncMock(return_value={'accepted_ids': ['msg-1'], 'total_count': 1})) as remote:
            asyncio.run(p.flush())
        body = remote.call_args.args[3]
        self.assertEqual(body['task_id'], 'task')
        self.assertEqual(body['session_id'], t['session_id'])
        message = body['messages'][0]
        self.assertEqual(set(message), {'role', 'content'})
        data = json.loads(message['content'].split('METADATA_JSON: ', 1)[1])
        self.assertEqual(data['note'], note)
        self.assertEqual(data['schema_version'], 1)
        self.assertIn('created_at', data)
        self.assertIn('接受风险不代表正式审批', message['content'])
        status = p.status(aid, 'TEST-1', self.uid)
        self.assertEqual(status['status'], 'l0_received')
        self.assertEqual(status['l0_id'], 'msg-1')
        self.assertEqual(status['l1_status'], 'not_observed')

    def test_zero_received_is_not_success(self):
        _, _, _, aid = self.prepared()
        self.save_feedback(aid)
        with patch.object(self.app.state.contract_memory, 'remote', AsyncMock(return_value={'accepted_ids': [], 'total_count': 0})):
            asyncio.run(self.app.state.precedents.flush())
        self.assertEqual(self.app.state.precedents.status(aid, 'TEST-1', self.uid)['status'], 'uncertain')

    def test_revoked_member_prevents_delivery_without_losing_feedback(self):
        _, _, _, aid = self.prepared()
        self.save_feedback(aid)
        self.store.execute('UPDATE team_members SET active=0')
        with patch.object(self.app.state.contract_memory, 'remote', AsyncMock()) as remote:
            asyncio.run(self.app.state.precedents.flush())
            remote.assert_not_called()
        self.assertEqual(self.store.one('SELECT status FROM contract_memory_deliveries')['status'], 'blocked')

    def test_current_report_cannot_be_forged_and_other_user_cannot_query(self):
        _, _, _, aid = self.prepared()
        self.login('bob')
        self.assertEqual(self.client.get(f'/api/artifacts/{aid}/risks/TEST-1/precedents').status_code, 404)
        self.login('alice')
        self.assertEqual(self.client.get(f'/api/artifacts/{aid}/risks/no-risk/precedents').status_code, 404)

    def test_precedent_sources_are_checked_after_model_wait_and_on_cache_hit(self):
        u, w, t, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        q = self.store.one('SELECT * FROM contract_memory_outbox')
        event = json.loads(q['data'])
        atom = self.accepted_atom()
        current = {**event, 'workspace_id': 'other', 'team_id': 'team-a', 'our_role': '乙方（供货方）'}

        async def remote(actor, team, action, body=None):
            self.assertEqual(action, '/v3/atomic/search')
            self.assertFalse(action.startswith('/v3/contract-memory'))
            return {'items': [atom]}

        with patch.object(p.memory, 'remote', AsyncMock(side_effect=remote)) as mock:
            result = asyncio.run(p.recall(u, current))
            self.assertEqual(len(result['items']), 1)
            self.assertIn('?artifact=', result['items'][0]['source_url'])
            self.assertEqual(result['items'][0]['relation'], 'conditional')
            asyncio.run(p.recall(u, current))
            self.assertEqual(mock.await_count, 1)
            self.store.execute('UPDATE workspaces SET deleted_at=? WHERE id=?', (time.time(), w['id']))
            self.assertEqual(asyncio.run(p.recall(u, current))['items'], [])

    def test_changed_feedback_during_inference_drops_stale_case(self):
        u, w, t, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        event = json.loads(self.store.one('SELECT data FROM contract_memory_outbox')['data'])
        atom = self.accepted_atom()

        async def remote(actor, team, action, body=None):
            self.assertEqual(action, '/v3/atomic/search')
            self.store.execute("UPDATE risk_feedback SET decision='待处理'")
            return {'items': [atom]}

        with patch.object(p.memory, 'remote', AsyncMock(side_effect=remote)):
            self.assertEqual(asyncio.run(p.recall(u, {**event, 'team_id': 'team-a'}))['items'], [])

    def test_local_filtering_drops_opposite_role_and_changed_doc_version_and_grades_applicable(self):
        u, w, t, aid = self.prepared()
        self.save_feedback(aid, note='常规标准验收条款可接受', revision=0, decision='接受风险')
        p = self.app.state.precedents
        event = json.loads(self.store.one('SELECT data FROM contract_memory_outbox')['data'])
        seller_meta = {**event['metadata'], 'our_role': '乙方（供货方）'}
        event['our_role'] = '供货方'
        self.store.execute('UPDATE contract_memory_deliveries SET data=?', (encoded(event),))
        atom = self.accepted_atom()

        with patch.object(p.memory, 'remote', AsyncMock(return_value={'items': [atom]})):
            # 1. Opposite role (buyer vs seller) is excluded locally
            p.cache.clear()
            opposite_current = {**event, 'workspace_id': 'other', 'team_id': 'team-a', 'our_role': '甲方（采购方）'}
            self.assertEqual(asyncio.run(p.recall(u, opposite_current))['items'], [])

            # 2. Opposite service role (委托方 vs 受托方) is also excluded locally
            p.cache.clear()
            service_atom = {**atom, 'source_message_ids': ['unknown']}
            with patch.object(p.memory, 'remote', AsyncMock(return_value={'items': [service_atom]})):
                self.assertEqual(asyncio.run(p.recall(u, {**event, 'workspace_id': 'other', 'team_id': 'team-a', 'our_role': '委托方'}))['items'], [])

            # 3. Same role, same risk_definition_hash, and no project-only restriction -> applicable
            p.cache.clear()
            same_role_current = {**event, 'workspace_id': 'other', 'team_id': 'team-a', 'our_role': '供货方'}
            res = asyncio.run(p.recall(u, same_role_current))
            self.assertEqual(len(res['items']), 1)
            self.assertEqual(res['items'][0]['relation'], 'conditional')

            # 4. Changed risk_definition_hash -> conditional
            p.cache.clear()
            changed_hash_current = {**same_role_current, 'risk_definition_hash': 'different-hash'}
            res_cond = asyncio.run(p.recall(u, changed_hash_current))
            self.assertEqual(len(res_cond['items']), 1)
            self.assertEqual(res_cond['items'][0]['relation'], 'conditional')

            # 5. Document version changed in local SQLite -> excluded locally
            p.cache.clear()
            self.store.execute('UPDATE documents SET source_hash=? WHERE id=?', ('changed-doc-version', w['document_id']))
            self.assertEqual(asyncio.run(p.recall(u, same_role_current))['items'], [])

    def test_readonly_preview_has_no_writes_and_runtime_requires_memory_binding(self):
        u, w, t, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        before = self.store.all('SELECT * FROM contract_memory_outbox')
        self.assertEqual(p.migration_preview(u)['writes'], 0)
        self.assertEqual(before, self.store.all('SELECT * FROM contract_memory_outbox'))
        token = (self.store.user_root(self.uid) / 'threads' / t['id'] / '.publish-token').read_text().strip()
        with self.assertRaises(HTTPException):
            p.runtime_thread(token)
        self.app.state.tdai.write_binding(u, t, {'enabled': True})
        self.assertEqual(p.runtime_thread(token)[1]['id'], w['id'])
        self.store.execute('UPDATE team_members SET active=0')
        with self.assertRaises(HTTPException):
            p.runtime_thread(token)

    def test_migration_preview_validates_and_explicit_enqueue_deduplicates(self):
        u, w, t, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        self.store.execute('DELETE FROM contract_memory_deliveries')
        self.store.execute("UPDATE contract_memory_outbox SET status='synced'")
        preview = p.migration_preview(u)
        self.assertTrue(preview['items'][0]['eligible'])
        self.assertEqual(preview['writes'], 0)
        selected = {'artifact_id': aid, 'risk_id': 'TEST-1', 'revision': 1}
        self.assertEqual(p.migrate(u, [selected, selected])['queued'], 1)
        self.assertEqual(self.store.one('SELECT status FROM contract_memory_outbox')['status'], 'synced')
        with self.assertRaises(HTTPException):
            p.migrate(u, [selected])
        self.assertEqual(len(self.store.all('SELECT * FROM contract_memory_outbox')), 1)
        self.store.execute('UPDATE documents SET source_hash=? WHERE id=?', ('new-version', w['document_id']))
        self.assertFalse(p.migration_preview(u)['items'][0]['eligible'])
        with self.assertRaises(HTTPException):
            p.migrate(u, [selected])

    def test_ordinary_report_does_not_create_memory_event(self):
        u, w, t, aid = self.prepared()
        path = self.store.user_root(self.uid) / 'published' / aid / 'report.json'
        d = json.loads(path.read_text())
        d['execution_config']['model']['providerID'] = 'ordinary'
        path.write_text(json.dumps(d))
        r = self.save_feedback(aid)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(self.store.all('SELECT * FROM contract_memory_outbox'), [])

    def test_unknown_source_cannot_use_model_ids_or_latest_feedback(self):
        _, _, _, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        event = json.loads(self.store.one('SELECT data FROM contract_memory_outbox')['data'])
        self.assertIsNone(p.parse_candidate({'id': 'a', **event}))
        self.assertIsNone(p.parse_candidate({'id': 'a', 'source_message_ids': ['missing'], **event}))
        atom = self.accepted_atom()
        case = p.parse_candidate({**atom, 'note': 'forged', 'revision': 99, 'document_version': 'forged'})
        self.assertEqual(case['data']['note'], event['note'])
        self.assertEqual(case['data']['revision'], 1)
        self.save_feedback(aid, revision=1, note='新版')
        u = self.store.one('SELECT * FROM users WHERE id=?', (self.uid,))
        self.assertFalse(p.allowed_case(u, p.memory.member(u, 'team-a'), case))

    def test_empty_note_and_current_contract_exclusion(self):
        u, _, _, aid = self.prepared()
        self.save_feedback(aid, note='   ', decision='要求修改')
        p = self.app.state.precedents
        atom = self.accepted_atom()
        self.assertEqual(p.status(aid, 'TEST-1', self.uid)['l1_status'], 'not_expected')
        self.assertIsNone(p.parse_candidate(atom))
        self.save_feedback(aid, revision=1, note='理由')
        self.store.execute("UPDATE contract_memory_deliveries SET status='l0_received',l0_id='msg-2' WHERE l0_id IS NULL")
        event = json.loads(self.store.one('SELECT data FROM contract_memory_outbox ORDER BY created DESC LIMIT 1')['data'])
        with patch.object(p.memory, 'remote', AsyncMock(return_value={'items': [{**atom, 'source_message_ids': ['msg-2']}]})):
            self.assertEqual(asyncio.run(p.recall(u, event))['items'], [])

    def test_overlength_event_preserves_feedback_without_sending(self):
        _, _, _, aid = self.prepared()
        p = self.app.state.precedents
        original = p.format_disposition_message
        with patch.object(p, 'format_disposition_message', side_effect=lambda x: original(x) + '文' * 8192):
            self.assertEqual(self.save_feedback(aid).status_code, 200)
        with patch.object(p.memory, 'remote', AsyncMock()) as remote:
            asyncio.run(p.flush())
            remote.assert_not_called()
        self.assertEqual(p.status(aid, 'TEST-1', self.uid)['status'], 'blocked_length')

    def test_search_hydrates_exact_atomic_id_from_native_query(self):
        u, _, _, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        atom = self.accepted_atom(metadata={'conditions': ['先核验担保'], 'exceptions': ['特批']})
        event = json.loads(self.store.one('SELECT data FROM contract_memory_outbox')['data'])
        async def remote(actor, team, endpoint, body):
            if endpoint.endswith('/search'):
                return {'items': [{k:v for k,v in atom.items() if k != 'source_message_ids'}]}
            self.assertEqual(endpoint, '/v3/atomic/query')
            self.assertEqual(body, {'limit': 100, 'offset': 0})
            return {'items': [atom], 'total': 1}
        with patch.object(p.memory, 'remote', AsyncMock(side_effect=remote)):
            result = asyncio.run(p.recall(u, {**event, 'workspace_id': 'other'}))
        self.assertEqual(result['items'][0]['conditions'], ['先核验担保'])
        self.assertEqual(result['items'][0]['relation'], 'conditional')
        self.assertEqual(p.status(aid, 'TEST-1', self.uid)['l1_status'], 'found')

    def test_source_unavailable_notice_and_no_fuzzy_query_match(self):
        u, _, _, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        atom = self.accepted_atom()
        event = json.loads(self.store.one('SELECT data FROM contract_memory_outbox')['data'])
        async def remote(actor, team, endpoint, body):
            return {'items': [{'id': 'different' if endpoint.endswith('/query') else 'a', 'content': '摘要'}], 'total': 1}
        with patch.object(p.memory, 'remote', AsyncMock(side_effect=remote)):
            result = asyncio.run(p.recall(u, {**event, 'workspace_id': 'other'}))
        self.assertEqual(result['items'], [])
        self.assertEqual(result['unavailable_sources'], 1)
        self.assertIn('不可用', result['notice'])
        self.assertIsNone(p.parse_candidate({**atom, 'source_message_ids': ['msg-1', 'unknown']}))

    def test_retry_only_requeues_unsent_blocked_delivery(self):
        _, _, _, aid = self.prepared()
        self.save_feedback(aid)
        q = self.store.one('SELECT * FROM contract_memory_outbox')
        url = '/api/contract-memory/sync-retry'
        self.store.execute("UPDATE contract_memory_deliveries SET status='uncertain'")
        self.assertEqual(self.client.post(url, headers=self.headers, json={'event_id': q['id']}).status_code, 409)
        self.store.execute("UPDATE contract_memory_deliveries SET status='blocked'")
        result = self.client.post(url, headers=self.headers, json={'event_id': q['id']})
        self.assertEqual(result.json()['queued'], 1)
        self.assertEqual(self.store.one('SELECT * FROM contract_memory_outbox'), q)
        self.assertEqual(self.client.post(url, headers=self.headers, json={'event_id': q['id']}).status_code, 409)

    def test_astral_length_uses_native_utf16_limit(self):
        from contract_web.contract_precedents import message_length
        self.assertEqual(message_length('😀' * 4097), 8194)

    def test_transport_semantics_and_safe_recovery(self):
        import httpx
        from contract_web.contract_memory import MemoryTransportError
        _, _, _, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        eid = self.store.one('SELECT event_id FROM contract_memory_deliveries')['event_id']
        for kind, safe in [(httpx.ConnectError, True), (httpx.ConnectTimeout, True), (httpx.PoolTimeout, True), (httpx.ReadTimeout, False), (httpx.WriteTimeout, False), (httpx.ReadError, False)]:
            self.store.execute("UPDATE contract_memory_deliveries SET status='pending'")
            error = MemoryTransportError(kind('synthetic'))
            self.assertEqual(error.safe_to_retry, safe)
            with patch.object(p.memory, 'remote', AsyncMock(side_effect=error)) as remote:
                asyncio.run(p.flush())
                asyncio.run(p.flush())
                self.assertEqual(remote.await_count, 1)
            self.assertEqual(p.status(aid, 'TEST-1', self.uid)['status'], 'blocked' if safe else 'uncertain')
            response = self.client.post('/api/contract-memory/sync-retry', headers=self.headers, json={'event_id': eid})
            self.assertEqual(response.status_code, 200 if safe else 409)
        self.store.execute("UPDATE contract_memory_deliveries SET status='blocked'")
        self.client.post('/api/contract-memory/sync-retry', headers=self.headers, json={'event_id': eid}).raise_for_status()
        with patch.object(p.memory, 'remote', AsyncMock(return_value={'accepted_ids': ['recovered'], 'total_count': 1})):
            asyncio.run(p.flush())
        self.assertEqual(p.status(aid, 'TEST-1', self.uid)['status'], 'l0_received')

    def test_real_transport_preserves_exception_class_without_exposing_url(self):
        import httpx
        from contract_web.contract_memory import MemoryTransportError
        u, _, _, _ = self.prepared()
        memory = self.app.state.contract_memory
        team = memory.member(u, 'team-a')
        for error, safe in [(httpx.ConnectError('secret-url'), True), (httpx.ReadTimeout('secret-url'), False)]:
            client = AsyncMock()
            client.__aenter__.return_value = client
            client.post.side_effect = error
            with patch('contract_web.contract_memory.httpx.AsyncClient', return_value=client):
                with self.assertRaises(MemoryTransportError) as caught:
                    asyncio.run(memory.remote(u, team, '/v3/conversation/add', {}))
            self.assertIs(caught.exception.__cause__, error)
            self.assertEqual(caught.exception.safe_to_retry, safe)
            self.assertNotIn('secret-url', caught.exception.detail)

    def test_concurrent_workers_claim_once_and_do_not_overwrite_receipt(self):
        from contract_web.contract_precedents import ContractPrecedents
        _, _, _, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        second = ContractPrecedents(p.memory)
        async def remote(*args):
            await asyncio.sleep(.01)
            return {'accepted_ids': ['concurrent'], 'total_count': 1}
        async def run():
            await asyncio.gather(p.flush(), second.flush())
        with patch.object(p.memory, 'remote', AsyncMock(side_effect=remote)) as mock:
            asyncio.run(run())
            self.assertEqual(mock.await_count, 1)
        self.assertEqual(p.status(aid, 'TEST-1', self.uid)['status'], 'l0_received')
        # A stale worker failing validation must not overwrite a confirmed row.
        self.store.execute("UPDATE contract_memory_deliveries SET status='pending',l0_id=NULL")
        def member(*args):
            self.store.execute("UPDATE contract_memory_deliveries SET status='l0_received',l0_id='confirmed'")
            raise HTTPException(403, 'changed during validation')
        with patch.object(p.memory, 'member', side_effect=member):
            asyncio.run(p.flush())
        self.assertEqual(p.status(aid, 'TEST-1', self.uid)['l0_id'], 'confirmed')
        self.assertEqual(p.status(aid, 'TEST-1', self.uid)['status'], 'l0_received')

    def test_bounded_search_finds_twenty_first_and_caps_requests(self):
        u, _, _, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        atom = self.accepted_atom()
        event = json.loads(self.store.one('SELECT data FROM contract_memory_outbox')['data'])
        limits = []
        async def remote(actor, team, endpoint, body):
            self.assertEqual(endpoint, '/v3/atomic/search')
            limits.append(body['limit'])
            entries = [{'id': f'ordinary-{i}', 'source_message_ids': [f'chat-{i}']} for i in range(100)]
            entries[20] = atom
            return {'items': entries[:body['limit']]}
        with patch.object(p.memory, 'remote', AsyncMock(side_effect=remote)):
            result = asyncio.run(p.recall(u, {**event, 'workspace_id': 'other'}))
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(limits, [20, 50, 100])

    def test_latest_revision_and_empty_or_withdrawn_replacement(self):
        u, _, _, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        old = self.accepted_atom()
        self.save_feedback(aid, revision=1, note='新版理由')
        with patch.object(p.memory, 'remote', AsyncMock(return_value={'accepted_ids': ['msg-new'], 'total_count': 1})):
            asyncio.run(p.flush())
        latest = {**old, 'id': 'latest', 'source_message_ids': ['msg-new']}
        event = json.loads(self.store.one('SELECT data FROM contract_memory_outbox ORDER BY created DESC LIMIT 1')['data'])
        def recall():
            p.cache.clear()
            with patch.object(p.memory, 'remote', AsyncMock(return_value={'items': [old, latest]})):
                return asyncio.run(p.recall(u, {**event, 'workspace_id': 'other'}))['items']
        self.assertEqual([x['version'] for x in recall()], [2])
        self.assertEqual(self.save_feedback(aid, revision=2, note=' ', decision='要求修改').status_code, 200)
        self.assertEqual(recall(), [])
        self.assertEqual(self.save_feedback(aid, revision=3, note='', decision='待处理').status_code, 200)
        self.assertEqual(recall(), [])

    def test_shared_samples_match_production_formatter(self):
        from scripts.generate_disposition_samples import samples
        from pathlib import Path
        self.assertEqual(json.loads(Path('docs/disposition-samples.json').read_text()), samples())
        for sample in samples():
            metadata = json.loads(sample['message'].split('METADATA_JSON: ', 1)[1])
            self.assertIs(type(metadata['schema_version']), int)
            self.assertEqual(metadata['note'], sample['payload']['note'])

    def test_target_rebind_is_verified_explicit_and_preserves_snapshot(self):
        u, _, _, aid = self.prepared()
        self.save_feedback(aid)
        p = self.app.state.precedents
        eid = self.store.one('SELECT event_id FROM contract_memory_deliveries')['event_id']
        binding = json.loads(self.store.one('SELECT binding FROM memory_identities')['binding'])
        binding['core_url'] = 'http://new-synthetic-target'
        self.store.execute('UPDATE memory_identities SET binding=?', (encoded(binding),))
        asyncio.run(p.flush())
        before = self.store.one('SELECT * FROM contract_memory_deliveries')
        self.assertEqual(before['status'], 'blocked')
        async def meta(binding, endpoint, body, key):
            return {'auth/verify': {'valid': True, 'user': {'user_id': 'up-user'}},
                    'agent/get': {'team_id': 'up-team', 'status': 'active'},
                    'task/get': {'team_id': 'up-team', 'creator_user_id': 'up-user', 'status': 'running'},
                    'team-member/get': {'status': 'active'},
                    'task-agent/list': {'items': [{'agent_id': 'agent', 'status': 'active'}]}}[endpoint.removeprefix('/v3/meta/')]
        for failed_path, bad in [('auth/verify', {'valid': False}), ('agent/get', {'team_id': 'wrong', 'status': 'active'}), ('task/get', {'team_id': 'up-team', 'creator_user_id': 'wrong', 'status': 'running'}), ('team-member/get', {'status': 'inactive'}), ('task-agent/list', {'items': []})]:
            async def invalid(binding, endpoint, body, key):
                return bad if endpoint.endswith('/' + failed_path) else await meta(binding, endpoint, body, key)
            with patch.object(p.memory.tdai, 'call', AsyncMock(side_effect=invalid)):
                with self.assertRaises(HTTPException):
                    asyncio.run(p.rebind(u, eid))
            self.assertEqual(self.store.one('SELECT * FROM contract_memory_deliveries'), before)
        with patch.object(p.memory.tdai, 'call', AsyncMock(side_effect=meta)):
            preview = asyncio.run(p.rebind(u, eid))
            self.assertEqual(self.store.one('SELECT * FROM contract_memory_deliveries'), before)
            self.assertEqual(asyncio.run(p.rebind(u, eid, preview['preview_token']))['queued'], 1)
            with self.assertRaises(HTTPException):
                asyncio.run(p.rebind(u, eid, preview['preview_token']))
        history = self.store.one('SELECT snapshot FROM contract_memory_delivery_history')
        self.assertEqual(json.loads(history['snapshot']), before)
        self.assertEqual(json.loads(self.store.one('SELECT data FROM contract_memory_deliveries')['data'])['target'][0], binding['core_url'])
        for state in ('uncertain', 'l0_received'):
            self.store.execute('UPDATE contract_memory_deliveries SET status=?', (state,))
            with patch.object(p.memory.tdai, 'call', AsyncMock()) as remote:
                with self.assertRaises(HTTPException):
                    asyncio.run(p.rebind(u, eid))
                remote.assert_not_called()

    def test_passive_trace_keeps_l0_body_and_receipt_on_export_failure(self):
        from contract_web import memory_trace as mt
        u, _, t, aid = self.prepared()
        captured=[]
        def fail(payload):
            captured.append(payload)
            raise OSError('synthetic exporter failure')
        tracer=mt.LocalTrace({'enabled':True,'run_id':'synthetic-run','app_user_ids':[u['id']],
            'include_content':True,'synthetic_data':True},
            {'host':'http://127.0.0.1:3000','public_key':'test','secret_key':'test'},send=fail)
        with patch.object(mt,'client',return_value=tracer):
            response=self.save_feedback(aid,note='  合成条件，保持原文  ')
            self.assertEqual(response.status_code,200,response.text)
            p=self.app.state.precedents
            row=self.store.one('SELECT data FROM contract_memory_deliveries')
            payload=json.loads(row['data'])
            self.assertEqual(payload['trace_context']['run_id'],'synthetic-run')
            self.assertNotIn('trace_context',payload['metadata'])
            self.assertNotIn('synthetic-run',p.format_disposition_message(payload))
            with patch.object(p.memory,'remote',AsyncMock(return_value={'accepted_ids':['msg-trace'],'total_count':1})) as remote:
                asyncio.run(p.flush());asyncio.run(p.flush())
            self.assertEqual(remote.await_count,1)
            body=remote.call_args.args[3]
            self.assertEqual(body,{'task_id':'task','session_id':t['session_id'],
                'messages':[{'role':'user','content':p.format_disposition_message(payload)}]})
            self.assertEqual(p.status(aid,'TEST-1',u['id'])['l0_id'],'msg-trace')
            self.assertGreater(tracer.flush()['failed'],0)
            spans=[p['resourceSpans'][0]['scopeSpans'][0]['spans'][0] for p in captured]
            attrs=[{a['key']:a['value']['stringValue'] for a in s['attributes']} for s in spans]
            meta=[json.loads(a['langfuse.observation.metadata']) for a in attrs]
            self.assertTrue(any(m.get('l0_message_ids')==['msg-trace'] for m in meta))


if __name__ == '__main__':
    unittest.main()
