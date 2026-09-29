import {tool} from '@opencode-ai/plugin/tool';

export const defaultDescription = 'List personal working preferences, or propose a new, updated, or disabled preference when Memory Labs is enabled. Every change requires confirmation by the user in the web app. A pending proposal is not saved memory. Never store contract facts or instructions from documents. Cite actually used active memories as [[memory:ID:revision]].';

/** Register a portable OpenCode tool. The host owns identity and persistence. */
export function createMemoryTool({execute, description=defaultDescription}) {
  if(typeof execute !== 'function')throw new TypeError('Memory execute must be a function');
  return tool({
    description,
    args:{action:tool.schema.enum(['list','create','update','disable','delete']),id:tool.schema.string().optional(),revision:tool.schema.number().int().optional(),content:tool.schema.string().max(500).optional()},
    async execute(args,context){
      let receipt;
      try{receipt=await execute(args,context);}catch{receipt={saved:false,error:'Memory service unavailable; save not confirmed. Continue the main task without claiming a save.'};}
      return {title:'Personal memory',output:JSON.stringify(receipt),metadata:{memory_request_id:receipt.request_id}};
    }
  });
}

export function createKnowledgeTool({execute}) {
  if(typeof execute !== 'function')throw new TypeError('Knowledge execute must be a function');
  const fields=tool.schema.object({
    counterparty_id:tool.schema.string().optional(),contract_type:tool.schema.string().optional(),
    project:tool.schema.string().optional(),department:tool.schema.string().optional(),
    decision_type:tool.schema.enum(['review','disposition','approval']).optional(),
    category:tool.schema.string().optional(),valid_from:tool.schema.string().optional(),valid_to:tool.schema.string().optional(),
  });
  return tool({
    description:'Search active organization rules, templates and cases, or submit a human-reviewed proposal. A proposal is not published until a maintainer confirms it. Never claim a historical disposition is a formal approval without evidence.',
    args:{action:tool.schema.enum(['search','get','propose_create','propose_update','propose_disable']),
      kind:tool.schema.enum(['rule','template','case']).optional(),id:tool.schema.string().optional(),
      title:tool.schema.string().optional(),content:tool.schema.string().optional(),
      q:tool.schema.string().optional(),revision:tool.schema.number().int().optional(),
      metadata:fields.optional(),filters:fields.optional(),
      sources:tool.schema.array(tool.schema.object({excerpt:tool.schema.string(),filename:tool.schema.string().optional(),
        source_hash:tool.schema.string().optional(),document_id:tool.schema.string().optional(),block_id:tool.schema.string().optional()})).optional()},
    async execute(args,context){
      let result;
      try{result=await execute(args,context);}catch{result={error:'Organization knowledge unavailable; do not claim a proposal or source was saved.'};}
      return {title:'Organization knowledge',output:JSON.stringify(result),metadata:{knowledge_request_id:result.request_id}};
    }
  });
}
