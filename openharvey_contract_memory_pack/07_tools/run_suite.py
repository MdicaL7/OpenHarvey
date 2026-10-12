#!/usr/bin/env python3
"""Review-gated, journaled application API replay. plan/report never make model calls."""
import argparse,hashlib,http.cookiejar,json,re,time,urllib.request,urllib.error,urllib.parse,uuid,sqlite3
from pathlib import Path
from suite_common import ROOT,atomic_json,manifest,pack_digest,require_review,input_files,read_json,source_mapping
from snapshot_memory import snapshot as core_snapshot
from structured_model import complete,ModelError

class StopRun(RuntimeError):pass
def scrub(value):
    if isinstance(value,dict):return {k:('[redacted]' if re.search(r'password|secret|token|api.?key|authorization',k,re.I) else scrub(v)) for k,v in value.items()}
    if isinstance(value,list):return [scrub(v) for v in value]
    if isinstance(value,str):return re.sub(r'\bsk-[A-Za-z0-9_-]{16,}\b','[redacted]',value)
    return value
class Api:
    def __init__(self,origin):
        if urllib.parse.urlparse(origin).hostname not in {'127.0.0.1','localhost','::1'}:raise StopRun('首版仅支持明确的本机测试实例')
        self.origin=origin.rstrip('/');self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(self,method,path,body=None,raw=None,headers=None,expected=200):
        h={'X-Workbench-Request':'1',**(headers or {})};data=raw
        if body is not None:data=json.dumps(body,ensure_ascii=False).encode();h['Content-Type']='application/json'
        req=urllib.request.Request(self.origin+path,data=data,method=method,headers=h)
        try:
            with self.opener.open(req,timeout=40) as r:status=r.status;value=json.load(r)
        except urllib.error.HTTPError as e:
            status=e.code
            try:value=json.load(e)
            except ValueError:value={'error':'HTTP '+str(status)}
        if status!=expected:raise StopRun('应用接口 '+path+' 返回 '+str(status)+'；'+str(scrub(value)))
        return value

