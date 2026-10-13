import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const read=name=>fs.readFileSync(new URL('../static/'+name,import.meta.url),'utf8').replace(/^import .*;\n/gm,'').replaceAll('export ','');
class Element {
 constructor(){this.dataset={};this.children=[];this.hidden=false;this.isConnected=true;this.disabled=false;this.classList={toggle(){}};}
 set textContent(value){this.text=value;this.children=[];}get textContent(){return this.text||'';}
 set innerHTML(value){this.html=value;this.children=[];}get innerHTML(){return this.html||'';}
 append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;this.html='';}
 removeAttribute(name){if(name==='data-kind')delete this.dataset.kind;}setAttribute(){}focus(){}
}
function experience(){
 const elements={},requests=[],$=id=>elements[id]??=new Element();
 const state={response:{items:[],jobs:[{id:'failed-job',status:'failed',attempts:3}]},error:null,read:null};
 const context={document:{getElementById:$,querySelectorAll:()=>[],createElement:()=>new Element()},location:{search:''},URLSearchParams,crypto:{randomUUID:()=> 'fixture-operation'},
  api:async(path,options)=>{requests.push({path,options});if(options)return {};if(state.read)return state.read();if(state.error)throw state.error;return state.response;}};
 vm.createContext(context);vm.runInContext(read('experience.js').replace('void init();','')+'\n'+read('loading-ui.js')+'\nteam="team-a";items=[{id:"candidate-a",version:3,data:{kind:"experience",title:"fixture"}}];',context);
 return {state,requests,$,context,act:async()=>{const b=new Element();b.dataset={id:'candidate-a',action:'confirm'};await $('content').onclick({target:{closest:()=>b}});}};
}
test('confirm preserves failed-job warning and recovery, including the request version',{timeout:2000},async()=>{
 const x=experience();await x.act();assert.equal(x.$('status').dataset.kind,'warn');assert.match(x.$('status').textContent,/整理未完成/);assert.equal(x.$('status').children.length,1);
 assert.equal(x.requests[0].options.body.version,3);assert.equal(x.requests[0].options.body.team_id,'team-a');
});
test('successful mutation cannot conceal a subsequent list failure',{timeout:2000},async()=>{
 const x=experience();x.state.error=Error('fixture read failure');await x.act();assert.equal(x.$('status').dataset.kind,'error');assert.equal(x.$('status').textContent,'fixture read failure');
});
test('retry retains another failed job and its recovery action',{timeout:2000},async()=>{
 const x=experience();await vm.runInContext('load()',x.context);await x.$('status').children[0].onclick();assert.equal(x.$('status').dataset.kind,'warn');assert.equal(x.$('status').children.length,1);assert.match(x.requests[1].path,/\/retry$/);
});
test('retry surfaces refresh failure instead of acknowledging completed refresh',{timeout:2000},async()=>{
 const x=experience();await vm.runInContext('load()',x.context);x.state.error=Error('retry refresh failed');await x.$('status').children[0].onclick();assert.equal(x.$('status').dataset.kind,'error');assert.equal(x.$('status').textContent,'retry refresh failed');
});
test('clean refresh displays the successful operation acknowledgement',{timeout:2000},async()=>{
 const x=experience();x.state.response={items:[],jobs:[]};await x.act();assert.equal(x.$('status').dataset.kind,'success');assert.match(x.$('status').textContent,/已确认记住/);
});
test('a superseded refresh cannot overwrite the current warning with old success',{timeout:2000},async()=>{
 const x=experience();let release;let first=true;x.state.read=()=>first?(first=false,new Promise(r=>release=r)):Promise.resolve(x.state.response);
 const old=vm.runInContext('load("old success")',x.context);await vm.runInContext('load()',x.context);release({items:[],jobs:[]});await old;assert.equal(x.$('status').dataset.kind,'warn');assert.equal(x.$('status').children.length,1);
});
function confirmation(){
 const nodes={},trigger=new Element(),dialogs=[];
 const context={tr:x=>x,document:{activeElement:trigger,getElementById:()=>null,body:{append(el){dialogs.push(el);}},createElement:()=>{
  const el=new Element();el.querySelector=sel=>nodes[sel]??=new Element();el.showModal=()=>el.open=true;el.close=value=>{el.open=false;el.returnValue=value;el.onclose?.();};el.remove=()=>el.isConnected=false;return el;
 }}};
 vm.createContext(context);vm.runInContext(read('confirm-dialog.js'),context);
 return {context,dialogs,trigger,ask:options=>context.confirmDialog(options),cancel:()=>context.cancelConfirmDialog()};
}
test('view cancellation settles false and removes the body-level modal',{timeout:2000},async()=>{
 const x=confirmation(),result=x.ask({});x.cancel();assert.equal(await result,false);assert.equal(x.dialogs[0].open,false);assert.equal(x.dialogs[0].isConnected,false);
});
test('confirmation from an invalidated view cannot authorize the continuation',{timeout:2000},async()=>{
 const x=confirmation();let current=true;const result=x.ask({isCurrent:()=>current});current=false;x.dialogs[0].close('confirm');assert.equal(await result,false);
});
test('replacing a pending dialog cancels its promise without settling the replacement',{timeout:2000},async()=>{
 const x=confirmation(),first=x.ask({}),old=x.dialogs[0],staleClose=old.onclose,second=x.ask({});assert.equal(await first,false);staleClose();assert.equal(x.dialogs[1].open,true);x.dialogs[1].close('confirm');assert.equal(await second,true);
});
test('already invalid view never opens a destructive confirmation',{timeout:2000},async()=>{
 const x=confirmation();assert.equal(await x.ask({isCurrent:()=>false}),false);assert.equal(x.dialogs.length,0);
});
