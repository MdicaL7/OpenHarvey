import {t as tr} from './i18n.js';

let dialogEl=null;

function ensureConfirmDialog(){
  if(dialogEl&&dialogEl.isConnected)return dialogEl;
  dialogEl=document.getElementById('ohConfirmDialog');
  if(!dialogEl){
    dialogEl=document.createElement('dialog');
    dialogEl.id='ohConfirmDialog';
    dialogEl.className='dialog-sm';
    dialogEl.innerHTML=`<form method="dialog"><h3 data-confirm-title></h3><p data-confirm-message></p><div class="dialog-actions"><button type="submit" value="cancel" data-confirm-cancel formnovalidate></button><button type="submit" value="confirm" data-confirm-ok class="confirm-delete"></button></div></form>`;
    document.body.append(dialogEl);
  }
  return dialogEl;
}

export function confirmDialog({title,message='',confirmText=tr('确认删除'),cancelText=tr('取消'),danger=true,trigger=null}={}){
  const opener=trigger||document.activeElement;
  const dialog=ensureConfirmDialog();
  const titleNode=dialog.querySelector('[data-confirm-title]');
  const messageNode=dialog.querySelector('[data-confirm-message]');
  const cancelBtn=dialog.querySelector('[data-confirm-cancel]');
  const okBtn=dialog.querySelector('[data-confirm-ok]');
  titleNode.textContent=title||tr('请确认');
  messageNode.textContent=message;
  messageNode.hidden=!message;
  cancelBtn.textContent=cancelText;
  okBtn.textContent=confirmText;
  okBtn.classList.toggle('confirm-delete',Boolean(danger));
  okBtn.classList.toggle('primary',!danger);
  dialog.returnValue='cancel';
  return new Promise(resolve=>{
    dialog.onclose=()=>{
      const confirmed=dialog.returnValue==='confirm';
      if(opener&&opener.isConnected&&!opener.disabled&&typeof opener.focus==='function')opener.focus();
      resolve(confirmed);
    };
    if(typeof dialog.showModal==='function')dialog.showModal();
    else dialog.setAttribute('open','');
    cancelBtn.focus();
  });
}
