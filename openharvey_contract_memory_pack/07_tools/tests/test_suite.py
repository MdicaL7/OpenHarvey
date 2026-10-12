import contextlib,copy,hashlib,json,os,sqlite3,subprocess,sys,tempfile,threading,unittest,urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
TOOLS=Path(__file__).resolve().parents[1];sys.path.insert(0,str(TOOLS))
import structured_model as model
import run_suite
from run_suite import Runner,StopRun,Api,deterministic_checks
from suite_common import ROOT,manifest,pack_digest,require_review,source_mapping,atomic_json
from snapshot_memory import snapshot

class ReviewAndFixtureTests(unittest.TestCase):
 def test_unreviewed_execution_is_rejected(self):
  for execute,digest in [(False,pack_digest()),(True,'old'),(False,None)]:
   with self.assertRaises(RuntimeError):require_review(execute,digest)
  self.assertEqual(require_review(True,pack_digest()),pack_digest())
 def test_default_plan_never_constructs_a_network_client(self):
  with patch.object(run_suite,'Api',side_effect=AssertionError('network')),patch.object(sys,'argv',['run_suite.py','plan']),contextlib.redirect_stdout(__import__('io').StringIO()) as out:run_suite.main()
  self.assertEqual(json.loads(out.getvalue())['status'],'offline_plan')
 def test_each_category_has_positive_and_negative(self):
  cases=manifest('cases.json')
  for name in manifest('categories.json'):self.assertTrue({'positive','negative'}<={c['polarity'] for c in cases if c['category']==name})
 def test_all_clauses_are_annotated(self):
  self.assertEqual(sum(r['clause_number'] is not None for r in manifest('clause_coverage.json')),154)
 def test_each_case_and_old_query_is_scheduled(self):
  cases=manifest('cases.json');self.assertTrue(all(c['step_ids'] for c in cases));self.assertTrue({f'Q{i:02d}' for i in range(1,25)}<={c['case_id'] for c in cases})
 def test_business_uploads_do_not_contain_gold_or_operator_files(self):
  from suite_common import input_files
  inputs=input_files()
  for s in manifest('steps.json'):
   if s['action'] in {'upload_contract','attach'}:self.assertFalse(any(x in inputs[s['input_id']]['path'] for x in ['05_private_gold','06_negative_controls','09_scenarios']))
 def test_revision_is_after_asof_queries(self):
  steps=manifest('steps.json');self.assertLess(next(s['step_id'] for s in steps if s.get('query_id')=='Q24'),next(s['step_id'] for s in steps if s.get('input_id')=='F01-R2'))
 def test_mapping_uses_real_blocks_but_does_not_claim_read(self):
  m=next(r for r in json.loads((ROOT/'00_start_here/contract_manifest.json').read_text()) if r['doc_id']=='H01')
  loc=[x for x in manifest('source_locations.json') if x['input_id']=='H01'];doc={'id':'native-doc','segments':[{'id':f'B{i}','text':r['text']} for i,r in enumerate(loc)]}
  mapped=source_mapping('H01',doc,ROOT/m['txt_path']);self.assertTrue(all(x['mapping_status']=='matched' for x in mapped));self.assertFalse(any(x['native_read_verified'] for x in mapped))
  doc['segments']*=2;self.assertTrue(all(x['mapping_status']=='ambiguous' for x in source_mapping('H01',doc,ROOT/m['txt_path'])))

