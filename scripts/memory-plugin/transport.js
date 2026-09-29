import {readFile,writeFile,rename,mkdir} from 'node:fs/promises';
import {join} from 'node:path';

const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));

export async function sendHttp(cap,req,signal){
  const response=await fetch(cap.url,{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+cap.token},body:JSON.stringify(req),signal});
  const value=await response.json();
  return response.ok?value:{saved:false,request_id:req.request_id,error:value.detail||'Memory unavailable'};
}

export async function sendExchange(req,signal,{exchange='/workspace/exchange/memory',timeout=90000}={}){
  await mkdir(exchange,{recursive:true});
  const path=join(exchange,req.request_id),receipt=path+'.receipt.json';
  try{return JSON.parse(await readFile(receipt,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
  await writeFile(path+'.tmp',JSON.stringify(req),{mode:0o600});
  await rename(path+'.tmp',path+'.request.json');
  const deadline=Date.now()+timeout;
  while(Date.now()<deadline&&!signal?.aborted){
    try{return JSON.parse(await readFile(receipt,'utf8'));}catch(e){if(e.code!=='ENOENT')throw e;}
    await wait(400);
  }
  return {saved:false,pending:true,request_id:req.request_id,error:'Memory result not confirmed. Check saved memories before retrying.'};
}
