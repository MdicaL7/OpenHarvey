import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,rm,readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {tmpdir} from 'node:os';
import plugin,{checkedCurl} from '../scripts/tencentdb-plugin/index.js';
import * as bundled from '../runtime/plugins/tencentdb-memory.js';

const bind=sid=>({enabled:true,session_id:sid,service_id:'default',team_id:'team',agent_id:'agent',task_id:'task-'+sid,bridge_url:'http://127.0.0.1:8096/memory-bridge/v3'});
const command=(sid,url='http://127.0.0.1:8096/memory-bridge/v3/atomic/search',body={query:'条件;需要保留',limit:5})=>
 `curl -sfk -X POST ${url} -H 'Content-Type: application/json' -H 'x-conversation-id: ${sid}' -H 'x-tdai-service-id: default' -d '${JSON.stringify(body)}'`;

test('runtime bundle has only the plugin factory export accepted by OpenCode',()=>{
 assert.deepEqual(Object.keys(bundled),['default']);assert.equal(typeof bundled.default,'function');
});

test('interleaved conversations have their own identity; title and direct provider have no memory headers',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'tdai-headers-'));
 try{
  for(const sid of ['ses_a','ses_b'])await writeFile(join(dir,sid+'.json'),JSON.stringify(bind(sid)));
  const hooks=await plugin({}, {bindingDirectory:dir});
  const request=async(sid,agent='contract',providerID='tencentdb-memory')=>{
   const output={headers:{}};await hooks['chat.headers']({sessionID:sid,agent,model:{providerID}},output);return output.headers;
  };
  const results=await Promise.all([request('ses_a'),request('ses_b'),request('ses_a')]);
  assert.equal(results[0]['x-conversation-id'],'ses_a');assert.equal(results[1]['x-task-id'],'task-ses_b');assert.deepEqual(results[0],results[2]);
  assert.deepEqual(await request('ses_a','title'),{});assert.deepEqual(await request('ses_a','compaction'),{});
  assert.deepEqual(await request('ses_a','contract','direct'),{});
  await assert.rejects(request('missing'),/绑定缺失/);
  await writeFile(join(dir,'ses_a.json'),JSON.stringify({...bind('ses_a'),enabled:false}));
  await assert.rejects(request('ses_a'),/未准备就绪/);
 }finally{await rm(dir,{recursive:true,force:true});}
});

test('curl bridge retains literal queries and rejects identity, task, URL, file and shell escapes',()=>{
 const safe=checkedCurl(command('ses_a'),bind('ses_a'));
 assert.match(safe,/task-ses_a/);assert.match(safe,/条件;需要保留/);assert.doesNotMatch(safe,/-sfk/);
 for(const unsafe of [
  command('ses_a','http://example.com/memory-bridge/v3/atomic/search'),
  command('ses_a','http://127.0.0.1:8096/memory-bridge/v3/atomic/delete'),
  command('ses_b'),command('ses_a',undefined,{query:'x',task_id:'other'}),
  command('ses_a',undefined,{query:'x',user_id:'other'}),
  command('ses_a')+'; echo stolen',command('ses_a')+' | cat',command('ses_a')+' -o /tmp/secret',
  `curl -sfk -X POST http://127.0.0.1:8096/memory-bridge/v3/atomic/search -d @/tmp/secret`,
  command('ses_a').replace('application/json','text/plain'),
  command('ses_a').replace('条件;需要保留','$(cat /tmp/secret)').replace("-d '",'-d "').replace(/'$/,'"'),
 ])assert.throws(()=>checkedCurl(unsafe,bind('ses_a')));
 assert.throws(()=>checkedCurl(command('ses_a'),{...bind('ses_a'),enabled:false}),/未启用/);
});

test('retired Memory UI is absent and shared material/redline Labs remain',async()=>{
 const source=await readFile(new URL('../static/labs-ui.js',import.meta.url),'utf8');
 assert.match(source,/data-materials-toggle/);assert.match(source,/redlineLabsHTML/);
 assert.doesNotMatch(source,/\/api\/memories|data-memory-toggle|memory-enabled|memoryReceiptHTML/);
});