class Runner:
    def __init__(self,config,out,state=None,api_factory=Api,snapshot_fn=core_snapshot):
        self.config=config;self.out=Path(out);self.out.mkdir(parents=True,exist_ok=True);self.snapshot_fn=snapshot_fn
        cfgsha=hashlib.sha256(json.dumps({k:config.get(k) for k in ['origin','business_model','ordinary_model','accounts','diagnostics','models']},sort_keys=True).encode()).hexdigest()
        self.state=state or {'run_id':uuid.uuid4().hex,'pack_sha':pack_digest(),'config_sha':cfgsha,'completed':[],'calls':{},'teams':{},'spaces':{},'threads':{},'documents':{},'entries':{},'proposals':{},'evidence':{},'entry_baselines':{},'candidate_baselines':{}}
        if self.state.get('config_sha',cfgsha)!=cfgsha:raise StopRun('模型或身份配置已改变，请建立新运行；操作员证据和等待参数可补充')
        self.clients={};self.users={};self.inputs=input_files();self.active_step=None
        for role,account in config['accounts'].items():
            client=api_factory(account.get('origin',config['origin']));login=read_json(account['login_file']);client.call('POST','/api/login',body=login);self.users[role]=client.call('GET','/api/me');self.clients[role]=client
    def diagnostics(self,actor):return self.config['accounts'][actor].get('diagnostics',self.config['diagnostics'])
    def save(self):atomic_json(self.out/'checkpoint.json',self.state)
    def mutate(self,name,method,path,body=None,raw=None,headers=None,expected=200,actor=None,idempotent=False):
        actor=actor or self.active_step['actor'];key=self.active_step['step_id']+':'+name
        old=self.state['calls'].get(key)
        if old and old.get('result') is not None:return old['result']
        if old and not idempotent:raise StopRun('该非幂等操作结果不确定，请核查并在检查点补入真实 result：'+key)
        if old:body=old.get('body',body)
        else:self.state['calls'][key]={'actor':actor,'method':method,'path':path,'body':body,'expected':expected};self.save()
        value=self.clients[actor].call(method,path,body=body,raw=raw,headers=headers,expected=expected)
        self.state['calls'][key]['result']=value;self.save();return value
    def key(self,suffix):return self.state['run_id']+':'+self.active_step['step_id']+':'+suffix
    def team(self,s):return self.state['teams'][s['team']]['id']
    def thread(self,s):return self.state['threads'][s['workspace']][-1]['id']
    def observed(self,s):
        client=self.clients[s['actor']];tid=self.team(s)
        value={'personal':client.call('GET','/api/contract-memory/list?'+urllib.parse.urlencode({'team_id':tid})),'team':client.call('GET','/api/contract-memory/list?'+urllib.parse.urlencode({'team_id':tid,'scope':'team'}))}
        params={'team_id':tid}
        if s.get('workspace') in self.state['threads']:params['thread_id']=self.thread(s)
        value['candidates']=client.call('GET','/api/contract-memory/candidates?'+urllib.parse.urlencode(params))
        value['core']=self.snapshot_fn(self.diagnostics(s['actor']),tid,self.users[s['actor']]['username'])
        return value
    def wait_message(self,s):
        deadline=time.monotonic()+self.config.get('step_timeout_seconds',600);client=self.clients[s['actor']]
        while time.monotonic()<deadline:
            snap=client.call('GET','/api/threads/'+self.thread(s))
            if snap.get('permissions') or snap.get('questions'):raise StopRun('原生任务等待人工权限或问题答复，脚本不自动扩大权限')
            q=snap.get('queue',{});last=next((m.get('info',{}) for m in reversed(snap.get('messages',[])) if m.get('info',{}).get('role')=='assistant'),{})
            if q.get('paused') or q.get('items') and any(x.get('status')=='failed' for x in q['items']) or last.get('error'):raise StopRun('业务消息失败：'+str(scrub(q.get('reason') or last.get('error'))))
            sent=self.state['calls'].get(s['step_id']+':send',self.state['calls'].get(s['step_id']+':outside-message',{})).get('result',{})
            if snap.get('status',{}).get('type')=='idle' and not q.get('active') and not q.get('items') and last.get('time',{}).get('completed') and snap.get('completion_id')==sent.get('id') and sent.get('id'):
                if last.get('finish') in {'length','content_filter','content-filter'}:raise StopRun('业务模型输出不完整')
                return snap
            time.sleep(self.config.get('poll_seconds',2))
        raise StopRun('消息完成超时')
    def wait_extraction(self,s,native):
        deadline=time.monotonic()+self.config.get('step_timeout_seconds',600);quiet_since=None
        while time.monotonic()<deadline:
            obs=self.observed(s);core=obs['core'];session=self.state['threads'][s['workspace']][-1]['session_id'];jobs=[j for j in core['jobs'] if j['session']==session or j['session']=='profile']
            if any(j['status']=='failed' and j['attempts']>=3 for j in jobs):raise StopRun('记忆提炼失败；保留真实后台状态，不能按无候选通过')
            raw=[r for r in core['raw'] if r['session']==session]
            fresh=any(r.get('created','')>=self.state['calls'][s['step_id']+':send']['started_at'] for r in raw)
            busy=any(j['status'] in {'pending','running'} or j['status']=='failed' and j['attempts']<3 for j in jobs)
            if fresh and not busy:
                if quiet_since is None:quiet_since=time.monotonic()
                if time.monotonic()-quiet_since>=3:
                    expected=self.config['models']['roles']['memory_extraction'];runs=core.get('llm_runs',[])
                    if not runs:raise StopRun('缺少当前团队实际模型提炼轨迹')
                    if any(r['data'].get('requested_model')!=expected['model'] or r['data'].get('provider')!=expected['provider'] for r in runs):raise StopRun('运行中 Core 的提炼模型与已审查配置不一致，请核对独立组件配置')
                    return obs
            else:quiet_since=None
            time.sleep(self.config.get('poll_seconds',2))
        raise StopRun('L0提交／提炼完成超时；回复成功不等于记忆成功')
    def pick_candidate(self,s,obs):
        selector=s['selector'];items=obs['candidates']['items'];items=[e for e in items if e['data']['kind']==selector['kind'] and selector.get('contains','') in json.dumps(e['data'],ensure_ascii=False)]
        if selector.get('source_dialogue'):
            utterance=manifest('dialogues.json')[selector['source_dialogue']];rawids={r['id'] for r in obs['core']['raw'] if r['data'].get('role')=='user' and utterance in r['data'].get('content','')};atomids={a['id'] for a in obs['core']['atoms'] if set(a['data'].get('source_ids',[]))&rawids}
            items=[e for e in items if set(e['data'].get('source_ids',[]))&atomids]
        if len(items)!=1:raise StopRun('候选必须唯一匹配实际输出，当前 '+str(len(items))+' 条；保存快照后人工核对，不预灌金标')
        return items[0]
    def do(self,s):
        self.active_step=s;client=self.clients[s['actor']];action=s['action'];result={}
        if action=='create_team':
            t=self.mutate('create','POST','/api/contract-memory/teams',body={'name':s['name']+' '+self.state['run_id'][:8]});self.state['teams'][s['team']]=t
        elif action=='assert_empty':
            result=self.observed(s)
            if result['personal']['items'] or result['team']['items'] or result['core']['atoms'] or result['core']['candidates']:raise StopRun('测试团队并非空记忆')
        elif action in {'upload_contract','attach'}:
            iid=s['input_id'];meta=next((m for m in read_json(ROOT/'00_start_here/contract_manifest.json') if m['doc_id']==iid),None)
            path=ROOT/(meta['docx_path'] if meta else self.inputs[iid]['path'])
            if path.suffix not in {'.docx','.txt'} or any(x in path.parts for x in ['05_private_gold_DO_NOT_INGEST','06_negative_controls_QUARANTINE','09_scenarios_OPERATOR_ONLY']):raise StopRun('禁止上传评测索引、金标或隔离负例')
            headers={'X-Filename':urllib.parse.quote(path.name),'X-Team-Id':self.team(s)}
            if action=='upload_contract':
                value=self.mutate('upload','POST','/api/workspaces',raw=path.read_bytes(),headers=headers);self.state['spaces'][s['workspace']]=value
                thread=self.mutate('thread','POST','/api/workspaces/'+value['id']+'/threads');self.state['threads'][s['workspace']]=[thread];docid=value['document_id']
            else:
                value=self.mutate('attach','POST','/api/threads/'+self.thread(s)+'/attachments',raw=path.read_bytes(),headers=headers);docid=value.get('id') or value.get('document',{}).get('id')
                if not docid:raise StopRun('附件接口未返回可核对的原生文档 ID')
            record={'id':docid,'workspace':s['workspace'],'file':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            self.state['documents'].setdefault(iid,record);self.state['documents'][s['workspace']+':'+iid]=record
            document=client.call('GET','/api/documents/'+docid+'?thread_id='+self.thread(s))
            result={'document':document,'mapping':source_mapping(iid,document,path)}
            atomic_json(self.out/'mappings'/f'{s["step_id"]}.json',result['mapping'])
        elif action=='new_thread':
            thread=self.mutate('thread','POST','/api/workspaces/'+self.state['spaces'][s['workspace']]['id']+'/threads');self.state['threads'][s['workspace']].append(thread)
        elif action=='message':
            model=self.config['ordinary_model'] if s.get('model_role')=='ordinary' else self.config['business_model']
            obs_before=self.observed(s);key=s['step_id']+':send'
            if key not in self.state['calls']:
                from datetime import datetime,timezone
                self.state['calls'][key]={'actor':s['actor'],'method':'POST','path':'/api/threads/'+self.thread(s)+'/messages','body':{'text':s['text'],'model':model,'request_id':self.key('message')},'expected':202,'started_at':datetime.now(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00','Z')};self.save()
            self.mutate('send','POST','/api/threads/'+self.thread(s)+'/messages',body=self.state['calls'][key]['body'],expected=202,idempotent=True)
            native=self.wait_message(s);obs=self.wait_extraction(s,native) if s.get('wait_extraction',True) else self.observed(s)
            result={'before':obs_before,'after':obs,'native':native}
            if s.get('require_saved_artifact'):
                result['workspace_artifacts']=client.call('GET','/api/workspaces/'+self.state['spaces'][s['workspace']]['id']).get('artifacts',[])
            if not s.get('wait_extraction',True) and obs_before['core']['raw']!=obs['core']['raw']:raise StopRun('普通provider路径新增了合同L0')
        elif action=='snapshot':result=self.observed(s)
        elif action=='candidate_action':
            obs=self.observed(s);obs['candidates']=client.call('GET','/api/contract-memory/candidates?team_id='+self.team(s))
            candidate=self.state['candidate_baselines'].get(s['entry_alias']) or self.pick_candidate(s,obs)
            self.state['candidate_baselines'][s['entry_alias']]=candidate;self.save();atomic_json(self.out/'pending-candidate.json',candidate)
            body={'team_id':self.team(s),'id':candidate['id'],'operation_id':self.key('candidate')}
            key=s['step_id']+':candidate';existing=self.state['calls'].get(key)
            if existing:body=existing['body']
            result=self.mutate('candidate','POST','/api/contract-memory/'+s['operation'],body=body,idempotent=True)
            self.state['candidate_baselines'][s['entry_alias']]=candidate
            if s['operation']=='confirm':self.state['entries'][s['entry_alias']]=result;self.state['entry_baselines'][s['entry_alias']]=result
            if s.get('repeat'):
                again=client.call('POST','/api/contract-memory/'+s['operation'],body=body)
                if again['id']!=result['id']:raise StopRun('重复确认发布了新条目')
            result={'mutation':result,'before':obs,'after':self.observed(s)}
        elif action=='entry_action':
            alias=s['entry_alias'];entry=self.state['entries'][alias];data=dict(entry['data'])
            if s.get('content'):data['content']=s['content']
            for field in ['title','conditions','exceptions']:
                if field in s:data[field]=s[field]
            if s.get('append'):data['content']+='\n'+s['append']
            op=s['operation'];body={'team_id':self.team(s),'id':entry['id'],'version':entry['version'],'operation_id':self.key('entry')}
            if op=='update':body['data']=data
            if op=='propose':body.update(operation='share',data={**data,'content':s['publication'],'title':'交付迟延审查经验','source_ids':[],'conditions':['设备采购','核对当前合同与政策'],'exceptions':['历史个案不能自动批准新合同']})
            value=self.mutate('entry','POST','/api/contract-memory/'+op,body=body,idempotent=True)
            if op=='propose':self.state['proposals'][s['proposal_alias']]=value
            else:self.state['entries'][alias]=value
            if s.get('stale_check'):
                stale={**body,'operation_id':self.key('stale'),'version':entry['version']}
                client.call('POST','/api/contract-memory/update',body=stale,expected=409)
            result={'mutation':value,'after':self.observed(s)}
        elif action in {'add_member','remove_member'}:
            member=self.users[s['member']];result=self.mutate('membership','PUT',f'/api/contract-memory/teams/{self.team(s)}/members/{member["id"]}',body={'role':'member','active':action=='add_member'},idempotent=True)
        elif action=='review':
            prop=self.state['proposals'][s['proposal_alias']];result=self.mutate('review','POST','/api/contract-memory/review',body={'team_id':self.team(s),'id':prop['id'],'approved':s['approved'],'operation_id':self.key('review')},idempotent=True)
        elif action=='denied_review':
            prop=self.state['proposals'][s['proposal_alias']];client.call('POST','/api/contract-memory/review',body={'team_id':self.team(s),'id':prop['id'],'approved':True,'operation_id':self.key('denied-review')},expected=403);result={'member_review_denied':True,'proposal_id':prop['id']}
        elif action=='scope_check':
            tid=self.team(s);result=client.call('GET','/api/contract-memory/list?team_id='+tid,expected=s.get('expect_status',200))
            if s.get('expect_status')==403:return {'denied':True}
            if s.get('expect_private_empty') and result['items']:raise StopRun('另一个用户读取到个人条目')
            shared=client.call('GET','/api/contract-memory/list?team_id='+tid+'&scope=team')
            if s.get('expect_team_empty') and shared['items']:raise StopRun('未经审核共享已发布')
            if s.get('expect_team_published'):
                if not shared['items']:raise StopRun('批准后的团队版本不可见')
                details=[client.call('GET','/api/contract-memory/detail/'+e['id']+'?team_id='+tid) for e in shared['items']]
                if any(not source.get('restricted') for d in details for source in d.get('sources',[])):raise StopRun('私有来源泄露')
            client.call('GET','/api/workspaces/'+self.state['spaces'][s['workspace']]['id'],expected=404)
            result={'personal':result,'team':shared}
        elif action=='observe_same_sources':
            # The preceding normal application message has completed another extraction.
            result=self.observed(s)
            baseline=self.state['candidate_baselines'].get(s['entry_alias']);fingerprint=(baseline or {}).get('fingerprint')
            if fingerprint and any(c['fingerprint']==fingerprint and c['status']=='pending' for c in result['core']['candidates']):raise StopRun('已忽略的同来源候选复活')
            eid=self.state['entries'].get(s['entry_alias'],{}).get('id')
            if eid and any(e['id']==eid for e in result['personal']['items']):raise StopRun('删除条目仍在正式视图')
            result['same_source_reextraction']='normal_application_read_after_human_decision'
            result['suppression_fingerprint']=fingerprint
        elif action=='seed_quarantine':
            if 'outsider' not in self.clients:raise StopRun('跨组织负例需要独立的 outsider 配置')
            scopes=[]
            for actor in ['owner','outsider']:
                appdata=Path(self.diagnostics(actor)['app_data']).resolve()
                with sqlite3.connect((appdata/'app.sqlite').as_uri()+'?mode=ro',uri=True) as db:
                    org=db.execute('SELECT org_id FROM users WHERE id=?',(self.users[actor]['id'],)).fetchone()
                    if not org:raise StopRun('无法核验负例所属组织')
                    scopes.append((str(appdata),org[0]))
            if scopes[0]==scopes[1]:raise StopRun('负例账号与被测账号属于同一组织，拒绝摄入')
            t=self.mutate('outside-team','POST','/api/contract-memory/teams',body={'name':'外部采购团队 '+self.state['run_id'][:8]});self.state['teams']['X']=t
            path=ROOT/'06_negative_controls_QUARANTINE/外部软件采购审批记录.txt'
            w=self.mutate('outside-upload','POST','/api/workspaces',raw=path.read_bytes(),headers={'X-Team-Id':t['id'],'X-Filename':urllib.parse.quote(path.name)})
            self.state['spaces']['NEGATIVE']=w;thread=self.mutate('outside-thread','POST','/api/workspaces/'+w['id']+'/threads');self.state['threads']['NEGATIVE']=[thread]
            self.mutate('outside-message','POST','/api/threads/'+thread['id']+'/messages',body={'text':'请实际读取审批记录，说明本项目的预付款安排和适用范围。','model':self.config['accounts']['outsider'].get('business_model',self.config['business_model']),'request_id':self.key('outside')},expected=202,idempotent=True)
            native=self.wait_message(s)
            # Use the same observable pipeline wait with the stored send timestamp.
            from datetime import datetime,timezone
            k=s['step_id']+':send'
            if k not in self.state['calls']:self.state['calls'][k]={'started_at':'1970-01-01T00:00:00.000Z'}
            obs=self.wait_extraction(s,native);candidate=self.state['candidate_baselines'].get('outside') or self.pick_candidate({**s,'selector':{'kind':'experience','contains':'90%'}},obs)
            self.state['candidate_baselines']['outside']=candidate;self.save()
            entry=self.mutate('outside-confirm','POST','/api/contract-memory/confirm',body={'team_id':t['id'],'id':candidate['id'],'operation_id':self.key('outside-confirm')},idempotent=True)
            self.state['entries']['outside']=entry
            result={'outside_scope_verified':True,'scope_pair':scopes,'outside_entry_id':entry['id'],'native':native,'after':self.observed(s)}
        elif action in {'operator_checkpoint','fault_checkpoint'}:
            ev=self.config.get('operator_evidence',{}).get(s['step_id'])
            if not ev:raise StopRun('此真实机制检查需要操作员证据，当前暂停：'+s['instruction'])
            evidence=read_json(ev)
            if evidence.get('run_id')!=self.state['run_id'] or evidence.get('step_id')!=s['step_id'] or not evidence.get('artifact_paths'):raise StopRun('操作员证据不属于此运行或缺少原始证据文件')
            if any(not Path(p).is_file() for p in evidence['artifact_paths']):raise StopRun('操作员证据文件不存在')
            result={'operator_evidence':evidence,'after':self.observed(s)}
        else:raise StopRun('未支持步骤 '+action)
        return result
    def run(self,steps):
        if self.state['pack_sha']!=pack_digest():raise StopRun('测试包已变动，不能继续旧运行')
        for s in steps:
            if s['step_id'] in self.state['completed']:continue
            try:
                result=self.do(s);checks=deterministic_checks(s,result,self.state)
                self.verify_reads(result)
                atomic_json(self.out/'steps'/(s['step_id']+'.json'),{'step':s,'result':scrub(result),'deterministic_checks':checks})
                self.state['completed'].append(s['step_id']);self.state.pop('blocked',None);self.save();print(s['step_id']+' completed')
            except Exception as e:
                self.state['blocked']={'step_id':s['step_id'],'error':str(e)};self.save()
                try:atomic_json(self.out/'blocked-observation.json',scrub(self.observed(s)))
                except Exception:pass
                raise
    def verify_reads(self,result):
        native=result.get('native',{});outputs=[]
        for m in native.get('messages',[]):
            for part in m.get('parts',[]):
                if part.get('type')=='tool' and part.get('tool')=='read' and part.get('state',{}).get('status')=='completed':outputs.append(part['state'].get('output',''))
        for p in (self.out/'mappings').glob('*.json') if (self.out/'mappings').exists() else []:
            mappings=read_json(p)
            for row in mappings:
                doc=row['runtime_document_id'];blocks=row['runtime_block_ids']
                if blocks and any(all(('【D'+doc+':'+b+'】') in o for b in blocks) for o in outputs):row['native_read_verified']=True
            atomic_json(p,mappings)

def deterministic_checks(step,result,state):
    """State/provenance checks only. Free-text semantic applicability goes to the judge."""
    checks=[]
    def add(name,ok,detail=''):checks.append({'check':name,'status':'pass' if ok else 'fail','detail':detail})
    action=step['action'];obs=result.get('after') or result
    if action=='upload_contract':
        w=state['spaces'][step['workspace']];others=[x['id'] for k,x in state['spaces'].items() if k!=step['workspace']]
        add('new_workspace_id',w['id'] not in others)
    if action in {'upload_contract','attach'}:
        add('source_mapping_complete',bool(result.get('mapping')) and all(x['mapping_status']=='matched' for x in result['mapping']))
    if action=='message' and result.get('after'):
        core=result['after']['core'];ids={r['id'] for r in core['raw']};atoms={a['id']:a for a in core['atoms']};entryids={e['id'] for e in core['entries']}
        add('L1_sources_exist',all(set(a['data'].get('source_ids',[]))<=ids for a in atoms.values()))
        add('L1_no_approved_enum',all(a['data'].get('business_state') in {'proposed','confirmed'} for a in atoms.values()))
        add('candidate_sources_exist',all(set(c['data'].get('source_ids',[]))<=set(atoms)|entryids for c in core['candidates']))
        formal={e['id'] for e in result['after']['personal']['items']}|{e['id'] for e in result['after']['team']['items']}
        add('draft_ids_not_formal',not formal & {c['id'] for c in core['candidates'] if c['status']=='pending'})
        outsider=state.get('entries',{}).get('outside',{}).get('id')
        if outsider and step['actor']!='outsider':add('no_cross_org_entry_in_answer_or_tools',outsider not in json.dumps(result.get('native',{}),ensure_ascii=False))
        if not step.get('wait_extraction',True):add('ordinary_no_new_L0',result['before']['core']['raw']==core['raw'])
        if step.get('require_saved_artifact'):
            add('saved_artifact_exists',bool(result.get('workspace_artifacts')))
            add('actual_tool_save_receipt',any(r['data'].get('role')=='tool' and re.search(r'"saved"\s*:\s*true',r['data'].get('content','')) for r in core['raw']))
        if 'RUN-AUX' in step.get('case_ids',[]):checks.append({'check':'auxiliary_request_was_observed','status':'needs_review','detail':'需人工核对实际标题／压缩请求及脱敏路由证据，单凭L0无相关文本不能判通过'})
    if action=='candidate_action':
        e=result['mutation']
        if step['operation']=='confirm':add('confirmed_entry_visible',any(x['id']==e['id'] for x in obs['personal']['items']))
        else:add('ignored_candidate_not_pending',not any(x['id']==state['candidate_baselines'][step['entry_alias']]['id'] for x in obs['candidates']['items']))
    if action=='entry_action':
        e=result['mutation'];old=state['entry_baselines'].get(step['entry_alias'])
        if step['operation']=='update' and old:add('version_increased',e['version']>old['version'])
        if step['operation']=='delete':add('deleted_entry_absent',not any(x['id']==e['id'] for x in obs['personal']['items']))
    if action=='observe_same_sources':
        fingerprint=result.get('suppression_fingerprint');add('same_source_tombstone',bool(fingerprint) and any(t['fingerprint']==fingerprint for t in result['core']['tombstones']));add('same_source_not_pending',not any(c['status']=='pending' and c['fingerprint']==fingerprint for c in result['core']['candidates']))
    if action=='snapshot' and 'L1-READ' in step['case_ids']:
        docid=state['documents']['H01']['id'];add('upload_does_not_read',not any(r['data'].get('role')=='tool' and docid in r['data'].get('tool_path','') for r in obs['core']['raw']))
    return checks

def report(out):
    out=Path(out);state=read_json(out/'checkpoint.json');cases=manifest('cases.json');completed=set(state['completed']);judged={}
    if (out/'judge.json').exists():judged={x['case_id']:x for x in read_json(out/'judge.json')['output']['results']}
    rows=[]
    for c in cases:
        done=all(s in completed for s in c['step_ids']);j=judged.get(c['case_id'])
        checks=[x for sid in c['step_ids'] if (out/'steps'/(sid+'.json')).exists() for x in read_json(out/'steps'/(sid+'.json')).get('deterministic_checks',[])]
        failed=any(x['status']=='fail' for x in checks);pending=any(x['status']=='needs_review' for x in checks)
        status='fail' if failed or j and j.get('critical_failures') else 'needs_review' if pending else j['verdict'] if done and j else 'not_judged' if done else 'not_executed'
        rows.append({'case_id':c['case_id'],'layers':c['layers'],'executed':done,'status':status,'deterministic_checks':checks,'judge_verdict':j['verdict'] if j else None,'critical_failures':j.get('critical_failures',[]) if j else []})
    result={'run_id':state['run_id'],'pack_sha':state['pack_sha'],'steps_completed':len(completed),'steps_total':len(manifest('steps.json')),'blocked':state.get('blocked'),'model_scores_are_assistance':True,'cases':rows,'status':'requires_review' if any(r['status']!='pass' for r in rows) else 'model_assessed_pass_pending_human_review'}
    atomic_json(out/'report.json',result);(out/'report.md').write_text('# 合同记忆运行报告\n\n'+json.dumps({k:v for k,v in result.items() if k!='cases'},ensure_ascii=False,indent=2)+'\n\n|用例|层级|状态|\n|---|---|---|\n'+'\n'.join(f"|{r['case_id']}|{'/'.join(r['layers'])}|{r['status']}|" for r in rows)+'\n')
    return result
def judge(config,out,execute,reviewed):
    require_review(execute,reviewed);out=Path(out);state=read_json(out/'checkpoint.json')
    if state['pack_sha']!=pack_digest():raise StopRun('实际运行不属于当前审查包')
    scores=[];metas=[]
    # Each case has independent context. Judge alone receives its rubric; never a business write.
    for case in manifest('cases.json'):
        if not all(s in state['completed'] for s in case['step_ids']):continue
        evidence=[compact_evidence(read_json(out/'steps'/(sid+'.json'))) for sid in case['step_ids']]
        request={'role':'judge','model':config['models']['roles']['judge']['model'],'stage':'judge','request_id':state['run_id']+':judge:'+case['case_id'],'prompt':'你是合同记忆功能评测者，仅评估给定证据。结构状态和真实工具记录优先于助手自述；禁止将关键词命中当语义正确。证据不足返回needs_review。每项必须引用source_id及原文片段，关键失败单列。输出指定JSON。','input':{'case':case,'evidence':evidence}}
        cached=out/'judge-cases'/(case['case_id']+'.json')
        inputsha=hashlib.sha256(json.dumps({'request':request,'model_config':config['models']['roles']['judge']},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if cached.exists():
            r=read_json(cached)
            if r.get('input_sha')!=inputsha:raise StopRun('judge缓存不属于当前冻结证据或模型配置')
        else:r=complete(config['models'],request,execute=True);r['input_sha']=inputsha;atomic_json(cached,r)
        items=r['output']['results']
        if len(items)!=1 or items[0]['case_id']!=case['case_id']:raise StopRun('judge returned mismatched case')
        sources={}
        def collect(v):
            if isinstance(v,str):return [v]
            elif isinstance(v,dict):
                fragments=[s for x in v.values() for s in collect(x)]
                if isinstance(v.get('id'),str):sources[v['id']]=fragments
                return fragments
            elif isinstance(v,list):
                return [s for x in v for s in collect(x)]
            return []
        for ev in evidence:sources[ev['step']['step_id']]=collect(ev['result'])
        if not items[0]['evidence'] or any(len(e['quote'].strip())<4 or not any(e['quote'] in x for x in sources.get(e['source_id'],[])) for e in items[0]['evidence']):raise StopRun('judge引用与指定原生来源不匹配')
        scores+=items;metas.append(r['metadata'])
    result={'output':{'results':scores},'metadata':metas,'same_configured_model':config['models']['roles']['judge']['model']==config['models']['roles']['memory_extraction']['model']}
    atomic_json(out/'judge.json',result);return result
def compact_evidence(ev):
    """Keep full local evidence; give the judge latest-turn tools plus real layer state, without repeated document hashes/context."""
    def compact(v):
        if isinstance(v,list):return [compact(x) for x in v]
        if isinstance(v,dict):
            return {k:compact(x) for k,x in v.items() if k not in {'evidence_context','llm_runs','extraction_runs','documents','skills','todos','locations','outline','fingerprint','tombstones','audit'}}
        return v
    value=compact(ev);result=value.get('result',{})
    if 'native' in result:
        messages=result['native'].get('messages',[]);start=max((i for i,m in enumerate(messages) if m.get('info',{}).get('role')=='user'),default=0)
        result['native']['messages']=messages[start:]
    # L0 is provenance, not another copy of every earlier dialogue. Keep only source records referenced by L1.
    for key in ['before','after']:
        core=result.get(key,{}).get('core',{});refs={sid for a in core.get('atoms',[]) for sid in a['data'].get('source_ids',[])}
        if 'raw' in core:core['raw']=[r for r in core['raw'] if r['id'] in refs]
    return value
def probe_models(config,out):
    out=Path(out);path=out/'preflight-models.json'
    results=read_json(path) if path.exists() else {}
    for role,stage in [('memory_extraction','l1'),('judge','judge')]:
        if role in results:
            expected=config['models']['roles'][role]
            if results[role]['requested_model']!=expected['model'] or results[role]['provider']!=expected['provider']:raise StopRun('模型连通性检查不属于当前配置')
            continue
        request={'role':role,'model':config['models']['roles'][role]['model'],'stage':stage,'request_id':'preflight-'+uuid.uuid4().hex,'prompt':'本次仅做已获授权的结构化连通性检查，不读文件不调用工具。输出 '+('{"records":[]}' if stage=='l1' else '{"results":[]}'),'input':{}}
        results[role]=complete(config['models'],request,execute=True)['metadata']
        atomic_json(path,results)
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['plan','run','resume','judge','report']);p.add_argument('--config',type=Path);p.add_argument('--out',type=Path);p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');a=p.parse_args()
    if a.action=='plan':print(json.dumps({'status':'offline_plan','pack_sha':pack_digest(),'cases':len(manifest('cases.json')),'steps':manifest('steps.json')},ensure_ascii=False,indent=2));return
    if not a.out:p.error('--out required')
    if a.action=='report':print(json.dumps(report(a.out),ensure_ascii=False));return
    require_review(a.execute,a.reviewed_pack_sha)
    if not a.config:p.error('--config required')
    config=read_json(a.config)
    if a.action=='judge':judge(config,a.out,a.execute,a.reviewed_pack_sha);return
    required={s['actor'] for s in manifest('steps.json')}|{'member'}
    if required-set(config['accounts']):raise StopRun('完整运行缺少账号配置：'+','.join(sorted(required-set(config['accounts']))))
    if a.action=='run' and a.out.exists() and any(a.out.iterdir()):raise StopRun('run 输出目录必须为空；已有运行请 resume')
    state=read_json(a.out/'checkpoint.json') if a.action=='resume' and (a.out/'checkpoint.json').exists() else None
    runner=Runner(config,a.out,state)
    for actor in ['owner','outsider']:
        if not runner.users[actor].get('capabilities',{}).get('admin'):raise StopRun(actor+' 需要测试组织管理员账号')
        runner.clients[actor].call('GET','/health')
        catalog=runner.clients[actor].call('GET','/api/models');ids={m['id'] for m in catalog['models']}
        expected=config['accounts'][actor].get('business_model',config['business_model'])
        if expected not in ids or actor=='owner' and config['ordinary_model'] not in ids:raise StopRun(actor+' 的应用模型 ID 未配置，请核对 /api/models')
    runner.save()
    probe_models(config,a.out)
    runner.run(manifest('steps.json'))
if __name__=='__main__':
    try:main()
    except (StopRun,RuntimeError,ModelError) as e:raise SystemExit(str(e))