class ModelAdapterTests(unittest.TestCase):
 def setUp(self):self.config={'roles':{'memory_extraction':{'provider':'codex_subscription','model':'gpt-6.1-sol'},'judge':{'provider':'codex_subscription','model':'gpt-6.1-sol'}}};self.request={'role':'memory_extraction','stage':'l1','request_id':'mock-1','prompt':'输出JSON','input':{'messages':[]}}
 def fake(self,cmd,**kwargs):
  if '--version' in cmd:return subprocess.CompletedProcess(cmd,0,'codex-cli mock\n','')
  Path(cmd[cmd.index('-o')+1]).write_text('{"records":[]}');return subprocess.CompletedProcess(cmd,0,'{"type":"turn.completed","usage":{"input_tokens":4,"output_tokens":2}}\n','')
 def test_model_calls_are_off_by_default(self):
  with self.assertRaises(model.ModelError):model.complete(self.config,self.request,run=lambda *a,**k:self.fail('call'))
 def test_role_stage_cannot_cross(self):
  for value in [{'role':'judge','stage':'l1'},{'role':'memory_extraction','stage':'judge'},{'role':'other','stage':'l1'}]:
   with self.assertRaises(model.ModelError):model.complete(self.config,{**self.request,**value},execute=True,run=lambda *a,**k:self.fail('call'))
 def test_mismatched_model_is_rejected_before_call(self):
  with self.assertRaises(model.ModelError):model.complete(self.config,{**self.request,'model':'wrong-model'},execute=True,run=lambda *a,**k:self.fail('call'))
 def test_role_credentials_must_be_distinct(self):
  with self.assertRaises(model.ModelError):model.serve(self.config,'127.0.0.1',0,{'judge':'same','memory_extraction':'same'},True)
 def test_subscription_explicitly_ignores_custom_config_and_api_env(self):
  captured={}
  def fake(cmd,**kw):captured.update(command=cmd,env=kw['env']);return self.fake(cmd,**kw)
  with patch.dict(os.environ,{'OPENAI_API_KEY':'must-not-use','CODEX_API_KEY':'must-not-use'}):r=model.complete(self.config,self.request,execute=True,run=fake)
  self.assertIn('--ignore-user-config',captured['command']);self.assertIn('model_provider="openai"',captured['command']);self.assertNotIn('OPENAI_API_KEY',captured['env']);self.assertNotIn('CODEX_API_KEY',captured['env']);self.assertIsNone(r['metadata']['actual_model']);self.assertFalse(r['metadata']['model_verified'])
 def test_tools_are_disabled_and_tool_results_rejected(self):
  def fake(cmd,**kw):self.fake(cmd,**kw);return subprocess.CompletedProcess(cmd,0,'{"type":"item.completed","item":{"type":"command_execution"}}\n','')
  with self.assertRaises(model.ModelError):model.complete(self.config,self.request,execute=True,run=fake)
  cmd=model.codex_command('codex','gpt-6.1-sol',Path('/tmp'),Path('/tmp/s'),Path('/tmp/o'));self.assertIn('shell_tool',cmd);self.assertIn('memories',cmd);self.assertIn('apps',cmd);self.assertNotIn('--dangerously-bypass-approvals-and-sandbox',cmd)
 def test_invalid_json_and_missing_output_fail(self):
  def invalid(cmd,**kw):
   if '--version' in cmd:return subprocess.CompletedProcess(cmd,0,'codex-cli mock','')
   Path(cmd[cmd.index('-o')+1]).write_text('{}');return subprocess.CompletedProcess(cmd,0,'','')
  with self.assertRaises(model.ModelError):model.complete(self.config,self.request,execute=True,run=invalid)
 def test_quota_failure_does_not_fallback(self):
  with self.assertRaises(model.ModelError):model.complete(self.config,self.request,execute=True,run=lambda *a,**k:subprocess.CompletedProcess(a,1,'','quota'),urlopen=lambda *a,**k:self.fail('fallback'))
 def test_timeout_visible(self):
  def timeout(*a,**k):raise subprocess.TimeoutExpired('mock',1)
  with self.assertRaises(model.ModelError):model.complete(self.config,self.request,execute=True,run=timeout)
 def test_schema_rejects_extra_field_and_bad_kind(self):
  for value in [{'records':[],'approved':True},{'records':[{'kind':'approved'}]}]:
   with self.assertRaises(model.ModelError):model.validate(value,model.SCHEMAS['l1'])
 def test_api_alternative_uses_only_explicit_key(self):
  config=copy.deepcopy(self.config);config['roles']['memory_extraction']={'provider':'openai_compatible','model':'deepseek-flash','base_url':'http://mock','api_key_env':'TEST_MODEL_KEY'}
  class Response:
   def __enter__(self):return self
   def __exit__(self,*a):pass
   def read(self):return b'{"model":"deepseek-flash","choices":[{"finish_reason":"stop","message":{"content":"{\\"records\\":[]}"}}]}'
  with patch.dict(os.environ,{'TEST_MODEL_KEY':'private-test'}):r=model.complete(config,self.request,execute=True,urlopen=lambda *a,**k:Response())
  self.assertEqual(r['metadata']['actual_model'],'deepseek-flash')

