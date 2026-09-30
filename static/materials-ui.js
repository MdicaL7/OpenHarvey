import {api,upload} from './api.js';
import {esc,citations,markdown} from './markdown.js';
import {t as tr} from './i18n.js';
import {loadingHTML} from './loading-ui.js';

export const activeDocuments=documents=>documents.filter(d=>!d.removed_at&&!d.historical_only);

const KNOWLEDGE_KIND_LABELS = {
  rule: '审查标准',
  template: '参考范本',
  case: '案例与决策',
  preference: '表达偏好'
};

export function sourceReferencesHTML(text, documents, {
  memoryReferences = [],
  knowledgeReferences = [],
  open = new Set(),
  key = '',
  materialsEnabled = true,
} = {}) {
  // 1. Contract materials / documents (only if materialsEnabled is true)
  const contractEntries = new Map();
  if (materialsEnabled) {
    for (const match of String(text || '').matchAll(/【D([a-f0-9]{12}):B(\d+)(?:-B(\d+))?】/g)) {
      const doc = (documents || []).find(d => d.id === match[1]);
      if (doc?.locations?.['B' + match[2]] && doc.locations['B' + (match[3] || match[2])]) {
        if (!contractEntries.has(doc.id)) contractEntries.set(doc.id, { doc, tags: new Set() });
        contractEntries.get(doc.id).tags.add(match[0]);
      }
    }
  }

  // 2. Personal preferences: deduplicated by kind + id + revision
  const memoryEntries = new Map();
  for (const item of memoryReferences || []) {
    if (!item) continue;
    const kind = item.kind || 'preference';
    const id = item.id || item.item_id;
    if (!id) continue;
    const rev = item.revision ?? 1;
    const entryKey = `${kind}:${id}:${rev}`;
    if (!memoryEntries.has(entryKey)) {
      memoryEntries.set(entryKey, item);
    }
  }

  // 3. Organization knowledge: deduplicated by kind + id + revision
  const knowledgeEntries = new Map();
  for (const item of knowledgeReferences || []) {
    if (!item) continue;
    const kind = item.kind || 'rule';
    const id = item.item_id || item.id;
    if (!id) continue;
    const rev = item.revision ?? 1;
    const entryKey = `${kind}:${id}:${rev}`;
    if (!knowledgeEntries.has(entryKey)) {
      knowledgeEntries.set(entryKey, item);
    }
  }

  const total = contractEntries.size + memoryEntries.size + knowledgeEntries.size;
  if (!total) return '';

  const contractHTML = [...contractEntries.values()].map(({ doc, tags }) => {
    const isPrimary = doc.primary;
    const tagLabel = isPrimary ? tr('主合同') : (doc.thread_id ? tr('附件') : tr('合同资料'));
    const tagClass = 'reference-tag-contract';
    const cites = [...tags].map(t => citations(t, documents)).join(' ');
    return `<div class="reference-entry"><span class="reference-tag ${tagClass}">${esc(tagLabel)}</span><span class="reference-title" title="${esc(doc.filename)}">${esc(doc.filename)}${doc.removed_at ? ' · ' + tr('已移除') : ''}</span> <span class="reference-citations">${cites}</span></div>`;
  }).join('');

  const memoryHTML = [...memoryEntries.values()].map(item => {
    const snippet = item.content ? (item.content.length > 50 ? item.content.slice(0, 50) + '…' : item.content) : tr('偏好');
    const isInactive = item.current_status === 'inactive';
    const isChanged = item.current_revision != null && item.current_revision !== item.revision;
    const statusText = isInactive ? ' · ' + tr('已停用') : isChanged ? ' · ' + tr('已有新版本') : '';
    return `<div class="reference-entry"><span class="reference-tag reference-tag-preference">${tr('表达偏好')}</span><button type="button" class="reference-item-btn" data-reference-type="preference" data-scope="personal" data-kind="preference" data-id="${esc(item.id)}" data-revision="${esc(item.revision)}"><span class="reference-name">${esc(snippet)}</span><span class="reference-version"> · v${esc(item.revision)}</span>${statusText ? `<span class="reference-status">${esc(statusText)}</span>` : ''}</button></div>`;
  }).join('');

  const knowledgeHTML = [...knowledgeEntries.values()].map(item => {
    const kind = item.kind || 'rule';
    const label = tr(KNOWLEDGE_KIND_LABELS[kind] || '组织知识');
    const tagClass = `reference-tag-${kind}`;
    const isInactive = item.current_status === 'inactive';
    const isChanged = item.current_revision != null && item.current_revision !== item.revision;
    const statusText = isInactive ? ' · ' + tr('已停用') : isChanged ? ' · ' + tr('已有新版本') : '';
    return `<div class="reference-entry"><span class="reference-tag ${tagClass}">${esc(label)}</span><button type="button" class="reference-item-btn" data-reference-type="knowledge" data-scope="${esc(item.scope || 'organization')}" data-kind="${esc(kind)}" data-id="${esc(item.item_id || item.id)}" data-revision="${esc(item.revision)}"><span class="reference-name">${esc(item.title || tr('知识条目'))}</span><span class="reference-version"> · v${esc(item.revision)}</span>${statusText ? `<span class="reference-status">${esc(statusText)}</span>` : ''}</button></div>`;
  }).join('');

  const dataKeyAttr = key ? ` data-key="${esc(key)}"` : '';
  const openAttr = (key && open.has(key)) ? ' open' : '';
  return `<details class="material-references"${dataKeyAttr}${openAttr}><summary>${tr('引用来源')} · ${total}</summary><div class="reference-list">${contractHTML}${memoryHTML}${knowledgeHTML}</div></details>`;
}

