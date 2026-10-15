import {readFile} from 'node:fs/promises';
import {join} from 'node:path';

export const endpoints = new Set(['atomic/search','atomic/query','conversation/search','conversation/query','scenario/ls','scenario/read']);
const identityHeaders=['x-team-id','x-agent-id','x-task-id','x-conversation-id','x-tdai-service-id','x-openharvey-memory-version','x-openharvey-source-event'];
const quote=value=>"'"+String(value).replaceAll("'","'\\''")+"'";

// Parse only literal shell words. No pipelines, expansion, redirection or commands.
export function words(command){
  command=command.replace(/\\\r?\n/g,'');
  let result=[],word='',mode=null,started=false;
  for(let i=0;i<command.length;i++){
    const ch=command[i];
    if(mode==="'"){if(ch==="'")mode=null;else word+=ch;continue;}
    if(mode==='"'){
      if(ch==='"'){mode=null;continue;}
      if(ch==='$'||ch==='`')throw new Error('记忆命令不允许 shell 展开');
      if(ch==='\\'&&i+1<command.length){word+=command[++i];continue;}
      word+=ch;continue;
    }
    if(ch==="'"||ch==='"'){mode=ch;started=true;continue;}
    if(ch==='\n'||ch==='\r'||/[;&|<>`$()]/.test(ch))throw new Error('记忆命令必须是单条只读 curl');
    if(ch==='\\'){if(i+1>=command.length)throw new Error('记忆命令格式无效');word+=command[++i];started=true;continue;}
    if(/\s/.test(ch)){if(started){result.push(word);word='';started=false;}continue;}
    word+=ch;started=true;
  }
  if(mode)throw new Error('记忆命令引号未闭合');
  if(started)result.push(word);
  return result;
}

export function checkedCurl(command,binding){
  if(!binding?.enabled)throw new Error('本轮未启用 TencentDB Memory');
  const args=words(command);
  if(args.shift()!=='curl')throw new Error('记忆桥接只允许 curl');
  let url,body,method='GET';
  for(let i=0;i<args.length;i++){
    const token=args[i];
    if(/^-[sSfk]+$/.test(token))continue;
    if(token==='-X'||token==='--request'){method=args[++i];continue;}
    if(token==='-H'||token==='--header'){
      const header=args[++i]||'',pos=header.indexOf(':');
      const name=header.slice(0,pos).trim().toLowerCase(),value=header.slice(pos+1).trim();
      const expected={'content-type':'application/json','x-conversation-id':binding.session_id,'x-tdai-service-id':binding.service_id};
      if(!(name in expected)||value!==expected[name])throw new Error('记忆命令身份或请求头不属于当前会话');
      continue;
    }
    if(['-d','--data','--data-raw'].includes(token)){
      if(body!==undefined)throw new Error('记忆命令只能包含一个 JSON 请求体');
      body=JSON.parse(args[++i]);continue;
    }
    if(/^https?:\/\//.test(token)&&!url){url=token;continue;}
    throw new Error('记忆命令包含不支持的 curl 参数');
  }
  if(method!=='POST'||!url||!body||typeof body!=='object'||Array.isArray(body))throw new Error('记忆桥接需要 POST JSON');
  const parsed=new URL(url),base=new URL(binding.bridge_url+'/');
  const endpoint=parsed.pathname.slice(base.pathname.length);
  if(parsed.origin!==base.origin||!parsed.pathname.startsWith(base.pathname)||!endpoints.has(endpoint)||parsed.search||parsed.hash||parsed.username||parsed.password)throw new Error('记忆命令访问了未授权地址或接口');
  for(const key of ['team_id','user_id','agent_id'])if(key in body)throw new Error('记忆请求不得覆盖业务身份');
  if('task_id' in body&&body.task_id!==binding.task_id)throw new Error('记忆请求不得切换合同任务');
  body.task_id=binding.task_id;
  return ['curl','-sf','-X','POST',quote(url),'-H',quote('Content-Type: application/json'),
    '-H',quote('x-tdai-service-id: '+binding.service_id),'-H',quote('x-conversation-id: '+binding.session_id),
    '--data-raw',quote(JSON.stringify(body))].join(' ');
}

export function checkedPrecedentCommand(command,script){
  const args=words(command);
  if(!script||args[0]!=='python3'||args[1]!==script)throw new Error('历史处置只允许固定只读脚本');
  const fields=new Map();
  for(let i=2;i<args.length;i+=2){const key=args[i],value=args[i+1];if(!['--risk-id','--artifact-id','--document-id','--blocks'].includes(key)||fields.has(key)||!value)throw new Error('历史处置参数无效');
    if(key==='--blocks'?!/^B\d+(?:,B\d+)*$/.test(value):!/^[\p{L}\p{N}_.-]{1,180}$/u.test(value))throw new Error('历史处置标识无效');fields.set(key,value);}
  const hasReport=fields.has('--artifact-id'),hasSource=fields.has('--document-id')&&fields.has('--blocks');
  if(!fields.has('--risk-id')||(hasReport&&(fields.has('--document-id')||fields.has('--blocks')))||(!hasReport&&!hasSource))throw new Error('请指定当前风险与报告或原文段落');
  return ['python3',quote(script),...args.slice(2).map((a,i)=>i%2?quote(a):a)].join(' ');
}

export default async function plugin(_input,options={}){
  async function binding(sessionID){
    if(!options.bindingDirectory||!/^[A-Za-z0-9_-]{1,180}$/.test(sessionID))throw new Error('TencentDB Memory 会话绑定缺失');
    let value;try{value=JSON.parse(await readFile(join(options.bindingDirectory,sessionID+'.json'),'utf8'));}
    catch{throw new Error('TencentDB Memory 会话绑定缺失，请重新发送当前任务');}
    if(value.session_id!==sessionID)throw new Error('TencentDB Memory 会话绑定不一致');
    return value;
  }
  return {
    'chat.headers':async(input,output)=>{
      if(input.model.providerID!=='tencentdb-memory')return;
      for(const name of identityHeaders)delete output.headers[name];
      if(input.agent!=='contract')return; // title/compaction: model forwarding only
      const value=await binding(input.sessionID);
      if(!value.enabled)throw new Error('本轮 TencentDB Memory 尚未准备就绪');
      for(const key of ['service_id','team_id','agent_id','task_id'])if(!value[key])throw new Error('TencentDB Memory 身份绑定不完整');
      Object.assign(output.headers,{'x-tdai-service-id':value.service_id,'x-team-id':value.team_id,
        'x-agent-id':value.agent_id,'x-task-id':value.task_id,'x-conversation-id':input.sessionID});
    },
    'tool.execute.before':async(input,output)=>{
      if(input.tool==='bash'&&String(output.args.command||'').includes('/scripts/recall_precedents.py')){const value=await binding(input.sessionID);if(!value.enabled||!value.contract)throw new Error('本轮未启用合同处置查询');output.args.command=checkedPrecedentCommand(output.args.command,options.precedentScript);return;}
      if(input.tool!=='bash'||!String(output.args.command||'').includes('/memory-bridge/'))return;
      output.args.command=checkedCurl(output.args.command,await binding(input.sessionID));
    },
  };
}