class FakeApi:
 def __init__(self,origin):self.calls=[]
 def call(self,method,path,body=None,**kw):
  self.calls.append((method,path,body))
  if path=='/api/me':return {'id':'user-1','username':'owner','capabilities':{'admin':True}}
  if path=='/api/login':return {'ok':True}
  if path=='/api/contract-memory/teams':return {'id':'team-1','name':'fresh'}
  if path.startswith('/api/contract-memory/candidates'):return {'items':[],'jobs':[]}
  if path.startswith('/api/contract-memory/list'):return {'items':[]}
  if path=='/api/workspaces':return {'id':'workspace-1','document_id':'native-doc'}
  if path.endswith('/threads'):return {'id':'thread-1','session_id':'session-1'}
  if path.startswith('/api/documents'):
   return {'id':'native-doc','segments':[{'id':f'B{i}','text':r['text']} for i,r in enumerate(x for x in manifest('source_locations.json') if x['input_id']=='H01')]}
  return {'id':'entry-1','version':1,'data':{'content':'explicit output'}}
class RunnerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);login=self.root/'login.json';login.write_text('{"username":"owner","password":"fake-password"}')
  self.config={'origin':'http://127.0.0.1','accounts':{'owner':{'login_file':str(login)}},'diagnostics':{},'business_model':'tencentdb-memory/mock','ordinary_model':'mock/direct'}
  self.snapshot=lambda *a,**kw:{k:[] for k in ['raw','atoms','jobs','candidates','entries','proposals','revisions','audit','tombstones']}
 def tearDown(self):self.tmp.cleanup()
 def runner(self,state=None):return Runner(self.config,self.root/'run',state,FakeApi,self.snapshot)
 def test_upload_and_resume_do_not_repeat_known_mutations(self):
  steps=[{'step_id':'S001','action':'create_team','actor':'owner','team':'A','workspace':None,'name':'fresh','case_ids':[]},{'step_id':'S002','action':'upload_contract','actor':'owner','team':'A','workspace':'H01','input_id':'H01','case_ids':[]}]
  r=self.runner();r.run(steps);self.assertEqual(len(r.state['completed']),2);r2=self.runner(r.state);r2.run(steps)
  self.assertFalse(any(m=='POST' and p!='/api/login' for m,p,b in r2.clients['owner'].calls));self.assertEqual(r2.state['documents']['H01']['id'],'native-doc')
 def test_uncertain_upload_requires_operator_reconciliation(self):
  r=self.runner();r.active_step={'step_id':'S001','actor':'owner'};r.state['calls']['S001:create']={'method':'POST','path':'/api/workspaces','body':None}
  with self.assertRaises(StopRun):r.mutate('create','POST','/api/workspaces')
 def test_idempotent_retry_uses_original_payload(self):
  r=self.runner();r.active_step={'step_id':'S001','actor':'owner'};r.state['calls']['S001:confirm']={'method':'POST','path':'/api/contract-memory/confirm','body':{'version':1,'operation_id':'stable'}}
  r.mutate('confirm','POST','/api/contract-memory/confirm',body={'version':2},idempotent=True)
  self.assertEqual(r.clients['owner'].calls[-1][2],{'version':1,'operation_id':'stable'})
 def test_candidate_ambiguity_stops_without_publication(self):
  r=self.runner();s={'selector':{'kind':'experience','contains':'60天'}};e={'data':{'kind':'experience','content':'60天'}}
  for items in [[],[e,e]]:
   with self.assertRaises(StopRun):r.pick_candidate(s,{'candidates':{'items':items}})
 def test_job_failure_is_not_no_candidate_success(self):
  r=self.runner();r.state['threads']['H01']=[{'session_id':'s','id':'t'}];s={'step_id':'S001','workspace':'H01','actor':'owner','team':'A'};r.state['calls']['S001:send']={'started_at':'2026-01-01'}
  r.observed=lambda s:{'core':{'jobs':[{'session':'s','status':'failed','attempts':3}],'raw':[]}}
  with self.assertRaises(StopRun):r.wait_extraction(s,{})
 def test_unexpected_permission_is_not_auto_allowed(self):
  r=self.runner();r.state['threads']['H01']=[{'session_id':'s','id':'t'}];r.clients['owner'].call=lambda *a,**k:{'permissions':[{'id':'unknown'}]}
  with self.assertRaises(StopRun):r.wait_message({'workspace':'H01','actor':'owner'})
 def test_operator_fault_checkpoint_never_stops_services(self):
  r=self.runner()
  with self.assertRaises(StopRun):r.do({'step_id':'S001','action':'fault_checkpoint','actor':'owner','team':'A','workspace':'H01','instruction':'restart isolated instance'})
 def test_report_does_not_invent_unexecuted_results(self):
  r=self.runner();r.save();result=run_suite.report(r.out);self.assertTrue(all(c['status']=='not_executed' for c in result['cases']))
 def test_bad_l1_sources_are_deterministic_failure(self):
  core={'raw':[],'atoms':[{'id':'a','data':{'source_ids':['fake'],'business_state':'approved'}}],'entries':[],'candidates':[]}
  checks=deterministic_checks({'action':'message','wait_extraction':True},{'after':{'core':core,'personal':{'items':[]},'team':{'items':[]}}},{})
  self.assertEqual(sum(x['status']=='fail' for x in checks),2)
 def test_remote_app_is_rejected(self):
  with self.assertRaises(StopRun):Api('https://prod.example')
 def test_ordinary_provider_new_raw_is_failure(self):
  core={'raw':[{'id':'r'}],'atoms':[],'entries':[],'candidates':[]}
  checks=deterministic_checks({'action':'message','wait_extraction':False},{'before':{'core':{'raw':[]}},'after':{'core':core,'personal':{'items':[]},'team':{'items':[]}}},{})
  self.assertEqual(next(x['status'] for x in checks if x['check']=='ordinary_no_new_L0'),'fail')

