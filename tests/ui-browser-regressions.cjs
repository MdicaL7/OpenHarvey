// Optional browser regression runner. Uses an already installed Playwright module;
// never installs dependencies or starts a server. Every request is intercepted.
// PLAYWRIGHT_MODULE_PATH=/path/to/playwright-core CHROME_PATH=/path/to/chrome \
//   node tests/ui-browser-regressions.cjs /tmp/ui-regression-output
const {chromium}=require(process.env.PLAYWRIGHT_MODULE_PATH||'playwright-core');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),out=path.resolve(process.argv[2]||'/tmp/openharvey-ui-regressions');
fs.mkdirSync(out,{recursive:true});
const skill={id:'fixture-skill',scope:'personal',editable:true,enabled:true,revision:1,content:{label:'Synthetic Skill',description:'fixture',body:'fixture'}};
const risk={id:'fixture-risk',scope:'personal',editable:true,enabled:true,revision:1,content:{label:'Synthetic Scheme',rules:[]}};
const provider={id:'fixture-provider',label:'Synthetic Provider',revision:1,enabled:true,models:[],base_url:'https://model.invalid/v1'};
const results=[];
function contrast(a,b){const l=c=>c.match(/[\d.]+/g).slice(0,3).map(Number).map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);const x=l(a),y=l(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH,headless:true});
 try{
 async function fixture(colorScheme='dark',width=1440){
  const context=await browser.newContext({viewport:{width,height:1000},colorScheme,serviceWorkers:'block'}),page=await context.newPage();
  const requests=[],errors=[];let failRead=false,failedJobs=true;
  page.on('pageerror',e=>errors.push(e.message));
  await context.route('**/*',async route=>{
   const u=new URL(route.request().url()),p=u.pathname,method=route.request().method();
   if(u.href==='https://api.orcarouter.ai/cdn/orca-connect-v1.js')return route.fulfill({contentType:'text/javascript',body:'/* Offline fixture: do not load the third-party widget. */'});
   if(u.hostname!=='audit.invalid'){errors.push('Unmocked origin: '+u.origin);return route.abort();}
   if(p.startsWith('/static/')){const f=path.join(root,p);if(!fs.existsSync(f))return route.fulfill({status:404,body:''});return route.fulfill({body:fs.readFileSync(f),contentType:p.endsWith('.js')?'text/javascript':p.endsWith('.css')?'text/css':p.endsWith('.svg')?'image/svg+xml':'application/octet-stream'});}
   if(p.startsWith('/api/')){
    requests.push({method,path:p});let v={};
    if(p==='/api/skills')v=[skill];else if(p.endsWith('/versions'))v=[];
    else if(p==='/api/providers')v={providers:[provider]};else if(p==='/api/risk-schemes')v=[risk];else if(p==='/api/risk-schemes/options')v={};
    else if(p==='/api/contract-memory/teams')v={items:[{id:'team-a',name:'测试团队',role:'admin'}],selected:'team-a',enterprise_admin:true};
    else if(p==='/api/contract-memory/list'){
     if(failRead)return route.fulfill({status:503,json:{detail:'fixture read failure'}});
     v={items:[{id:'fixture-entry',version:1,data:{kind:'experience',title:'测试经验',content:'仅用于隔离界面验收',conditions:[],exceptions:[]}}],jobs:failedJobs?[{id:'fixture-job',status:'failed',attempts:3}]:[]};
    }else if(!['/api/contract-memory/delete','/api/contract-memory/retry'].includes(p)&&method!=='DELETE'){errors.push('Unmocked API: '+p);return route.fulfill({status:500,json:{detail:'unmocked fixture'}});}
    return route.fulfill({json:v});
   }
   if(p==='/experience')return route.fulfill({body:fs.readFileSync(root+'/static/experience.html','utf8'),contentType:'text/html'});
   if(p==='/harness'){
    const css=[...fs.readFileSync(root+'/static/index.html','utf8').matchAll(/<link rel="stylesheet"[^>]*>/g)].map(m=>m[0]).join('');
    return route.fulfill({contentType:'text/html',body:`<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${css}<link rel="stylesheet" href="/static/connectors-ui.css"></head><body data-auth="ready"><header></header><details id="workspaceSwitcher"></details><div id="appShell"></div><script type="module">import {setupSettings} from '/static/settings-ui.js';window.auditSettings=setupSettings({notice:t=>(window.notices??=[]).push(t)});await window.auditSettings.open(new URLSearchParams(location.search).get('tab')||'skills',{user:{username:'fixture',role:'admin',capabilities:{}}});window.auditReady=true;</script></body></html>`});
   }
   return route.fulfill({status:404,body:''});
  });
  return {context,page,requests,errors,setReadError:v=>failRead=v,setFailedJobs:v=>failedJobs=v};
 }
 // Real module + real DOM event flows for all three shared-dialog callers.
 for(const tab of ['skills','risks','providers'])for(const action of ['back','close','expired','cancel','confirm']){
  const x=await fixture(),{page}=x;
  await page.goto('https://audit.invalid/harness?tab='+tab);await page.waitForFunction(()=>window.auditReady);
  if(tab==='skills')await page.locator('[data-skill-edit]').click();
  if(tab==='risks')await page.locator('[data-scheme]').click();
  await page.locator(tab==='skills'?'[data-delete-skill]':tab==='risks'?'[data-delete-scheme]':'[data-delete-provider]').click();
  await page.locator('#ohConfirmDialog').waitFor({state:'visible'});
  if(action==='back')await page.goBack();
  else if(action==='close')await page.evaluate(()=>window.auditSettings.close({historyMode:'none'}));
  else if(action==='expired')await page.evaluate(()=>document.dispatchEvent(new Event('session-expired')));
  else await page.locator(action==='confirm'?'[data-confirm-ok]':'[data-confirm-cancel]').click();
  await page.locator('#ohConfirmDialog').waitFor({state:'detached'});
  if(action==='confirm')await page.waitForFunction(()=>window.notices?.some(t=>t.includes('已删除')));
  assert.equal(x.requests.filter(r=>r.method==='DELETE').length,action==='confirm'?1:0,tab+' '+action);
  assert.deepEqual(x.errors,[]);results.push({case:'confirmation',tab,action,deletes:x.requests.filter(r=>r.method==='DELETE').length});await x.context.close();
 }
 // Error and failed-job recovery remain visible after actual click handlers.
 for(const condition of ['failed-job','read-error','clean']){
  const x=await fixture(),{page}=x;await page.goto('https://audit.invalid/experience');await page.locator('[data-action=delete]').waitFor();
  x.setReadError(condition==='read-error');x.setFailedJobs(condition==='failed-job');
  await page.locator('[data-action=delete]').click();const refreshed=page.waitForResponse(r=>new URL(r.url()).pathname==='/api/contract-memory/list');await page.locator('#confirmOk').click();await refreshed;
  await page.waitForFunction(()=>document.getElementById('status').dataset.kind!=='loading'&&document.getElementById('status').textContent!=='正在读取…');
  const kind=await page.locator('#status').getAttribute('data-kind');assert.equal(kind,condition==='failed-job'?'warn':condition==='read-error'?'error':'success');
  if(condition==='failed-job')assert.equal(await page.locator('#status button').count(),1);
  assert.deepEqual(x.errors,[]);results.push({case:'experience-status',condition,kind});await x.context.close();
 }
 for(const color of ['light','dark'])for(const width of [1440,390]){
  const x=await fixture(color,width),{page}=x;
  const palette=[];
  async function checkButton(selector){const button=page.locator(selector).first();for(const state of ['normal','hover','focus','disabled']){
   await button.evaluate(el=>{el.disabled=false;el.blur();});await page.mouse.move(0,0);
   if(state==='hover')await button.hover();if(state==='focus')await button.focus();if(state==='disabled')await button.evaluate(el=>el.disabled=true);
   const style=await button.evaluate(el=>{const s=getComputedStyle(el);return {color:s.color,background:s.backgroundColor,opacity:s.opacity,outline:s.outlineStyle};});
   const ratio=contrast(style.color,style.background);assert.ok(ratio>=4.5,`${color} ${width} ${selector} ${state}: ${ratio}`);assert.equal(style.opacity,'1');palette.push({selector,state,...style,contrast:ratio});
  }await button.evaluate(el=>el.disabled=false);}
  await page.goto('https://audit.invalid/experience');await page.locator('[data-action=delete]').waitFor();await checkButton('#add');
  await page.screenshot({path:path.join(out,`experience-${color}-${width}.png`)});
  await page.goto('https://audit.invalid/harness');await page.waitForFunction(()=>window.auditReady);await checkButton('[data-new-skill]');
  await page.evaluate(()=>{const f=document.createElement('div');f.className='feishu-card';f.innerHTML='<button class="primary">Fixture connect</button>';document.querySelector('#settingsPage').append(f);});await checkButton('.feishu-card button');
  await page.screenshot({path:path.join(out,`settings-${color}-${width}.png`)});
  await page.evaluate(async()=>{await window.auditSettings.close({historyMode:'none'});const {setupMaterials}=await import('/static/materials-ui.js');setupMaterials({context:()=>({}),notice:()=>{},refresh:()=>{},openSource:()=>{}});document.querySelector('.materials-dialog').showModal();});
  const layout=await page.locator('.materials-dialog').evaluate(d=>({width:d.getBoundingClientRect().width,overflow:d.scrollWidth>d.clientWidth,controls:[...d.querySelectorAll('.materials-toolbar input,.materials-toolbar select')].map(e=>{const r=e.getBoundingClientRect();return {width:r.width,height:r.height,y:r.y,right:r.right};})}));
  assert.equal(layout.overflow,false);assert.ok(layout.width<=width-32);assert.ok(layout.controls.every(c=>c.height===34&&c.right<=width));
  if(width>600){assert.equal(layout.width,850);assert.equal(new Set(layout.controls.map(c=>c.y)).size,1);assert.ok(layout.controls[1].width<200);}
  else {assert.ok(layout.controls[0].y<layout.controls[1].y);assert.equal(layout.controls[1].y,layout.controls[2].y);}
  await page.screenshot({path:path.join(out,`materials-${color}-${width}.png`)});assert.deepEqual(x.errors,[]);
  results.push({case:'visual',color,width,palette,layout});await x.context.close();
 }
 }finally{await browser.close();fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify(results,null,2));}
 console.log(JSON.stringify({passed:results.length,output:out}));
})().catch(e=>{console.error(e);process.exitCode=1;});
