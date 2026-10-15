import {api} from './api.js';
import {esc} from './markdown.js';
const relations={applicable:'可参考',conditional:'需核对',insufficient:'信息不足'};
export function precedentHTML(result){
 const items=(result.items||[]).slice(0,3);
 if(!items.length)return `<p class="precedent-empty">${esc(result.notice||'暂无合适的历史处置参考。')}</p>`;
 return items.map(e=>`<article class="precedent-case"><strong>${esc(relations[e.relation]||'需核对')} · 此前${esc(e.decision)}</strong><p>${esc(e.note||'未填写处置理由')}</p><p>适用条件：${esc((e.conditions||[]).join('；')||'请核对历史处置原话')}<br>例外：${esc((e.exceptions||[]).join('；')||'未提供')}</p><p>相同点：${esc((e.matching_points||[]).join('；')||'尚未确认')}<br>本次差异：${esc((e.differences||[]).join('；')||'请结合当前原文核对')}</p><small>历史案例版本 ${Number(e.version)||1} · 不代表本次处理决定</small>${typeof e.source_url==='string'&&/^\/agent\?[^#]*#[a-f0-9]+/.test(e.source_url)?`<a href="${esc(e.source_url)}">查看历史反馈</a>`:''}</article>`).join('');
}
export async function loadPrecedents(root,stillCurrent=()=>true){
 await Promise.all([...root.querySelectorAll('[data-precedents]')].map(async host=>{
  if(host.dataset.loaded)return;host.dataset.loaded='1';const board=host.closest('[data-risk-board]');
  try{const result=await api(`/api/artifacts/${board.dataset.riskBoard}/risks/${encodeURIComponent(host.dataset.precedents)}/precedents`,{timeout:210000});if(host.isConnected&&stillCurrent())host.innerHTML=precedentHTML(result);}
  catch(error){if(host.isConnected&&stillCurrent())host.textContent=error.status===409?'合同或来源版本已变化，请重新审查后查询历史参考。':error.status===422?'当前报告未启用历史处置参考。':'历史处置暂时无法查询；当前审查结果仍可查看。';}
 }));
}
