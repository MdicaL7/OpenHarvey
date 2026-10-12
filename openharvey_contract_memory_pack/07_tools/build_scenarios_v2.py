#!/usr/bin/env python3
"""One ordered source of truth for both API replay and human testing."""
import json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def readj(p):return json.loads((ROOT/p).read_text())
def readl(p):return [json.loads(l) for l in (ROOT/p).read_text().splitlines() if l]
def write(p,data): (ROOT/p).write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')

def main():
    locations=readj('09_scenarios_OPERATOR_ONLY/source_locations.json');contracts=readj('00_start_here/contract_manifest.json');inputs=readj('00_start_here/input_manifest_OPERATOR_ONLY.json')
    imap={x['input_id']:x for x in inputs};queries={q['query_id']:q for q in readl('04_queries/queries.jsonl')};gold={q['query_id']:q for q in readl('05_private_gold_DO_NOT_INGEST/recall_gold.jsonl')}
    steps=[];cases=[]
    categories={
      'facts':('L1 事实准确性',['L1']), 'nature':('L1 信息性质',['L1']), 'evidence':('L1 证据与状态',['L1']),
      'experience':('L2 经验沉淀',['L2']), 'applicability':('L2 跨合同适用',['L2']), 'preference':('L3 用户偏好',['L3']),
      'principle':('L3 原则形成',['L3']), 'confirmation':('候选与正式记忆',['L1','L2','L3']),
      'conflict':('更新与冲突',['L1','L2','L3']), 'protection':('人工保护',['L2','L3']),
      'scope':('作用范围',['L1','L2','L3']), 'reliability':('可靠性',['L0','L1','L2','L3'])}
    def case(cid,category,title,refs,expected,forbidden,polarity='positive',assertions=None,query_id=None):
        data={'case_id':cid,'category':category,'title':title,'polarity':polarity,'layers':categories[category][1],'source_anchors':refs,'expected':expected,'forbidden':forbidden,'evidence_requirements':['真实操作结果与原始回答','分层状态快照','来源链或工具调用轨迹'],'assertions':assertions or [],'query_id':query_id,'step_ids':[]};cases.append(data);return cid
    def step(action,workspace=None,case_ids=None,**kw):
        s={'step_id':f'S{len(steps)+1:03d}','action':action,'workspace':workspace,'actor':'owner','team':'A','case_ids':case_ids or [],**kw};steps.append(s)
        for cid in s['case_ids']:next(c for c in cases if c['case_id']==cid)['step_ids'].append(s['step_id'])
        return s
    def message(w,text,ids=None,**kw):return step('message',w,ids,text=text,**kw)
    def ask(qid,w,ids=None,**kw):return message(w,queries[qid]['prompt'],[qid]+(ids or []),query_id=qid,as_of=queries[qid]['as_of'],**kw)
    for qid,q in queries.items():
        category={'Q02':'facts','Q05':'evidence','Q06':'evidence','Q08':'conflict','Q09':'conflict','Q11':'preference','Q12':'nature','Q14':'scope','Q15':'facts','Q16':'evidence','Q17':'evidence','Q18':'conflict','Q19':'nature','Q20':'scope','Q21':'confirmation','Q22':'conflict','Q23':'facts'}.get(qid,'applicability')
        g=gold[qid];case(qid,category,q['prompt'],g['expected_evidence'],g['reasoning_requirements'],'；'.join(g['critical_failure_conditions']) or '不得把本次建议或不适用经验作为正式批准',polarity='negative' if qid in {'Q03','Q04','Q07','Q09','Q10','Q11','Q12','Q13','Q14','Q15','Q16','Q17','Q19','Q20','Q21'} else 'positive',query_id=qid)
    case('L1-READ','evidence','上传和实际读取的区别',['H01-C05'],'上传后无该文档 L0 工具内容；实际 read 后有 L0，L1 引用版本和段落可核验','上传元数据被冒充合同全文','negative',[{'check':'no_tool_read_before_message'}])
    case('L1-NATURE','nature','用户意见、助手建议和执行结果',['H01-C05','DIALOGUE-E01'],'我的一次性意见保留三项限制，助手建议与真实保存回执分别归类','无审批证据时标记正式批准，生成建议稿被标记执行完成','positive')
    case('L1-VERSION','evidence','新旧文档引用版本',['F01-C06','F01-R2-C06'],'旧稿0.03%与修订稿0.05%分别有原生文档及来源，新结论引用修订稿','使用旧段落支持新值或抹除旧历史','positive')
    case('L1-EXECUTION','nature','建议稿与成果保存回执',['DIALOGUE-REPORT-DRAFT','DIALOGUE-REPORT-SAVE'],'先生成未保存建议稿，再取得实际工具回执和应用成果记录；L1执行结果须来自真实工具','助手说已保存被当作真实执行结果','negative')
    case('L2-PUBLISH','experience','经验候选到正式经验',['H01-C06','APPROVAL-H01-D1'],'按交付迟延风险主题形成候选，确认后正式发布，条件与除外责任完整','每合同永久专题或统一企业底线','positive')
    case('CONFIRM-PUBLISHED','confirmation','确认后正式召回',['APPROVAL-H01-D1'],'确认后正式个人经验可读，复用源于实际条目','仅助手口头说已记住但正式条目缺失','positive')
    case('L2-UNRELATED','experience','无关案例不构成经验依据',['H06-C06','F03-C06'],'会务取消费不作为软件责任上限的经验依据','仅凭相近比例形成跨主题经验','negative')
    case('L2-DRAFT','confirmation','未确认经验不进入正式视图',['H03-C05','APPROVAL-H03-D1'],'L1可能查询，经验候选存在，正式经验中无该候选；新会话不把草稿当正式经验','把草稿当正式经验','negative',[{'check':'draft_not_published'}])
    case('L2-ROLE','applicability','同数字、不同义务与受益方',['H01-C06','H02-C06','F02-C06'],'同一数值不导致机械套用，交付和付款责任、采购与销售角色分别判断','只按对手名称和30%数值适用','negative')
    case('L3-LONG','preference','明确长期报告偏好',['DIALOGUE-P01'],'先形成L1偏好及L3候选，确认后在新会话和另一份历史合同中使用“合同决策卡”标题及风险、依据、建议顺序；需正式条目及实际召回／注入证据','只凭默认报告格式或助手自述认定L3生效','positive')
    case('L3-TEMP','preference','一次性格式要求',['DIALOGUE-P02'],'本轮三句话表达不替代长期偏好，下轮恢复原顺序','临时要求覆盖长期偏好','negative')
    case('L3-UPDATE','conflict','长期偏好更新',['DIALOGUE-P03'],'新偏好形成候选和冲突提示；人工更新正式版本后使用新顺序，旧版本可追溯','静默覆盖旧版本或忽略有效的新偏好','positive',[{'check':'version_increased','entry_alias':'style'}])
    case('L3-WITHDRAW','conflict','撤回个人偏好',['DIALOGUE-P04'],'撤回原子记录可观察；人工删除后不再注入，旧历史仍保留','仅口头撤回就假报数据库已删除','negative',[{'check':'entry_absent','entry_alias':'style'}])
    case('L3-PRINCIPLE','principle','确认经验后形成证据原则',['APPROVAL-H01-D1'],'确认经验可触发L3候选，原则保持核对角色和条件，仍需确认','经验确认后原则自动正式生效','positive')
    case('L3-NO-GENERALIZE','principle','一次性例外不形成公司规则',['DIALOGUE-E01','H03-C05'],'例外保留为具体案例，不形成全部合同接受60天或60%预付的原则','把60天账期与60%预付混为一谈或泛化','negative')
    case('L2-UPDATE','conflict','撤回后的旧经验与人工更新',['APPROVAL-H04-D1','WITHDRAWAL-H04-W1'],'先观察冲突，人工更新后版本变化并保留来源；回答判断与已落盘状态分别报告','看到新消息即宣称旧L2已自动更改','positive',[{'check':'version_increased','entry_alias':'data-experience'}])
    case('CONFLICT-CONDITIONS','conflict','不同条件不是互相覆盖',['H01-C06','H02-C06'],'主题和角色不同的记录独立保留','相同数字导致互相替代','negative')
    for cid,title,expected,forbidden in [
      ('PROTECT-EDIT','人工修改保护','后续提炼保留用户修订的正式文本与版本','后台覆盖人工版本'),
      ('PROTECT-IGNORE','忽略相同来源','忽略后原来源的候选不重复提示','刷新或重试后同候选复活'),
      ('PROTECT-DELETE','删除与历史保留','正式召回立即移除，L0/L1历史保留','删除经验导致原合同丢失或正式条目仍被召回'),
      ('PROTECT-IDEMPOTENT','重复确认幂等','相同operation_id得到同一条目','同一操作发布两条记忆'),
      ('PROTECT-STALE','并发编辑','旧版本编辑返回409，新版本保持不变','旧版本覆盖新版本')]:
        case(cid,'protection',title,['APPROVAL-H01-D1'],expected,forbidden,'negative' if cid.endswith(('IGNORE','DELETE','STALE')) else 'positive')
    for cid,title,expected,forbidden in [
      ('SCOPE-THREAD','同合同新会话','Task相同、Conversation不同，经验与偏好可用','会话串联或无法续用'),
      ('SCOPE-TASK','不同合同空间','Task不同，历史经验不是当前合同事实','把历史金额和原文当当前条款'),
      ('SCOPE-TEAM','同用户不同团队','新团队个人和团队正式记忆均为空','跨团队自动继承个人偏好'),
      ('SCOPE-USER','同团队不同用户','同事看不到我的个人记忆和合同','管理员或成员越权读取个人内容'),
      ('SCOPE-SHARE','审核前后团队范围','提交前后待审核均不发布，批准后团队摘要可见，原合同受限','共享自动开放原合同'),
      ('SCOPE-REVOKE','退出团队','移除成员后应用访问立即403','成员退出后仍能查看或发布')]:case(cid,'scope',title,['H01-C01'],expected,forbidden,'negative' if cid.endswith(('TEAM','USER','REVOKE')) else 'positive')
    for cid,title,expected,forbidden in [
      ('RUN-ASYNC','异步状态','消息完成与提炼完成分别等待并记录','回复成功等于记忆成功'),
      ('RUN-RESUME','中断恢复','保持run/step/request/operation ID，不重复执行已完成步骤','恢复重复上传或发布'),
      ('RUN-FAIL','模型或服务失败','失败/超时可见，无后台切换模型或伪造成功','失败被报告为没有候选而通过'),
      ('RUN-RESTART','重启持久化','重启后映射、正式条目、版本和续聊保留','只检查健康就宣布记忆保留'),
      ('RUN-ORDINARY','普通provider','普通provider对话不新增业务记忆','普通对话也进入合同记忆'),
      ('RUN-AUX','辅助请求','标题/压缩没有污染业务L0','把辅助提示当用户长期指令')]:case(cid,'reliability',title,['H01-C05'],expected,forbidden,'negative' if cid.endswith(('FAIL','ORDINARY','AUX')) else 'positive')
    step('create_team',name='合同审查团队 A')
    step('assert_empty',case_ids=['SCOPE-TEAM'])
    initial=True
    for inp in sorted([x for x in inputs if x['kind'] in {'history_contract','approval_event','policy'}],key=lambda x:(x['available_at'],x['input_id'])):
        iid=inp['input_id'];asof=inp['available_at']
        if iid=='POL-P01':continue # introduced after the first contract, before its review
        if inp['kind']=='history_contract':
            w=iid;step('upload_contract',w,['L1-READ'] if iid=='H01' else [],input_id=iid,as_of=asof)
            step('snapshot',w,['L1-READ'] if iid=='H01' else [])
            if initial:
                step('attach',w,input_id='IDENTITY-MAP');step('attach',w,input_id='POL-P01',as_of=asof);initial=False
            message(w,'本份合同以华子有限公司为我方。请实际读取本合同及当前附件，整理合同主体、我方交易角色、金额、付款前提、验收、责任和证据位置。区分原文约定与已发生事实，暂不推定审批、签署或付款。', ['RUN-ASYNC','RUN-AUX'] if iid=='H01' else [],as_of=asof)
            if iid=='H03':ask('Q19',w)
            if iid=='H02':ask('Q23',w)
        else:
            match=re.search(r'H\d{2}',iid);w=match.group(0) if match else 'H01'
            step('attach',w,input_id=iid,as_of=asof)
            message(w,'请实际读取刚上传的材料，说明它新增了什么事实、意见、决定或执行证明，以及适用条件和未被证明的事项。遇到旧记录冲突先说明，暂不宣称正式经验已改动。',as_of=asof)
            if iid=='AP-H01':
                step('candidate_action',w,['L2-PUBLISH','L3-PRINCIPLE','PROTECT-IDEMPOTENT','CONFIRM-PUBLISHED'],operation='confirm',selector={'kind':'experience','contains':'0.03%'},entry_alias='delivery',repeat=True)
            if iid=='AP-H02':step('candidate_action',w,operation='confirm',selector={'kind':'experience','contains':'0.03%'},entry_alias='payment')
            if iid=='AP-H03':
                step('new_thread',w,['L2-DRAFT']);ask('Q21',w,['L2-DRAFT']);ask('Q05',w)
                step('candidate_action',w,operation='confirm',selector={'kind':'experience','contains':'60%'},entry_alias='pilot')
            if iid=='EX-H03':ask('Q06',w)
            if iid=='AP-H04':
                step('candidate_action',w,operation='confirm',selector={'kind':'experience','contains':'训练'},entry_alias='data-experience');ask('Q08',w)
            if iid=='WD-H04':
                ask('Q09',w);ask('Q22',w)
                step('entry_action',w,['L2-UPDATE'],operation='update',entry_alias='data-experience',append='内部先例已于2026年5月15日撤回；不得据此授权新项目。原合同许可是否终止须另核对双方补充约定。')
            if iid=='POL-P02':ask('Q18',w)
    # Natural conversations are input, not attached evaluator instructions.
    dialogue={
      'DIALOGUE-E01':'这份终端合同如果谈60天账期，我这次的意见是必须有20%预付款保障，而且仅限本项目；目前没有正式审批。请区分我的意见和你的建议，不要扩大为通用规则。',
      'DIALOGUE-P01':'以后给我的合同报告，统一使用“合同决策卡”作为标题，正文先列风险，再列原文依据，最后列修改建议。引用历史经验前，也请先核对我方角色和适用条件。',
      'DIALOGUE-P02':'这一次请用三句话概括，重大风险和证据仍要保留。只针对这次回复。',
      'DIALOGUE-P03':'从今以后报告标题改为“交易风险简报”，顺序改为：先给结论，再列风险和原文依据，最后列建议。之前“合同决策卡”和“风险放在最前”的长期格式要求不再适用。',
      'DIALOGUE-P04':'我撤回之前对报告标题和顺序的长期偏好。以后根据当前任务选择格式，不要再固定“交易风险简报”和“结论在最前”。',
      'DIALOGUE-REPORT-DRAFT':'请先拟一份当前合同的风险摘要，引用原文依据并列出建议，暂时不要保存到合同成果。',
      'DIALOGUE-REPORT-SAVE':'请把刚才的风险摘要保存到当前合同成果，返回实际保存回执；如未保存成功，请明确说明。'}
    write('09_scenarios_OPERATOR_ONLY/dialogues.json',dialogue)
    message('H01',dialogue['DIALOGUE-E01'],['L1-NATURE','L3-NO-GENERALIZE'],dialogue_id='DIALOGUE-E01')
    message('H01',dialogue['DIALOGUE-REPORT-DRAFT'],['L1-EXECUTION'],dialogue_id='DIALOGUE-REPORT-DRAFT')
    message('H01',dialogue['DIALOGUE-REPORT-SAVE'],['L1-EXECUTION'],dialogue_id='DIALOGUE-REPORT-SAVE',require_saved_artifact=True)
    message('H01',dialogue['DIALOGUE-P01'],['L3-LONG'],dialogue_id='DIALOGUE-P01')
    step('candidate_action','H01',['L3-LONG'],operation='confirm',selector={'kind':'preference','contains':'合同决策卡','source_dialogue':'DIALOGUE-P01'},entry_alias='style')
    step('new_thread','H01',['SCOPE-THREAD']);message('H01','请按适合我的工作方式简要审查当前合同。',['L3-LONG','SCOPE-THREAD'])
    step('new_thread','H06',['L3-LONG','SCOPE-TASK']);message('H06','请按适合我的工作方式回顾当前会务合同的风险和依据。',['L3-LONG','SCOPE-TASK'])
    message('H01',dialogue['DIALOGUE-P02'],['L3-TEMP'],dialogue_id='DIALOGUE-P02')
    step('new_thread','H01');message('H01','请给我一份当前合同风险报告。',['L3-TEMP'])
    message('H01',dialogue['DIALOGUE-P03'],['L3-UPDATE'],dialogue_id='DIALOGUE-P03')
    step('entry_action','H01',['L3-UPDATE','PROTECT-EDIT','PROTECT-STALE'],operation='update',entry_alias='style',title='个人合同报告格式',content='以后报告标题使用“交易风险简报”，先给结论，再列风险和原文依据，最后列建议。旧“合同决策卡”和风险在前的格式不再适用。引用历史经验前核对角色和适用条件。',conditions=['本人当前团队的合同报告','长期工作格式要求'],exceptions=['不得省略重大风险或替代合同原文与有效制度'],stale_check=True)
    step('new_thread','H01');message('H01','请按我的长期工作约定生成当前合同的风险摘要。',['L3-UPDATE','PROTECT-EDIT'])
    step('create_team',name='合同审查团队 B',team='B',case_ids=['SCOPE-TEAM'])
    step('assert_empty',team='B',case_ids=['SCOPE-TEAM'])
    message('H01',dialogue['DIALOGUE-P04'],['L3-WITHDRAW'],dialogue_id='DIALOGUE-P04')
    step('entry_action','H01',['L3-WITHDRAW'],operation='delete',entry_alias='style')
    step('new_thread','H01');message('H01','请简要审查当前合同，说明当前有效的格式约定。',['L3-WITHDRAW'])
    future={'F01':['Q01','Q02','Q12','Q15','Q16'],'F02':['Q03'],'F03':['Q04','Q13','Q14','Q17','Q20'],'F04':['Q07','Q10','Q11']}
    step('seed_quarantine',case_ids=['Q14'],actor='outsider',team='X',workspace='NEGATIVE',input_id='NEG-XTENANT-01')
    for w,qs in future.items():
        step('upload_contract',w,['SCOPE-TASK'],input_id=w,as_of=imap[w]['available_at'])
        policy='POL-P03' if w=='F04' else 'POL-P02'
        step('attach',w,input_id=policy,as_of=imap[w]['available_at'])
        message(w,'本份合同以华子有限公司为我方。请实际读取这份新合同，审查主要风险。历史经验仅供参考，请说明适用条件及当前原文依据，不推定本合同已批准。',['SCOPE-TASK'])
        for qid in qs:ask(qid,w,(['L2-ROLE','CONFLICT-CONDITIONS'] if qid=='Q02' else ['L2-ROLE'] if qid=='Q03' else ['L2-UNRELATED'] if qid=='Q13' else []))
    step('upload_contract','COMBINED',input_id='F01')
    for iid in ['F02','F03','F04']:step('attach','COMBINED',input_id=iid)
    for iid in ['POL-P02','POL-P03']:step('attach','COMBINED',input_id=iid)
    ask('Q24','COMBINED')
    step('attach','F01',input_id='F01-R2',as_of=imap['F01-R2']['available_at']);message('F01','请实际读取新上传的修订稿，比较第6条交付迟延责任与原稿，当前意见以修订稿为对象，同时保留旧稿历史来源。',['L1-VERSION'],as_of=imap['F01-R2']['available_at'])
    # Protected mutation / publication checks on actual extracted entries only.
    step('entry_action','H01',['PROTECT-EDIT','PROTECT-STALE'],operation='update',entry_alias='delivery',append='使用前由经办人重新核对当前合同角色、类型和政策。',stale_check=True)
    step('add_member',case_ids=['SCOPE-USER'],member='member')
    step('scope_check','H01',['SCOPE-USER'],actor='member',expect_private_empty=True)
    step('entry_action','H01',['SCOPE-SHARE'],operation='propose',entry_alias='delivery',publication='设备采购的交付迟延安排应结合交付范围、赔偿边界和除外责任一并核对；历史个案仅供谈判参考，不代表新合同已批准。',proposal_alias='delivery-share')
    step('scope_check','H01',['SCOPE-SHARE'],actor='member',expect_team_empty=True)
    step('denied_review','H01',['SCOPE-SHARE'],actor='member',proposal_alias='delivery-share')
    step('review','H01',['SCOPE-SHARE'],proposal_alias='delivery-share',approved=True)
    step('scope_check','H01',['SCOPE-SHARE'],actor='member',expect_team_published=True)
    step('remove_member',case_ids=['SCOPE-REVOKE'],member='member')
    step('scope_check','H01',['SCOPE-REVOKE'],actor='member',expect_status=403)
    step('candidate_action','H01',['PROTECT-IGNORE'],operation='ignore',selector={'kind':'experience','contains':'60天'},entry_alias='ignored')
    message('H01','请实际重新读取原合同及已经上传的审阅决定，核对历史记录。无需提出新的交易条件或长期工作要求。',['PROTECT-IGNORE'])
    step('observe_same_sources','H01',['PROTECT-IGNORE'],entry_alias='ignored')
    step('entry_action','H01',['PROTECT-DELETE'],operation='delete',entry_alias='delivery')
    message('H01','请实际重新读取原合同的交付迟延条款和已有审阅记录，核对同一来源的历史内容。',['PROTECT-DELETE'])
    step('observe_same_sources','H01',['PROTECT-DELETE'],entry_alias='delivery')
    step('new_thread','F01',['RUN-ORDINARY']);message('F01','请回复当前合同标题即可。',['RUN-ORDINARY'],model_role='ordinary',wait_extraction=False)
    step('operator_checkpoint','H01',['RUN-RESUME'],instruction='运行至此停止脚本，再使用 resume 恢复；核对已完成步骤和操作未重复。')
    step('fault_checkpoint','H01',['RUN-FAIL'],fault='proxy_outage',instruction='仅专用隔离运行实例：停 Proxy，发送一轮请求，记录可见错误，再恢复；不自动切换模型。')
    step('fault_checkpoint','H01',['RUN-RESTART'],fault='restart',instruction='仅专用隔离实例：重启应用和记忆组件，检查ID、版本及续聊；保存前后快照。')
    for c in cases:
        if not c['step_ids']:raise ValueError('Unscheduled case '+c['case_id'])
    known={x['anchor']:x for x in locations}
    for anchor,text in dialogue.items():known[anchor]={'anchor':anchor,'input_id':anchor,'file':'09_scenarios_OPERATOR_ONLY/dialogues.json','clause_number':None,'clause_title':'自然对话步骤','text':text}
    points=[]
    for loc in known.values():
        ids=[c['case_id'] for c in cases if loc['anchor'] in c['source_anchors']]
        points.append({**loc,'coverage_role':'主测条款' if ids else '背景条款','case_ids':ids,'categories':sorted({c['category'] for c in cases if c['case_id'] in ids})})
    write('09_scenarios_OPERATOR_ONLY/cases.json',cases);write('09_scenarios_OPERATOR_ONLY/steps.json',steps);write('09_scenarios_OPERATOR_ONLY/clause_coverage.json',points)
    write('09_scenarios_OPERATOR_ONLY/categories.json',{k:{'title':v[0],'layers':v[1]} for k,v in categories.items()})
    table=['# 条款与测试要点对照表','\n仅供操作员审查，不能上传到 Agent。内部锚点通过正常条款及原生块映射，合同正文不含测试标记。','\n| 文件／对话 | 正常条款 | 用途 | 测试用例 |','| --- | --- | --- | --- |']
    for p in points:table.append(f"| {p['input_id']} · {p['file']} | {'第'+str(p['clause_number'])+'条 '+p['clause_title'] if p['clause_number'] else p['clause_title']} | {p['coverage_role']} | {', '.join(p['case_ids']) or '背景与完整性'} |")
    (ROOT/'10_manual/CLAUSE_COVERAGE.md').write_text('\n'.join(table)+'\n')
    manual=['# 人工逐步测试手册','\n先审查本手册和条款对照表，再批准固定版本。当前真实实验未执行。','\n## 准备','\n使用已绑定合同记忆的企业管理员作为 owner，另准备同企业普通 member 测试账号。每轮新建团队；不要复用既有团队的记忆。选择配置的 TencentDB Memory 业务模型。','\n浏览器进入 /spaces 和 /experience。每份合同新建空间，事件作为对应空间附件。每次上传后实际发出读取指令；等消息完成和记忆整理完成两个状态。L1 用只读快照辅助检查。','\n候选须按种类、主题与真实来源选择；若找不到或找到多条，先记录失败／待处理，不用金标手动创建来补齐。确认记忆与合同业务审批分别记录。','\n## 逐步操作']
    ui_actions={
      'create_team':'在“经验与偏好”点击“创建团队”，填写下方名称，再用“当前团队”选择它。',
      'assert_empty':'分别打开“我的内容”“团队内容”“待确认”，确认无既有条目；辅助检查只读快照的原子记录和草稿也为空。',
      'upload_contract':'在“合同空间”选择本步骤团队，点击“上传新合同”。进入新空间，创建首个对话，选择记忆模型。',
      'attach':'进入对应空间和当前对话，用附件入口添加本步材料。保留之前资料，不一次上传后续事件。',
      'message':'在当前对话发送下方原文，保存回复、原文引用和工具结果。普通模型步骤先主动切换为配置中的普通 provider。',
      'new_thread':'进入已有合同空间，点击新建对话；不要继续上一段会话，核对会话标识变化、空间及Task保持对应。',
      'snapshot':'此步不发送对话；查看页面并用配套只读导出记录原始、原子、候选和正式状态。',
      'candidate_action':'到“经验与偏好”的“待确认”，按类型、正文及来源选择实际候选；对其执行确认或不记录。多条候选需逐条辨认，不全选。',
      'entry_action':'到“我的内容”定位已记录别名对应的真实条目；按下方操作修改、删除或“提交团队共享”。共享时检查最终标题、正文、条件和例外，移除私人合同信息。',
      'add_member':'owner 到“管理团队成员”，把 member 设置为“成员”，勾选“允许访问”，点击“保存成员设置”。',
      'remove_member':'owner 到“管理团队成员”，取消 member 的“允许访问”，保存；member 刷新后检查拒绝访问。',
      'scope_check':'使用 member 的独立登录会话，核对“我的内容”为空、团队内容的预期状态，以及原合同和来源仍受限。',
      'review':'owner 到“共享申请与审核”，核对最终发布文本及差异，点击“批准发布”；回到“团队内容”检查。',
      'denied_review':'member 在“共享申请与审核”不应看到可用的批准按钮。补充用同一登录态按自动说明的 review 接口请求核验403，记录原始响应，不把按钮隐藏当唯一权限证据。',
      'seed_quarantine':'切换到独立 outsider 组织／应用及登录态，新建团队和空间，只在这里读入隔离材料、取得经验候选并确认。核验其数据目录或组织与owner不同后返回owner；禁止上传到A。',
      'observe_same_sources':'前一步正常对话已经再次触发整理。刷新“待确认”“我的内容”，对照忽略／删除前的来源和ID，核对没有复活；L0/L1历史仍保留。',
      'operator_checkpoint':'在此保存检查点、停止并恢复自动运行；人工路径核对刷新、重新登录后相同条目和会话仍可继续。',
      'fault_checkpoint':'按下方说明，仅在专用隔离运行实例操作；保存原始错误和前后快照，不停止正在供其他业务使用的进程。'}
    for s in steps:
        manual+=['\n### '+s['step_id']+' · '+s['action'],f"\n登录角色：{s['actor']}；团队：{s['team']}；空间：{s['workspace'] or '团队管理'}。"]
        manual.append('\n界面操作：'+ui_actions[s['action']])
        if s.get('name'):manual.append('团队名称：'+s['name']+'（追加本轮运行ID，避免与旧团队混淆）。')
        if s.get('input_id'):
            iid=s['input_id'];path='01_history/identity_map.txt' if iid=='IDENTITY-MAP' else '06_negative_controls_QUARANTINE/外部软件采购审批记录.txt' if iid=='NEG-XTENANT-01' else imap[iid]['path'];m=next((m for m in contracts if m['doc_id']==iid),None)
            manual.append('上传：'+(m['docx_path'] if m else path)+'。同份合同不再重复上传 TXT。')
        if s.get('text'):manual.append('\n发送以下自然对话：\n\n> '+s['text'])
        if s.get('operation'):manual.append('面板操作：'+s['operation']+'；条目别名：'+s.get('entry_alias','')+'；选择条件：'+json.dumps(s.get('selector',{}),ensure_ascii=False))
        for k in ['title','content','append','publication','conditions','exceptions','instruction']:
            if s.get(k):manual.append(k+'：'+(s[k] if isinstance(s[k],str) else '；'.join(s[k])))
        manual.append('等待／查看：'+('消息队列和提炼任务分别完成；保存回复、原生引用、/experience及分层快照。' if s['action']=='message' else '等待本步界面／接口真实回执并刷新列表，记录ID、版本及来源；不要把页面刷新当模型沉淀已完成。')+'失败、超时或权限待答不能视为已完成。')
        for cid in s['case_ids']:
            c=next(c for c in cases if c['case_id']==cid);manual.append(f"- {cid}（{'/'.join(c['layers'])}）：{c['expected']}；禁止：{c['forbidden']}。")
        manual.append('\n记录：时间____；原生空间／会话／文档／条目ID____；版本____；证据文件____；结果及理由____。')
    (ROOT/'10_manual/MANUAL_TEST.md').write_text('\n'.join(manual)+'\n')
    print(json.dumps({'steps':len(steps),'cases':len(cases),'clauses':sum(x['clause_number'] is not None for x in points),'categories':len(categories)},ensure_ascii=False))
if __name__=='__main__':main()
