import {redlineLabsHTML,announceLabsChange} from './redline-labs.js';
import {api} from './api.js';
import {t as tr,getLanguage} from './i18n.js';

export async function renderLabs(root,{notice,isCurrent=()=>true}){
  const [status,redline]=await Promise.all([api('/api/settings/labs'),api('/api/settings/labs/redline')]);
  if(!isCurrent())return;
  root.innerHTML=`<div class="settings-heading"><div><h2>Labs</h2><p>${tr('尝试工作台的实验功能。')}</p></div></div><section class="labs-feature materials-labs"><header><div><h3>${tr('合同资料')}</h3><p>${tr('集中管理合同空间的资料，批量上传、查找和恢复，并由助手按任务取材。')}</p></div><label class="settings-check"><input type="checkbox" data-materials-toggle ${status.materials_enabled?'checked':''}>${tr('开启')}</label></header><p class="settings-note">${tr('默认关闭，仅对我的账号生效。关闭后恢复附件入口，已有资料与历史引用保留。')}</p><p class="settings-note" data-materials-status role="status">${tr(status.materials_enabled?'已开启合同资料':'未开启合同资料')}</p><p class="settings-note"><a href="/guide${getLanguage()==='en'?'?lang=en':''}#materials" target="_blank" rel="noopener">${tr('使用手册')} ↗</a></p></section>${redlineLabsHTML(redline)}`;
  root.querySelector('[data-materials-toggle]').onchange=async e=>{
    const input=e.target;input.disabled=true;
    try{
      Object.assign(status,await api('/api/settings/labs',{method:'PATCH',body:{materials_enabled:input.checked,revision:status.revision}}));
      root.querySelector('[data-materials-status]').textContent=tr(status.materials_enabled?'已开启合同资料':'未开启合同资料');
      announceLabsChange();
    }catch(error){input.checked=status.materials_enabled;root.querySelector('[data-materials-status]').textContent=error.message;notice(error.message);}
    finally{input.disabled=false;}
  };
  root.querySelector('[data-redline-toggle]').onchange=async e=>{
    const input=e.target;input.disabled=true;
    try{await api('/api/settings/labs/redline',{method:'PATCH',body:{redline_enabled:input.checked,revision:redline.revision}});}
    catch(error){input.checked=redline.redline_enabled;notice(error.message);}
    finally{input.disabled=!redline.available;announceLabsChange();}
  };
}
