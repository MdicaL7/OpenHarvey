import {createMemoryTool,createKnowledgeTool} from './tool.js';
import {openHarveyExecute,openHarveyKnowledgeExecute} from './openharvey.js';

export default async function memoryPlugin(){
  return {tool:{memory:createMemoryTool({execute:openHarveyExecute}),
    knowledge:createKnowledgeTool({execute:openHarveyKnowledgeExecute})}};
}
