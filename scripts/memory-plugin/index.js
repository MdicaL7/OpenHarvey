import {createMemoryTool} from './tool.js';
import {openHarveyExecute} from './openharvey.js';

export default async function memoryPlugin(){
  return {tool:{memory:createMemoryTool({execute:openHarveyExecute})}};
}