export async function openReferenceDetail({ referenceType, scope, kind, id, revision }){
  const dialog = document.createElement('dialog');
  dialog.className = 'reference-detail-dialog';
  dialog.setAttribute('aria-labelledby', 'refDetailTitle');
  dialog.innerHTML = `<header class="reference-detail-header">
    <div class="reference-detail-head-main">
      <h3 id="refDetailTitle">${tr('引用详情')}</h3>
      <div class="reference-detail-badges" data-badges></div>
    </div>
    <button type="button" class="dialog-close-btn" data-close aria-label="${tr('关闭')}">×</button>
  </header>
  <div class="reference-detail-body" data-body>
    ${loadingHTML(tr('正在加载引用内容…'))}
  </div>
  <footer class="reference-detail-footer">
    <button type="button" data-close class="primary">${tr('关闭')}</button>
  </footer>`;
  document.body.append(dialog);
  dialog.showModal();

  const cleanup = () => { dialog.remove(); };
  const close = () => { dialog.close(); cleanup(); };
  dialog.oncancel = close;
  dialog.querySelectorAll('[data-close]').forEach(btn => btn.onclick = close);

  const titleEl = dialog.querySelector('#refDetailTitle');
  const badgesEl = dialog.querySelector('[data-badges]');
  const bodyEl = dialog.querySelector('[data-body]');

  try {
    const revParam = revision ? `?revision=${encodeURIComponent(revision)}` : '';
    const item = await api(`/api/knowledge/items/${encodeURIComponent(scope || (referenceType === 'preference' ? 'personal' : 'organization'))}/${encodeURIComponent(kind || (referenceType === 'preference' ? 'preference' : 'rule'))}/${encodeURIComponent(id)}${revParam}`);

    const isPreference = referenceType === 'preference' || kind === 'preference' || scope === 'personal';
    const itemKind = item.kind || kind || (isPreference ? 'preference' : 'rule');
    const kindLabel = tr(KNOWLEDGE_KIND_LABELS[itemKind] || (isPreference ? '表达偏好' : '组织知识'));
    const isInactive = item.current_status === 'inactive';
    const isChanged = item.current_revision != null && item.current_revision !== item.revision;

    titleEl.textContent = isPreference ? tr('个人偏好') : (item.title || tr('知识详情'));

    badgesEl.innerHTML = `
      <span class="reference-tag reference-tag-${esc(itemKind)}">${esc(kindLabel)}</span>
      <span class="reference-badge reference-badge-version">v${esc(item.revision)}</span>
      ${isInactive ? `<span class="reference-badge reference-badge-inactive">${tr('现已停用')}</span>` : ''}
      ${isChanged ? `<span class="reference-badge reference-badge-changed">${tr('已有新版本')} (v${esc(item.current_revision)})</span>` : ''}
    `;

    let html = '';
    if (isPreference) {
      html += `<div class="reference-detail-notice preference-notice">${tr('表达偏好仅作为回复风格与习惯参考，避免被误认为合同判断依据。')}</div>`;
    } else {
      html += `<div class="reference-detail-notice">${tr('当前展示该回答引用时的历史版本。若后续条目发生更新或停用，此处保持历史引用不变。')}</div>`;
    }

    html += `<div class="reference-detail-content markdown">${markdown(item.content || '')}</div>`;

    if (item.sources && item.sources.length) {
      html += `<div class="reference-detail-sources">
        <h4>${tr('已确认来源')}</h4>
        ${item.sources.map(s => `
          <div class="reference-source-item">
            <div class="reference-source-meta">
              <strong>${esc(s.filename || tr('来源资料'))}</strong>
              ${s.source_available === false ? `<span class="badge-source-unavailable">${tr('原资料不可访问')}</span>` : ''}
            </div>
            <blockquote class="reference-source-excerpt">${esc(s.excerpt || '')}</blockquote>
          </div>
        `).join('')}
      </div>`;
    }

    bodyEl.innerHTML = html;
  } catch (err) {
    titleEl.textContent = tr('资料不可访问');
    badgesEl.innerHTML = `<span class="reference-badge reference-badge-inactive">${tr('不可用')}</span>`;
    bodyEl.innerHTML = `<p class="chat-error">${esc(err.message || tr('原资料不可访问或权限已撤销。'))}</p>`;
  }
}

