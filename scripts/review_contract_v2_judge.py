"""Additive re-evaluation with JSON-pointer provenance and exact leaf-text citations."""
import argparse,hashlib,json,sys,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'openharvey_contract_memory_pack/07_tools'))
from structured_model import complete
from suite_common import atomic_json,require_review
from run_suite import scrub

def leaves(value,pointer=''):
    if value==[] or value=={}:
        yield pointer,json.dumps(value);return
    if isinstance(value,dict):
        for key,v in value.items():yield from leaves(v,pointer+'/'+key.replace('~','~0').replace('/','~1'))
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from leaves(v,pointer+'/'+str(i))
    elif value is not None:
        yield pointer,value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)

def citations_valid(result,sources):
    # Status codes, versions and empty lists are valid complete scalar evidence.
    # A short quote must equal the entire leaf; never accept a one-character
    # fragment of a longer value merely because it appears somewhere in it.
    return bool(result.get('evidence')) and all(e['source_id'] in sources and bool(e['quote'].strip()) and e['quote'] in sources[e['source_id']]['text'] and (len(e['quote'].strip())>=4 or e['quote']==sources[e['source_id']]['text']) for e in result['evidence'])

def main():
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');p.add_argument('--reviewed-pack-sha');p.add_argument('--config',type=Path,required=True);p.add_argument('--root',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--case');p.add_argument('--post-fix',action='store_true');a=p.parse_args();require_review(a.execute,a.reviewed_pack_sha);cfg=json.loads(a.config.read_text());sources={};filehashes={}
    def add_file(rel,filter_fn=None):
        path=a.root/rel;raw=path.read_bytes();value=json.loads(raw);filehashes[rel]=hashlib.sha256(raw).hexdigest()
        native=value.get('result',{}).get('native',{}).get('messages',[]) if isinstance(value,dict) else []
        last_user=max((i for i,msg in enumerate(native) if msg.get('info',{}).get('role')=='user'),default=0)
        for pointer,text in leaves(scrub(value)):
            if filter_fn and not filter_fn(pointer,text):continue
            if '/result/native/messages/' in pointer:
                index=int(pointer.split('/result/native/messages/')[1].split('/')[0])
                if index<last_user:continue
            if not text.strip():continue
            sid='ev_'+hashlib.sha256((rel+pointer).encode()).hexdigest()[:16]
            sources[sid]={'file':rel,'pointer':pointer,'file_sha256':filehashes[rel],'text':text}
    def focused(pointer,text):
        if pointer.startswith('/result/before/'):return False
        if any(x in pointer for x in ['llm_runs','extraction_runs','/raw/','/jobs/','/atoms/','locations','skills','outline','/documents/','/metadata/','/context/','/review_events/','/review_cases/','/preference_statements/']):return False
        if '/native/' in pointer:return pointer.endswith(('/text','/command','/output','/sessionID','/agent','/id','/role'))
        if '/after/' in pointer:
            if not any('/core/'+k+'/' in pointer for k in ['entries','revisions','audit','tombstones','candidates']):return False
        if pointer.endswith(('/created','/updated','/instance','/team','/agent','/user','/task','/session','/prompt_version','/job','/model','/target_id')):return False
        return True
    groups={}
    files_by_case={
        'V2-PREFERENCE':['core-03-audit/steps/V2-S0'+str(i)+'.json' for i in range(12,17)]+['preferences-02/steps/PREF-0'+str(i)+'.json' for i in [4,5,6,7,8]]+['preferences-02/steps/PREF-'+str(i)+'.json' for i in [11,12,13,14]]+['preference-source-01/steps/PREF-SOURCE-01.json'],
        'V2-BOUNDARY':['access-02.json','scope-extra.json','team-admin-private-source.json','closeout-01/boundary-raw.json'],
        'V2-PROTECTION':['core-03-audit/steps/V2-S0'+str(i)+'.json' for i in range(22,26)]+['preferences-02/steps/PREF-'+str(i)+'.json' for i in [10,11,13,14]]+['access-02.json'],
    }
    if a.post_fix:
        base='closeout-01/protection-01/'
        files_by_case={
          'V2-PREFERENCE':[base+'steps/PROTECT-'+str(i).zfill(2)+'.json' for i in [3,4,5,8,9,10,11,12]],
          'V2-PROTECTION':[base+'steps/PROTECT-'+str(i).zfill(2)+'.json' for i in [7,8,9,12,13,15,16]]+[base+'api-receipts.json',base+'post-checks.json','closeout-01/protection-replay/same-source-proof.json'],
        }
    for case,files in files_by_case.items():
        before=set(sources)
        for rel in files:add_file(rel,focused if '/steps/' in rel else None)
        # Shared files must be present in every case input, not only their first occurrence.
        groups[case]={sid:v for sid,v in sources.items() if v['file'] in files}
    originals=json.loads((ROOT/'docs/evidence/contract-memory-v2-live/judge-original-summary.json').read_text())
    cases=json.loads((ROOT/'openharvey_contract_memory_pack/09_scenarios_OPERATOR_ONLY/v2_cases.json').read_text());clarifications={
        'V2-PREFERENCE':'正文是正式L3条目的data.content，不能包含确认流程说明。助手回复可以解释确认流程，不能据此判正文污染。称呼无须每个答复机械重复；新会话询问已确认约定时必须实际取用最新称呼和结构。两类偏好分别存储，不进入L2。',
        'V2-BOUNDARY':'产品范围固定为每Team一个合同Agent。核验跨Team、个人User隔离、撤销成员和伪造/跨Team Agent标识。不得要求一个Team内多个合同Agent的产品形态。已有旧接口限制仍要求通过。',
        'V2-PROTECTION':'不得降低人工修改不覆盖、409、删除退出召回、历史版本保留、重复确认/修改幂等、忽略/删除同来源不反复生成的业务断言。审计/删除标记和真实后续提炼都可作为证据。只引用本case提供的原始叶子值；它们可能是独立短值而非拼接JSON。'}
    freeze={'files':filehashes,'sources':sources,'criteria_clarifications':clarifications,'requested_model':cfg['models']['roles']['judge']['model'],'original_summary_sha256':hashlib.sha256(json.dumps(originals,sort_keys=True).encode()).hexdigest()}
    freeze_sha=hashlib.sha256(json.dumps(freeze,sort_keys=True,ensure_ascii=False).encode()).hexdigest();frozen=a.out/'frozen-sources.json'
    if frozen.exists():assert json.loads(frozen.read_text())==freeze,'Frozen evidence changed'
    else:atomic_json(frozen,freeze)
    results=[]
    for case in cases:
        cid=case['case_id']
        if cid not in groups:continue
        if a.case and a.case!=cid:continue
        dest=a.out/(cid+'.json')
        if dest.exists() and json.loads(dest.read_text()).get('result'):results.append(json.loads(dest.read_text()));continue
        record={'case_id':cid,'freeze_sha':freeze_sha,'original_preserved':True,'clarification':clarifications[cid],'attempts':[]}
        for attempt in range(3):
            model_sources={sid:{'path':v['file']+':'+v['pointer'],'text':v['text']} for sid,v in groups[cid].items()}
            req={'role':'judge','stage':'judge','model':cfg['models']['roles']['judge']['model'],'request_id':freeze_sha[:20]+':'+cid+':'+str(attempt),'prompt':'评估冻结真实证据。仅输出指定case_id一个结果。不要调用工具。原结果不会被覆盖。使用业务断言及澄清，逐项判断系统缺陷、评分规则错误、证据不足；在reason说明类别。引用source_id必须为sources键，quote必须从对应text逐字复制连续片段，不能自行拼接JSON字段、改写标点或用省略号。证据不足needs_review，真实违反断言fail，无缺口才pass。'+('这是修复后独立团队的当前行为验收，不抹去此前真实失败。当前证据中仍违反断言时必须fail，不得因修复声明判通过。' if a.post_fix else '')+('上次引用未逐字匹配，请重新选择text原样片段；完整短值如409、2和[]也可引用，不能只取较长内容中的短字。' if attempt else ''),'input':{'case':case,'clarification':clarifications[cid],'sources':model_sources}}
            def traced(args,**kw):
                z=subprocess.run(args,**kw)
                if z.returncode:atomic_json(a.out/(cid+'-cli-failure-'+str(attempt)+'.json'),{'returncode':z.returncode,'stdout':scrub(z.stdout),'stderr':scrub(z.stderr)})
                return z
            try:raw=complete(cfg['models'],req,execute=True,run=traced)
            except Exception as e:
                record['attempts'].append({'error':str(e),'input_bytes':len(json.dumps(req,ensure_ascii=False).encode())});atomic_json(dest,record);raise
            items=raw['output']['results'];valid=len(items)==1 and items[0]['case_id']==cid and citations_valid(items[0],groups[cid]);record['attempts'].append({'raw':raw,'citations_valid':valid});atomic_json(dest,record)
            if valid:record['result']=items[0];break
        if 'result' not in record:record['result']={'case_id':cid,'verdict':'needs_review','reason':'Evidence citation validation failed','critical_failures':['No valid exact-source citations'],'evidence':[]}
        atomic_json(dest,record);results.append(record);print(cid,record['result']['verdict'],flush=True)
    atomic_json(a.out/'summary.json',{'status':'completed','original_preserved':True,'freeze_sha':freeze_sha,'requested_model':cfg['models']['roles']['judge']['model'],'same_configured_model':True,'results':results})
if __name__=='__main__':main()