class HttpReplayTests(unittest.TestCase):
 def test_real_http_client_upload_headers_and_async_acceptance(self):
  seen=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*a):pass
   def do_POST(self):
    seen.append((self.path,self.headers.get('X-Filename'),self.rfile.read(int(self.headers['Content-Length']))));self.send_response(202 if self.path.endswith('/messages') else 200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(b'{"id":"actual-mock-result"}')
  server=ThreadingHTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   api=Api('http://127.0.0.1:'+str(server.server_port));api.call('POST','/api/workspaces',raw=b'fixture',headers={'X-Filename':'contract.docx'});api.call('POST','/api/threads/t/messages',body={'text':'read','request_id':'stable'},expected=202)
   self.assertEqual(seen[0],('/api/workspaces','contract.docx',b'fixture'));self.assertEqual(json.loads(seen[1][2])['request_id'],'stable')
  finally:server.shutdown();server.server_close()

class SnapshotTests(unittest.TestCase):
 def test_readonly_snapshot_respects_user_team_and_organization(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);app=root/'app.sqlite';core=root/'core.sqlite'
   with sqlite3.connect(app) as db:
    db.executescript('CREATE TABLE teams(id,org_id,tdai_team_id,agent_id);CREATE TABLE team_members(team_id,user_id,active);CREATE TABLE users(id,username,active,org_id);CREATE TABLE memory_identities(user_id,tdai_user_id,binding);')
    db.execute('INSERT INTO teams VALUES(?,?,?,?)',('app-team','org','team','agent'));db.execute('INSERT INTO team_members VALUES(?,?,?)',('app-team','owner',1));db.execute('INSERT INTO users VALUES(?,?,?,?)',('owner','owner',1,'org'));db.execute('INSERT INTO memory_identities VALUES(?,?,?)',('owner','mem-owner','{"service_id":"default"}'))
   with sqlite3.connect(core) as db:
    for table in ['raw','atoms','jobs','candidates','entries','proposals','audit','tombstones']:db.execute('CREATE TABLE '+table+'(id,instance,team,agent,user,scope,data)')
    db.execute('CREATE TABLE revisions(id,version,data)')
    for table in ['raw','atoms','entries']:
     for uid,team,scope in [('mem-owner','team','personal'),('other','team','personal'),('mem-owner','other-team','personal'),('','team','team')]:
      db.execute('INSERT INTO '+table+' VALUES(?,?,?,?,?,?,?)',(uid+team,'default',team,'agent',uid,scope,'{"content":"bounded"}'))
   before=hashlib.sha256(core.read_bytes()).hexdigest();result=snapshot({'app_data':str(root),'sqlite_path':str(core)},'app-team','owner')
   self.assertEqual(len(result['raw']),1);self.assertEqual(len(result['atoms']),1);self.assertEqual(len(result['entries']),2);self.assertEqual(before,hashlib.sha256(core.read_bytes()).hexdigest())
   with sqlite3.connect(app) as db:db.execute("UPDATE users SET org_id='other-org'")
   with self.assertRaises(RuntimeError):snapshot({'app_data':str(root),'sqlite_path':str(core)},'app-team','owner')
if __name__=='__main__':unittest.main()
