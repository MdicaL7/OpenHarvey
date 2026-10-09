import {build} from 'esbuild';
await build({entryPoints:['scripts/tencentdb-plugin/runtime.js'],outfile:'runtime/plugins/tencentdb-memory.js',
  bundle:true,platform:'node',format:'esm',target:'node20',minify:true,legalComments:'eof'});
