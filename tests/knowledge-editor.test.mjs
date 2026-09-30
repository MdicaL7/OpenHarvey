import test from 'node:test';
import assert from 'node:assert/strict';
import {JSDOM} from 'jsdom';
import {resolveParty,knowledgeEditPayload} from '../static/knowledge-editor.js';
import {renderKnowledge} from '../static/knowledge-ui.js';

test('party identity uses exact active records and requires selection for ambiguity',()=>{
  const parties=[{id:'a',name:'母公司',legal_identifier:'MOCK-A',status:'active'},
    {id:'child',name:'子公司',legal_identifier:'MOCK-A-EAST',status:'active'},
    {id:'off',name:'已停用',legal_identifier:'OLD',status:'inactive'}];
  assert.equal(resolveParty('MOCK-A',parties).id,'a');
  assert.equal(resolveParty('母公司',parties).id,'a');
  assert.equal(resolveParty('MOCK',parties).status,'not_found');
  assert.equal(resolveParty('OLD',parties).status,'not_found');
  const duplicates=[...parties,{...parties[0],id:'b'}];
  assert.equal(resolveParty('MOCK-A',duplicates).status,'ambiguous');
  assert.equal(resolveParty('a',duplicates).id,'a');
});

test('editing visible fields preserves unknown metadata and multiline source provenance',()=>{
  const base={metadata:{category:'安全',valid_from:'2026-03-01',valid_to:'2026-12-31',custom:{nested:true}},
    sources:[{excerpt:'第一行\n第二行',document_id:'doc1',source_hash:'hash',block_id:'B2',owner_user_id:'owner',
      filename:'约定.md',custom:{page:2}}]};
  const edited=knowledgeEditPayload(base,{title:'新题',content:'修改正文',counterparty_id:'real-id',
    department:'信息技术部',source_excerpt_0:'第一行\n第二行'});
  assert.deepEqual(edited.sources,base.sources);
  assert.deepEqual(edited.metadata,{...base.metadata,counterparty_id:'real-id',department:'信息技术部'});
  assert.equal(knowledgeEditPayload(base,{valid_to:''}).metadata.valid_to,null);
  assert.equal(knowledgeEditPayload(base,{remove_source_0:'on'}).sources.length,0);
  assert.equal(base.metadata.valid_to,'2026-12-31');
});

test('unresolved proposal blocks publication until named selector submits host ID with intact evidence',async()=>{
  const dom=new JSDOM('<div id="root"></div>');
  const previous=Object.fromEntries(['document','FormData','sessionStorage','fetch','File','Blob'].map(k=>[k,globalThis[k]]));
  const calls=[],notices=[];
  const source={excerpt:'原文第一行\n原文第二行',document_id:'doc1',source_hash:'hash',block_id:'B1',filename:'约定.md',owner_user_id:'u1'};
  const p={id:'p1',kind:'rule',action:'create',owner_id:null,proposal_revision:2,proposer_id:'u1',
    content:{title:'专项规则',content:'规则正文',metadata:{counterparty_id:'UNKNOWN',valid_from:'2026-03-01',
      valid_to:'2026-12-31',category:'安全',custom:{kept:true}},sources:[source]},sources:[source],
    counterparty_resolution:{status:'not_found',reference:'UNKNOWN'}};
  try{
    globalThis.document=dom.window.document;globalThis.FormData=dom.window.FormData;
    globalThis.File=dom.window.File;globalThis.Blob=dom.window.Blob;
    globalThis.sessionStorage={getItem:()=>null};
    globalThis.fetch=async(url,options={})=>{
      calls.push({url:String(url),method:options.method,body:options.body});
      let data={};
      if(String(url).includes('/profile'))data={role:'maintainer',active:true};
      else if(String(url).includes('/proposals?'))data={items:[p]};
      else if(String(url).includes('/items?'))data={items:[]};
      else if(String(url).includes('/parties'))data={items:[{id:'a',name:'临沄数研技术有限公司',legal_identifier:'MOCK-A',status:'active'}]};
      else if(String(url).includes('/imports'))data=[];
      return {ok:true,json:async()=>data};
    };
    const root=document.querySelector('#root');
    await renderKnowledge(root,{identity:{id:'u1',role:'member'},notice:msg=>notices.push(msg)});
    root.querySelector('.knowledge-tabs [data-kind="rules"]').click();
    await new Promise(resolve=>setTimeout(resolve,0));
    const card=root.querySelector('[data-proposal="p1"]');
    assert.equal(card.querySelector('[data-decision="confirm"]').disabled,true);
    card.querySelector('[data-proposal-edit]').click();
    let form=root.querySelector('.knowledge-form');
    const selector=form.querySelector('[name=counterparty_id]');
    assert.equal(selector.tagName,'SELECT');
    assert.equal(selector.value,'');
    assert.ok(selector.options[1].textContent.includes('临沄数研技术有限公司'));
    await form.onsubmit({preventDefault(){},target:form});
    assert.equal(calls.filter(c=>c.method==='PUT').length,0);
    assert.ok(notices.at(-1).includes('选择'));
    selector.value='a';
    selector.onchange();
    assert.equal(form.querySelector('[data-party-warning]').hidden,true);
    assert.equal(form.querySelector('[name=valid_to]').value,'2026-12-31');
    form.querySelector('[name=content]').value='只改正文';
    await form.onsubmit({preventDefault(){},target:form});
    const saved=JSON.parse(calls.find(c=>c.method==='PUT').body);
    assert.equal(saved.metadata.counterparty_id,'a');
    assert.equal(saved.metadata.valid_to,'2026-12-31');
    assert.deepEqual(saved.metadata.custom,{kept:true});
    assert.deepEqual(saved.sources,[source]);
    assert.equal(saved.proposal_revision,2);
  }finally{
    for(const [key,value] of Object.entries(previous))globalThis[key]=value;
    dom.window.close();
  }
});
