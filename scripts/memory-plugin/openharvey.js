import {readFile} from 'node:fs/promises';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {sendHttp,sendExchange} from './transport.js';

const hash=value=>createHash('sha256').update(value).digest('hex');

/** OpenHarvey's execution identity and transport adapter for the portable tool. */
export async function openHarveyExecute(args,context){
  const cap=JSON.parse(await readFile(join(context.directory,'.memory-capability'),'utf8'));
  if(cap.session_id!==context.sessionID)throw new Error('Memory session does not match this execution');
  const operation={action:args.action,...(args.id?{id:args.id}:{}),...(args.revision!==undefined?{revision:args.revision}:{}),...(args.content!==undefined?{content:args.content}:{})};
  const req={execution_id:cap.execution_id,thread_id:cap.thread_id,session_id:context.sessionID,message_id:context.messageID,...operation};
  req.request_id=hash(JSON.stringify(req));
  if(context.abort?.aborted)throw new Error('Memory operation cancelled');
  return cap.transport==='http' ? sendHttp(cap,req,context.abort) : sendExchange(req,context.abort);
}
