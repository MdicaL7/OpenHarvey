import {api} from './api.js';
import {esc} from './markdown.js';
import {resolveParty,knowledgeEditPayload} from './knowledge-editor.js';

const tabs={preference:'我的偏好',rules:'规则与范本',case:'案例与决策'};
const kinds={preference:'我的偏好',rule:'审查标准',template:'参考范本',case:'案例与决策'};
const E=value=>esc(String(value??''));
let stylesheet=false;

export async function renderKnowledge(root,{identity,notice=()=>{},dirty=()=>{},isCurrent=()=>true}){
  if(!stylesheet&&!document.querySelector('link[href*="knowledge.css"]')){const link=document.createElement('link');link.rel='stylesheet';link.href='/static/knowledge.css?v=20260929-km';document.head.append(link);stylesheet=true;}
  let tab='preference',subType='all',status='active',query='',current=null,proposals=[],members=[],imports=[],parties=[],profile={active:false,role:null};
  let priorByProposal=new Map();
  const sourceChat=(sessionStorage.getItem('workbench-location')||'').match(/^\/agent#([a-f0-9]+)\/thread\//);
  let contractContext=null;
  const filters={counterparty:'',contract_type:'',project:'',department:'',mine:false,updated_from:'',updated_to:''};
  const role=identity.role==='admin';
  async function load(){
    let items=[];
    try{
      const scope=tab==='preference'?'personal':'organization';
      profile=await api('/api/knowledge/profile');
      const params=new URLSearchParams({scope,status,q:query});
      if(tab==='preference'){
        params.set('kind','preference');
      }else if(tab==='case'){
        params.set('kind','case');
      }else if(tab==='rules'){
        if(subType==='rule')params.set('kind','rule');
        else if(subType==='template')params.set('kind','template');
        else params.set('kinds','rule,template');
      }
      for(const key of ['counterparty','contract_type','project','department'])if(filters[key])params.set(key,filters[key]);
      if(filters.mine)params.set('mine','true');
      for(const key of ['updated_from','updated_to'])if(filters[key])params.set(key,String(new Date(filters[key]+'T00:00:00').getTime()/1000+(key==='updated_to'?86399:0)));
      items=(await api('/api/knowledge/items?'+params)).items;
      proposals=(await api(`/api/knowledge/proposals?scope=${scope}`)).items;
      priorByProposal=new Map(await Promise.all(proposals.filter(p=>p.target_id).map(async p=>{
        const pScope=p.scope||(p.owner_id?'personal':'organization');
        try{return [p.id,await api(`/api/knowledge/items/${pScope}/${p.kind}/${p.target_id}`)];}
        catch{return [p.id,null];}
      })));
      if(scope==='organization'){imports=await api('/api/knowledge/imports');parties=(await api('/api/knowledge/parties?status='+
        (profile.role==='maintainer'?'all':'active'))).items;}
      if(scope==='organization'&&sourceChat){
        try{contractContext=await api(`/api/knowledge/workspaces/${sourceChat[1]}/context`);}catch{contractContext=null;}
      }
      if(role)members=await api('/api/knowledge/members');
    }catch(error){notice(error.message);}
    if(!isCurrent())return;
    const org=tab!=='preference',canPublish=profile.role==='maintainer';
    const newBtnLabel=tab==='preference'?'个人偏好':tab==='case'?'案例与决策':subType==='rule'?'审查标准':subType==='template'?'参考范本':'规则或范本';
    root.innerHTML=`<div class="settings-heading"><div><h2>知识</h2><p>个人偏好由本人确认；组织知识由维护人发布。停用的条目不会进入新任务。</p></div></div>
      <section class="knowledge-tabs" role="tablist">${Object.entries(tabs).map(([id,name])=>`<button data-kind="${id}" role="tab" aria-selected="${tab===id}">${name}</button>`).join('')}</section>
      <section class="knowledge-toolbar"><input type="search" data-search placeholder="搜索知识" aria-label="搜索知识" value="${E(query)}">${tab==='rules'?`<div class="knowledge-type-filter" role="tablist" aria-label="类型筛选"><button type="button" data-type="all" value="all" role="tab" class="${subType==='all'?'active':''}" aria-selected="${subType==='all'}">全部</button><button type="button" data-type="rule" value="rule" role="tab" class="${subType==='rule'?'active':''}" aria-selected="${subType==='rule'}">审查标准</button><button type="button" data-type="template" value="template" role="tab" class="${subType==='template'?'active':''}" aria-selected="${subType==='template'}">参考范本</button></div><select data-type aria-label="类型筛选" class="knowledge-type-select" hidden><option value="all" ${subType==='all'?'selected':''}>全部</option><option value="rule" ${subType==='rule'?'selected':''}>审查标准</option><option value="template" ${subType==='template'?'selected':''}>参考范本</option></select>`:''}<select data-status aria-label="知识状态"><option value="active" ${status==='active'?'selected':''}>生效</option><option value="inactive" ${status==='inactive'?'selected':''}>停用</option><option value="all" ${status==='all'?'selected':''}>全部</option></select><button data-new class="primary">新增${E(newBtnLabel)}</button></section>
      ${org?`<section class="knowledge-filters"><label>合作方<select data-filter="counterparty"><option value="">全部</option>${parties.filter(p=>p.status==='active').map(p=>`<option value="${E(p.id)}" ${filters.counterparty===p.id?'selected':''}>${E(p.name)}${p.legal_identifier?' · '+E(p.legal_identifier):''}</option>`).join('')}</select></label><label>合同类型<input data-filter="contract_type" value="${E(filters.contract_type)}"></label><label>项目<input data-filter="project" value="${E(filters.project)}"></label><label>部门<input data-filter="department" value="${E(filters.department)}"></label><label>起始日期<input data-filter="updated_from" type="date" value="${E(filters.updated_from)}"></label><label>截止日期<input data-filter="updated_to" type="date" value="${E(filters.updated_to)}"></label><label>我参与的<input data-filter="mine" type="checkbox" ${filters.mine?'checked':''}></label>${canPublish?'<button data-party-add>新增合作方主体</button>':''}</section>`:''}
      <div class="knowledge-columns"><section class="knowledge-list" aria-label="知识列表">${items.map(item=>`<button data-item="${E(item.id)}" data-kind="${E(item.kind)}" data-scope="${E(item.scope)}" class="settings-list-item${current&&current.id===item.id?' active':''}"><b>${item.kind?`<span class="knowledge-tag knowledge-tag-${E(item.kind)}">${E(kinds[item.kind]||item.kind)}</span> `:''}${E(item.title||item.content)}</b><span>${E(kinds[item.kind]||item.kind)} · ${item.status==='active'?'生效':'停用'} · v${item.revision}</span><p>${E((item.content||'').slice(0,100))}</p></button>`).join('')||'<p class="settings-empty">暂无知识条目</p>'}</section><section class="knowledge-detail" aria-label="知识详情"><p class="settings-empty">选择条目查看来源和历史版本，或新建一条知识。</p></section></div>
      ${org&&canPublish?`<details class="knowledge-parties"><summary>合作方主体索引（${parties.length}）</summary>${parties.map(p=>`<p>${E(p.name)}${p.legal_identifier?' · '+E(p.legal_identifier):''} · ${p.status==='active'?'生效':'停用'} <button data-party-edit="${E(p.id)}">编辑</button><button data-party-toggle="${E(p.id)}">${p.status==='active'?'停用':'恢复'}</button></p>`).join('')}</details>`:''}
      ${org&&contractContext?`<section class="knowledge-context"><h3>当前合同的规则适用信息</h3><p class="settings-note">只填写已核实的条件；缺失时相关规则会标记“适用性待确认”。</p><form data-context-form><label>合作方<select name="counterparty_id"><option value="">待确认</option>${parties.filter(p=>p.status==='active').map(p=>`<option value="${E(p.id)}" ${contractContext.counterparty_id===p.id?'selected':''}>${E(p.name)}</option>`).join('')}</select></label><label>合同类型<input name="contract_type" value="${E(contractContext.contract_type)}"></label><label>项目<input name="project" value="${E(contractContext.project)}"></label><label>部门<input name="department" value="${E(contractContext.department)}"></label><button type="submit" class="primary">保存适用信息</button></form></section>`:''}
      ${org?`<section class="knowledge-imports"><h3>资料导入与整理</h3><p class="settings-note">支持 DOCX、文字版 PDF、Markdown、TXT。上传后只是资料，AI 提出的规则或范本仍需维护人确认。</p><label>提取类型<select data-import-kind><option value="rule">审查标准</option><option value="template">参考范本</option></select></label><label>上传资料<input data-import-file type="file" accept=".docx,.pdf,.md,.txt"></label><div>${imports.map(item=>`<article><b>${E(item.title)}</b> · ${E(item.knowledge_kind==='rule'?'审查标准':'参考范本')} <button data-extract="${E(item.id)}" data-extract-kind="${E(item.knowledge_kind)}">开始／重新整理</button>${item.thread_id?` <a href="/agent#${E(item.id)}/thread/${E(item.thread_id)}">查看整理对话</a>`:''}</article>`).join('')||'<p>暂无已上传资料</p>'}</div></section>`:''}
      <section class="knowledge-inbox"><h3>待确认（${proposals.length}）</h3><div class="knowledge-batch"><button data-batch="confirm">批量确认所选</button><button data-batch="ignore">批量忽略所选</button></div><div data-proposals>${proposals.map(p=>proposalCard(p)).join('')||'<p class="settings-empty">暂无待确认提案</p>'}</div></section>
      ${role?`<section class="knowledge-members"><h3>组织知识成员</h3><div data-members>${members.map(m=>`<div><span>${E(m.username)} · ${m.active?'已加入':'已停用'} · ${m.role==='maintainer'?'维护人':'成员'}</span><button data-member="${E(m.user_id)}">调整</button></div>`).join('')}</div><button data-member-add>添加组织成员</button></section>`:''}
      ${org?'<p class="settings-note">发布后组织成员可见知识正文和确认过的摘录；原始合同权限保持不变。</p>':''}`;
    root.querySelectorAll('.knowledge-tabs button').forEach(b=>b.onclick=async e=>{
      e?.stopPropagation?.();
      const next=b.dataset.kind;
      if(next==='rule'||next==='template'){tab='rules';subType=next;}
      else{tab=next;if(tab==='rules')subType='all';}
      status='active';current=null;await load();
    });
    root.querySelectorAll('button[data-type]').forEach(b=>b.onclick=async()=>{subType=b.dataset.type;current=null;await load();});
    const typeSelect=root.querySelector('select[data-type]');
    if(typeSelect){typeSelect.onchange=async e=>{subType=e.target.value;current=null;await load();};}
    root.querySelector('[data-status]').onchange=async e=>{status=e.target.value;await load();};
    root.querySelector('[data-search]').onchange=async e=>{query=e.target.value.trim();await load();};
    root.querySelectorAll('[data-filter]').forEach(field=>field.onchange=async e=>{filters[field.dataset.filter]=field.type==='checkbox'?field.checked:field.value;await load();});
    root.querySelector('[data-party-add]')?.addEventListener('click',async()=>{
      const name=prompt('请输入合作方的准确法律主体名称');if(!name)return;
      const legal_identifier=prompt('主体标识（统一社会信用代码等，可留空）')||'';
      try{await api('/api/knowledge/parties',{method:'POST',body:{name,legal_identifier}});notice('合作方主体已保存');await load();}
      catch(error){notice(error.message);}
    });
    root.querySelectorAll('[data-party-edit],[data-party-toggle]').forEach(b=>b.onclick=async()=>{
      const p=parties.find(item=>item.id===(b.dataset.partyEdit||b.dataset.partyToggle));if(!p)return;
      let name=p.name,legal_identifier=p.legal_identifier||'',nextStatus=p.status;
      if(b.dataset.partyEdit){name=prompt('合作方准确法律主体名称',p.name);if(name===null)return;
        legal_identifier=prompt('主体标识',p.legal_identifier||'');if(legal_identifier===null)return;}
      else nextStatus=p.status==='active'?'inactive':'active';
      try{await api(`/api/knowledge/parties/${p.id}`,{method:'PUT',body:{name,legal_identifier,
        revision:p.revision,status:nextStatus}});notice('合作方主体信息已更新');await load();}
      catch(error){notice(error.message);}
    });
    root.querySelector('[data-context-form]')?.addEventListener('submit',async event=>{
      event.preventDefault();const values=Object.fromEntries(new FormData(event.target));
      const submitBtn=event.target.querySelector('button[type="submit"]');
      if(submitBtn)submitBtn.disabled=true;
      try{await api(`/api/knowledge/workspaces/${sourceChat[1]}/context`,{method:'PUT',body:values});notice('本次合同适用信息已保存');await load();}
      catch(error){notice(error.message);if(submitBtn)submitBtn.disabled=false;}
    });
    root.querySelector('[data-new]').onclick=()=>editor(null);
    root.querySelectorAll('[data-item]').forEach(b=>b.onclick=async()=>{
      root.querySelectorAll('[data-item]').forEach(el=>el.classList.toggle('active',el===b));
      const target=items.find(it=>it.id===b.dataset.item);
      const itemScope=target?.scope||b.dataset.scope||(tab==='preference'?'personal':'organization');
      const itemKind=target?.kind||b.dataset.kind||(tab==='preference'?'preference':'rule');
      try{current=await api(`/api/knowledge/items/${itemScope}/${itemKind}/${b.dataset.item}`);await showItem(current);}catch(error){notice(error.message);}
    });
    root.querySelectorAll('[data-proposal]').forEach(card=>wireProposal(card));
    if(org){
      root.querySelector('[data-import-file]').onchange=async e=>{
        const file=e.target.files?.[0];if(!file)return;
        const selected=root.querySelector('[data-import-kind]').value;
        try{await api('/api/knowledge/imports',{method:'POST',body:file,headers:{'X-Filename':encodeURIComponent(file.name),'X-Knowledge-Kind':selected}});notice('资料已保存，可开始整理；尚未成为生效规则。');await load();}
        catch(error){notice(error.message);}
      };
      root.querySelectorAll('[data-extract]').forEach(b=>b.onclick=async()=>{
        b.dataset.requestId ||= crypto.randomUUID().replaceAll('-','');b.disabled=true;
        try{
          const job=await api(`/api/knowledge/imports/${b.dataset.extract}/extract`,{method:'POST',
            body:{kind:b.dataset.extractKind,request_id:b.dataset.requestId}});
          notice('资料整理任务已加入对话队列');location.assign(`/agent#${job.workspace_id}/thread/${job.thread_id}`);
        }catch(error){notice(error.message);b.disabled=false;}
      });
    }
    root.querySelectorAll('[data-batch]').forEach(b=>b.onclick=async()=>{
      const chosen=[...root.querySelectorAll('[data-proposal-check]:checked')].map(c=>proposals.find(p=>p.id===c.value)).filter(Boolean);
      if(!chosen.length)return notice('请先选择提案');
      b.disabled=true;
      try{
        const result=await api('/api/knowledge/proposals/batch',{method:'POST',body:{items:chosen.map(p=>({id:p.id,decision:b.dataset.batch,proposal_revision:p.proposal_revision}))}});
        const failed=result.results.filter(r=>r.error);notice(failed.length?`${failed.length} 项未处理，请查看差异。`:`已处理 ${chosen.length} 项`);await load();
      }catch(error){notice(error.message);b.disabled=false;}
    });
    if(role){
      root.querySelectorAll('[data-member]').forEach(b=>b.onclick=()=>editMember(b.dataset.member));
      root.querySelector('[data-member-add]').onclick=()=>editMember(null);
    }
  }
  function proposalCard(p){
    const c=p.content||{};
    const canPublish=Boolean(p.owner_id)||profile.role==='maintainer';
    const prior=priorByProposal.get(p.id);
    const kindName=kinds[p.kind]||p.kind;
    return `<article class="knowledge-proposal" data-proposal="${E(p.id)}"><label>${canPublish?`<input type="checkbox" data-proposal-check value="${E(p.id)}">`:''}<span class="knowledge-tag knowledge-tag-${E(p.kind)}">${E(kindName)}</span><b>${E(kindName)} · ${E(({create:'新增',update:'修改',disable:'停用'})[p.action])}</b></label><p>${E(c.title||c.content||'拟停用现有条目')}</p><small>来源：${E(p.thread_id?'对话任务':'人工提交')} · 目标版本 ${E(p.base_revision??'新条目')} · 提案 v${p.proposal_revision}</small><details><summary>查看修改前后及来源</summary>${prior?`<p>当前生效内容（v${prior.revision}）</p><pre>${E(prior.content)}</pre>`:''}<p>拟${E(({create:'新增',update:'修改',disable:'停用'})[p.action])}内容</p><pre>${E(c.content||prior?.content||'')}</pre>${(p.sources||[]).map(s=>`<p>来源：${E(s.filename||'记录')} · ${E(s.excerpt)}</p>`).join('')}</details><div class="knowledge-proposal-actions">${canPublish?`<button type="button" data-decision="confirm" class="primary">${p.owner_id?'本人确认':'维护人发布'}</button>`:''}<button type="button" data-proposal-edit>编辑候选</button>${canPublish||p.proposer_id===identity.id?'<button type="button" data-decision="ignore">忽略</button>':''}</div></article>`;
  }
  function wireProposal(card){
    const p=proposals.find(value=>value.id===card.dataset.proposal);
    const resolution=p.counterparty_resolution||resolveParty(p.content?.metadata?.counterparty_id,parties);
    if(p.action!=='disable'&&resolution&&resolution.status!=='resolved'){
      card.insertAdjacentHTML('beforeend',`<p class="settings-danger" role="status">合作方 ${E(resolution.reference)} ${resolution.status==='ambiguous'?'匹配到多个主体':'未匹配到有效主体'}，请编辑候选并选择合作方后再发布。</p>`);
      const publish=card.querySelector('[data-decision="confirm"]');if(publish)publish.disabled=true;
      const check=card.querySelector('[data-proposal-check]');if(check)check.disabled=true;
    }
    card.querySelectorAll('[data-decision]').forEach(button=>button.onclick=async()=>{
      const buttons=card.querySelectorAll('button');
      buttons.forEach(btn=>btn.disabled=true);
      try{await api(`/api/knowledge/proposals/${p.id}/decide`,{method:'POST',body:{decision:button.dataset.decision,proposal_revision:p.proposal_revision}});notice('提案已处理');await load();}
      catch(error){notice(error.message);buttons.forEach(btn=>btn.disabled=false);await load();}
    });
    card.querySelector('[data-proposal-edit]').onclick=()=>editor(p);
  }
  async function showItem(item){
    const detail=root.querySelector('.knowledge-detail');if(!detail)return;
    const versions=await api(`/api/knowledge/items/${item.scope}/${item.kind}/${item.id}/versions`);
    detail.innerHTML=`<h3>${E(item.title||'个人偏好')}</h3><p>${E(item.content)}</p><p class="settings-note"><span class="knowledge-tag knowledge-tag-${E(item.kind)}">${E(kinds[item.kind]||item.kind)}</span> · ${E(item.status==='active'?'生效':'已停用')} · v${item.revision} · ${E(item.maintainer_id||item.user_id)}</p>
      ${item.metadata?`<details><summary>适用范围</summary><pre>${E(JSON.stringify(item.metadata,null,2))}</pre></details>`:''}
      ${item.sources?.length?`<details><summary>已确认来源（${item.sources.length}）</summary>${item.sources.map(s=>`<p>${E(s.filename||'来源')}：${E(s.excerpt)}${s.source_available===false?' · 原件不可访问':''}</p>`).join('')}</details>`:''}
      <details><summary>历史版本</summary>${versions.map(v=>`<button type="button" data-version="${v.revision}">v${v.revision} · ${E(v.status)}</button>`).join('')}</details>
      <div class="settings-form-actions"><button type="button" data-edit>编辑</button>${item.status==='active'?'<button type="button" data-disable>停用</button>':item.scope==='personal'||profile.role==='maintainer'?'<button type="button" data-restore>恢复</button>':''}</div>`;
    detail.querySelector('[data-edit]').onclick=()=>editor(item);
    detail.querySelector('[data-disable]')?.addEventListener('click',async()=>{
      try{await api(`/api/knowledge/items/${item.scope}/${item.kind}/${item.id}/disable`,{method:'POST',body:{revision:item.revision}});notice('已提交停用操作');await load();}
      catch(error){notice(error.message);}
    });
    detail.querySelector('[data-restore]')?.addEventListener('click',async()=>{
      try{await api(`/api/knowledge/items/${item.scope}/${item.kind}/${item.id}/restore`,{method:'POST',body:{revision:item.revision}});notice('已恢复');await load();}
      catch(error){notice(error.message);}
    });
    detail.querySelectorAll('[data-version]').forEach(b=>b.onclick=async e=>{
      e?.stopPropagation?.();
      try{const old=await api(`/api/knowledge/items/${item.scope}/${item.kind}/${item.id}?revision=${b.dataset.version}`);notice(`v${old.revision}：${old.content}`);}
      catch(error){notice(error.message);}
    });
  }
  function editor(record){
    const proposal=record?.proposal_revision!==undefined;
    const isNew=!record;
    let kindOf;
    if(proposal||record)kindOf=record.kind;
    else if(tab==='rules')kindOf=(subType==='template'?'template':'rule');
    else if(tab==='preference')kindOf='preference';
    else kindOf='case';
    const c=proposal?record.content:record||{};
    const scope=(record?.scope)||(kindOf==='preference'?'personal':'organization');
    const detail=root.querySelector('.knowledge-detail');if(!detail)return;
    const showKindSelect=isNew&&tab==='rules';
    const partyReference=c.metadata?.counterparty_id;
    const resolution=record?.counterparty_resolution||resolveParty(partyReference,parties);
    const selectedParty=resolution?.status==='resolved'?resolution.id:'';
    const partyOptions=parties.filter(p=>p.status==='active').map(p=>`<option value="${E(p.id)}" ${selectedParty===p.id?'selected':''}>${E(p.name)} · ${E(p.legal_identifier||p.id.slice(-6))}${parties.filter(other=>other.name===p.name&&other.legal_identifier===p.legal_identifier).length>1?' · '+E(p.id.slice(-6)):''}</option>`).join('');

    detail.innerHTML=`<form class="settings-form knowledge-form"><h3>${proposal?'编辑待确认提案':record?`编辑${kinds[kindOf]||''}`:(tab==='rules'?'新增规则或范本':`新增${kinds[kindOf]}`)}</h3>
      ${showKindSelect?`<label>知识类型<select name="kind" data-form-kind><option value="rule" ${kindOf==='rule'?'selected':''}>审查标准</option><option value="template" ${kindOf==='template'?'selected':''}>参考范本</option></select></label>`:''}
      ${kindOf!=='preference'?`<label>标题<input name="title" required maxlength="120" value="${E(c.title)}"></label>`:''}
      <label>内容<textarea name="content" required rows="7">${E(c.content)}</textarea></label>
      ${kindOf!=='preference'?`<details ${partyReference&&!selectedParty?'open':''}><summary>筛选与证据</summary>
        <label>合作方<select name="counterparty_id" ${partyReference?'required':''}>${partyReference?(!selectedParty?`<option value="" disabled selected>请选择主体（原标识：${E(partyReference)}）</option>`:''):'<option value="">不限合作方</option>'}${partyOptions}</select></label>
        ${partyReference&&!selectedParty?'<p class="settings-danger" data-party-warning role="status">原标识无法唯一匹配，请人工选择有效主体。若列表中没有，请先在合作方主体索引中新增。</p>':''}
        <label>合同类型<input name="contract_type" value="${E(c.metadata?.contract_type)}"></label><label>项目<input name="project" value="${E(c.metadata?.project)}"></label><label>部门<input name="department" value="${E(c.metadata?.department)}"></label>
        <label>生效日期<input type="date" name="valid_from" value="${E(c.metadata?.valid_from)}"></label><label>截止日期<input type="date" name="valid_to" value="${E(c.metadata?.valid_to)}"></label>
        ${kindOf==='case'?`<label>决定类型<select name="decision_type"><option value="review">审查建议</option><option value="disposition">人工处置</option><option value="approval">正式批准</option></select></label>`:''}
        ${(c.sources||[]).map((s,i)=>`<fieldset><legend>来源 ${i+1} · ${E(s.filename||'记录')}</legend><p class="settings-note">${E(s.block_id||'手工摘录')}${s.source_hash?' · '+E(s.source_hash):''}</p><label>证据摘录<textarea name="source_excerpt_${i}" rows="3">${E(s.excerpt)}</textarea></label><label class="settings-check"><input type="checkbox" name="remove_source_${i}">移除此来源</label></fieldset>`).join('')}
        <label>新增手工摘录（每行一段）<textarea name="new_excerpts" rows="3"></textarea></label></details>`:''}
      ${record&&!proposal?`<p class="settings-note">基于 v${record.revision} 修改；保存前会再次核对版本。</p>`:''}
      <div class="settings-form-actions"><button type="submit" class="primary">${proposal?'保存提案':scope==='personal'?'保存个人偏好':'提交／发布'}</button><button type="button" data-cancel>取消</button></div></form>`;
    if(kindOf==='case')detail.querySelector('[name=decision_type]').value=c.metadata?.decision_type||'review';
    const partySelector=detail.querySelector('[name=counterparty_id]');
    if(partySelector)partySelector.onchange=()=>{
      const warning=detail.querySelector('[data-party-warning]');if(warning)warning.hidden=Boolean(partySelector.value);
    };
    detail.querySelector('[data-cancel]').onclick=()=>{dirty(false);void load();};
    detail.querySelector('form').oninput=()=>dirty(true);
    detail.querySelector('form').onsubmit=async event=>{
      event.preventDefault();const data=Object.fromEntries(new FormData(event.target));
      if(kindOf!=='preference'&&partyReference&&!data.counterparty_id)return notice('请选择有效的合作方主体');
      const submitBtn=event.target.querySelector('button[type="submit"]');
      if(submitBtn)submitBtn.disabled=true;
      const targetKind=proposal?record.kind:(record?record.kind:(data.kind||kindOf));
      const targetScope=(record?.scope)||(targetKind==='preference'?'personal':'organization');
      const body={content:data.content,revision:record?.revision};
      if(targetKind!=='preference'){
        Object.assign(body,knowledgeEditPayload(c,data));
      }
      try{
        if(proposal){body.proposal_revision=record.proposal_revision;await api(`/api/knowledge/proposals/${record.id}`,{method:'PUT',body});}
        else if(record){await api(`/api/knowledge/items/${targetScope}/${targetKind}/${record.id}`,{method:'PUT',body});}
        else{await api('/api/knowledge/items',{method:'POST',body:{...body,scope:targetScope,kind:targetKind}});}
        dirty(false);notice(proposal?'提案已更新':'知识已保存或提交待确认');await load();
      }catch(error){notice(error.message);if(submitBtn)submitBtn.disabled=false;}
    };
  }
  async function editMember(uid){
    try{
      const candidates=await api('/api/knowledge/members/candidates');
      const member=members.find(m=>m.user_id===uid);
      const detail=root.querySelector('.knowledge-detail');
      detail.innerHTML=`<form class="settings-form"><h3>组织知识成员</h3><label>账号<select name="user_id" ${uid?'disabled':''}>${candidates.map(c=>`<option value="${E(c.id)}" ${c.id===uid?'selected':''}>${E(c.username)}</option>`).join('')}</select></label><label>权限<select name="role"><option value="member">成员</option><option value="maintainer">知识维护人</option></select></label><label class="settings-check"><input name="active" type="checkbox" ${member?.active===0?'':'checked'}>已加入</label><div class="settings-form-actions"><button type="submit" class="primary">保存成员权限</button><button type="button" data-cancel>取消</button></div></form>`;
      detail.querySelector('[name=role]').value=member?.role||'member';
      detail.querySelector('[data-cancel]').onclick=()=>{dirty(false);void load();};
      detail.querySelector('form').onsubmit=async e=>{
        e.preventDefault();const form=e.target;const id=uid||form.elements.user_id.value;
        const submitBtn=form.querySelector('button[type="submit"]');
        if(submitBtn)submitBtn.disabled=true;
        try{await api(`/api/knowledge/members/${id}`,{method:'PUT',body:{role:form.elements.role.value,active:form.elements.active.checked,revision:member?.revision}});notice('成员权限已保存');await load();}
        catch(error){notice(error.message);if(submitBtn)submitBtn.disabled=false;}
      };
    }catch(error){notice(error.message);}
  }
  await load();
}

export function knowledgeProposalHTML(part){
  const p=part.knowledge_proposal;
  if(!p)return '';
  const content=p.content||{};
  return `<aside class="memory-receipt knowledge-proposal" data-knowledge-chat-proposal="${E(p.id)}"><strong>${p.status==='pending'?'组织知识待维护人确认':'组织知识提案已处理'}</strong><p>${E(content.title||content.content||'拟停用知识')}</p>${p.status==='pending'?`<div class="memory-receipt-actions"><span class="proposal-version">提案 v${p.proposal_revision}</span>${p.can_publish?`<button type="button" class="primary" data-knowledge-decision="confirm" data-id="${E(p.id)}" data-revision="${p.proposal_revision}">维护人发布</button>`:''}<button type="button" class="secondary" data-knowledge-decision="ignore" data-id="${E(p.id)}" data-revision="${p.proposal_revision}">忽略</button><a href="/knowledge" class="memory-receipt-link">查看或编辑提案</a></div>`:''}</aside>`;
}

export function knowledgeReferencesHTML(parts){
  const refs=[...new Map(parts.flatMap(p=>p.knowledge_references||[]).map(k=>[k.item_id+':'+k.revision,k])).values()];
  if(!refs.length)return '';
  return `<details class="memory-references"><summary>参考组织知识 · ${refs.length}</summary>${refs.map(r=>`<p>${E(r.title)} · v${r.revision}${r.current_status==='inactive'?' · 已停用':''}</p>`).join('')}</details>`;
}

export async function handleKnowledgeProposalAction(event,{notice=()=>{}}={}){
  const b=event.target.closest('[data-knowledge-decision]');if(!b)return false;
  event.preventDefault();
  if(b.disabled)return true;
  const card=b.closest('[data-knowledge-chat-proposal]');
  const buttons=card?.querySelectorAll('button')||[b];
  buttons.forEach(btn=>btn.disabled=true);
  try{
    await api(`/api/knowledge/proposals/${b.dataset.id}/decide`,{method:'POST',body:{decision:b.dataset.knowledgeDecision,proposal_revision:Number(b.dataset.revision)}});
    if(card)card.innerHTML='<strong>提案已处理</strong>';
    document.dispatchEvent(new Event('memory-changed'));
  }catch(error){
    buttons.forEach(btn=>btn.disabled=false);
    notice(error.message);
  }
  return true;
}