export function setupMaterials({context,notice,refresh,openSource,onBusy}){
  const dialog=document.createElement('dialog');dialog.className='materials-dialog';dialog.setAttribute('aria-labelledby','materialsTitle');
  dialog.innerHTML=`<header><div><h2 id="materialsTitle">${tr('合同资料')}</h2><p>${tr('本合同空间内所有对话可用；助手按问题查找相关资料。')}</p></div><button type="button" data-close aria-label="${tr('关闭')}">×</button></header>
    <div class="materials-toolbar"><input type="search" data-search placeholder="${tr('搜索文件名')}" aria-label="${tr('搜索文件名')}"><select data-type aria-label="${tr('文件格式')}"><option value="">${tr('全部格式')}</option>${['docx','pdf','md','txt'].map(s=>`<option value=".${s}">${s.toUpperCase()}</option>`).join('')}</select><select data-scope aria-label="${tr('资料范围')}"><option value="active">${tr('当前资料')}</option><option value="removed">${tr('已移除')}</option></select><button type="button" data-add>${tr('添加资料')}</button></div>
    <input type="file" data-files accept=".docx,.pdf,.md,.txt" multiple hidden>
    <div class="materials-drop" data-drop>${tr('可拖入多份文件，支持 Word、文字版 PDF、Markdown 和 TXT。')}</div>
    <p class="materials-status" data-status role="status"></p><div data-jobs aria-live="polite"></div><div class="materials-table" data-table></div>`;
  document.body.append(dialog);
  const $=s=>dialog.querySelector(s),jobs=new Map();
  let wid=null,rows=[],busy=false,generation=0,lastRemoved=null,session=0,errorMessage='',loading=false;
  const writable=()=>context().enabled&&context().wid===wid&&!!context().tid&&!context().readOnly&&!context().busy&&!busy;
  function setBusy(value){busy=value;onBusy();render();}
  function render(){
    const q=$('[data-search]').value.trim().toLowerCase(),suffix=$('[data-type]').value,removed=$('[data-scope]').value==='removed';
    const visible=rows.filter(d=>!!d.removed_at===removed&&(!suffix||d.suffix===suffix)&&d.filename.toLowerCase().includes(q));
    $('[data-add]').disabled=!writable();
    $('[data-status]').replaceChildren();
    if(errorMessage)$('[data-status]').textContent=errorMessage;
    else if(lastRemoved){
      $('[data-status]').textContent=tr('已移出资料区，历史引用保留。')+' ';
      const undo=document.createElement('button');undo.textContent=tr('撤销');undo.disabled=!writable();undo.onclick=()=>void change(lastRemoved,'restore');$('[data-status]').append(undo);
    }else if(context().busy)$('[data-status]').textContent=tr('空间内任务结束后可修改资料。');
    $('[data-table]').innerHTML=visible.length?`<table><thead><tr><th>${tr('名称')}</th><th>${tr('格式')}</th><th>${tr('操作')}</th></tr></thead><tbody>${visible.map(d=>`<tr><td><button type="button" data-open="${esc(d.id)}">${esc(d.filename)}</button><small>${tr(d.primary?'主合同':d.removed_at?'已移除':'可用')}</small></td><td>${esc(d.suffix.slice(1).toUpperCase())}</td><td>${!d.primary?`<button type="button" data-action="${d.removed_at?'restore':'remove'}" data-id="${esc(d.id)}" ${writable()?'':'disabled'}>${tr(d.removed_at?'恢复':'移除')}</button>`:''}</td></tr>`).join('')}</tbody></table>`:`<p class="materials-empty">${tr(removed?'没有已移除资料':'没有匹配的资料')}</p>`;
    $('[data-jobs]').innerHTML=(jobs.get(wid)||[]).map((job,index)=>`<div class="material-upload"><span>${esc(job.name)}</span><span>${esc(tr(job.status))}${job.error?`：${esc(job.error)}`:''}</span>${job.status==='失败'?`<button type="button" data-retry="${index}" ${writable()?'':'disabled'}>${tr('重试')}</button>`:''}</div>`).join('');
    if(loading&&!rows.length)$('[data-table]').innerHTML=loadingHTML(tr('正在读取资料…'));
  }
  async function reload(){
    const target=wid,version=++generation;
    loading=true;render();
    try{
      const data=await api(`/api/workspaces/${target}/documents`);
      if(version!==generation||wid!==target)return;
      rows=data.documents;
    }finally{if(version===generation&&wid===target){loading=false;render();}}
  }
  async function open(){
    const c=context();if(!c.enabled||!c.wid)return;
    if(wid!==c.wid){wid=c.wid;rows=[];lastRemoved=null;errorMessage='';}
    if(!dialog.open)dialog.showModal();
    render();
    try{await reload();}catch(e){$('[data-status]').textContent=e.message;}
  }
  async function change(id,action){
    if(!writable())return;
    const target=wid,account=session;errorMessage='';setBusy(true);
    try{
      await api(`/api/workspaces/${target}/documents/${id}`,{method:'PATCH',body:{action}});
      if(account!==session)return;
      lastRemoved=action==='remove'?id:null;
      if(context().wid===target)await refresh(action==='remove'?id:null);
      await reload();
    }catch(e){errorMessage=e.message;notice(e.message,'error');}
    finally{if(account===session)setBusy(false);}
  }
  async function run(items){
    if(!writable())return;
    const target=wid,thread=context().tid,account=session;errorMessage='';setBusy(true);
    try{
      // ponytail: sequential uploads suit contract-sized batches; add bounded
      // concurrency only when measured upload latency calls for it.
      for(const job of items){
        if(account!==session)break;
        job.status='处理中';job.error='';render();
        try{
          const result=await upload(`/api/workspaces/${target}/attachments?thread_id=${thread}`,job.file);
          job.status=result.reused?'已存在':'可用';job.file=null;
        }catch(e){job.status='失败';job.error=e.message;}
        if(account!==session)return;
        render();
      }
      if(context().wid===target)await refresh();
      if(wid===target)await reload();
    }catch(e){errorMessage=e.message;notice(e.message,'error');}
    finally{if(account===session)setBusy(false);}
  }
  async function add(files){
    if(busy||!files.length)return;
    await open();if(!writable())return;
    const items=Array.from(files,file=>({file,name:file.name,status:'待上传',error:''}));
    jobs.set(wid,[...(jobs.get(wid)||[]),...items]);await run(items);
  }
  for(const selector of ['[data-search]','[data-type]','[data-scope]'])$(selector).addEventListener('input',render);
  $('[data-close]').onclick=()=>dialog.close();
  $('[data-add]').onclick=()=>$('[data-files]').click();
  $('[data-files]').onchange=e=>{const files=Array.from(e.target.files);e.target.value='';void add(files);};
  dialog.onclick=async e=>{
    const button=e.target.closest('button');if(!button||button.disabled)return;
    if(button.dataset.open){dialog.close();try{await openSource(button.dataset.open);}catch(error){notice(error.message,'error');}}
    if(button.dataset.action)await change(button.dataset.id,button.dataset.action);
    if(button.dataset.retry!=null)await run([jobs.get(wid)[Number(button.dataset.retry)]]);
  };
  dialog.ondragover=e=>{if(e.dataTransfer?.types.includes('Files')){e.preventDefault();$('[data-drop]').classList.add('dragging');}};
  dialog.ondragleave=()=>$('[data-drop]').classList.remove('dragging');
  dialog.ondrop=e=>{e.preventDefault();$('[data-drop]').classList.remove('dragging');void add(Array.from(e.dataTransfer.files));};
  return {open,add,get busy(){return busy;},close(){dialog.close();generation++;},reset(){dialog.close();generation++;session++;jobs.clear();rows=[];wid=null;busy=false;}};
}
