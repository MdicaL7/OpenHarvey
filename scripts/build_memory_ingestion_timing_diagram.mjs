import fs from 'node:fs';

// Current implementation, rather than a proposed task-end extraction design.
let seq=0, region='ingestion';
const elements=[];
const C={ink:'#243244',muted:'#596979',blue:'#326ca5',green:'#26724b',orange:'#a46120',purple:'#78569f',line:'#bac8d6'};
function base(type,x,y,width,height,o={}) {
  return {id:`timing-${++seq}`,type,x,y,width,height,angle:0,strokeColor:o.color||C.ink,backgroundColor:o.fill||'transparent',fillStyle:'solid',strokeWidth:1.5,strokeStyle:o.dashed?'dashed':'solid',roughness:0,opacity:100,groupIds:[],frameId:null,index:null,roundness:type==='rectangle'?{type:3}:null,seed:seq*5431,version:1,versionNonce:seq*7523,isDeleted:false,boundElements:null,updated:1791763200000,link:null,locked:false,customData:{region}};
}
function text(x,y,width,value,o={}) {
  const size=o.size||24;
  const e={...base('text',x,y,width,value.split('\n').length*size*1.35,o),fontSize:size,fontFamily:2,text:value,originalText:value,textAlign:o.align||'left',verticalAlign:'middle',containerId:o.containerId||null,autoResize:true,lineHeight:1.35};
  if(o.center)e.customData.center=o.center;
  elements.push(e);return e;
}
function box(x,y,w,h,value,o={}) {
  const e=base('rectangle',x,y,w,h,o);elements.push(e);
  if(value){const t=text(x+18,y+18,w-36,value,{...o,align:o.align||'center',containerId:e.id,center:{x:x+w/2,y:y+h/2}});e.boundElements=[{id:t.id,type:'text'}];}
  return e;
}
function arrow(points,o={}) {
  const [x,y]=points[0], ps=points.map(([a,b])=>[a-x,b-y]);
  const xs=ps.map(p=>p[0]),ys=ps.map(p=>p[1]);
  elements.push({...base('arrow',x,y,Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys),o),points:ps,startBinding:null,endBinding:null,startArrowhead:null,endArrowhead:'arrow',elbowed:false});
}
function panel(y,h,title,sub) {
  box(40,y,2440,h,null,{fill:'#ffffff',color:C.line});
  text(80,y+25,2360,title,{size:36});text(80,y+84,2360,sub,{size:24,color:C.muted});
}
text(70,35,2380,'合同记忆：哪些内容进入、何时提炼、何时正式生效',{size:43});
text(72,106,2370,'OpenHarvey × TencentDB Memory  ·  当前 contract 模式实现  ·  2026-10-12  ·  长期记忆 L0–L3',{size:24,color:C.muted});
box(80,162,520,55,'蓝：业务输入与传递',{fill:'#eaf1fb',color:C.blue});
box(630,162,520,55,'橙：自动提炼 / 候选',{fill:'#fff1df',color:C.orange});
box(1180,162,520,55,'绿：已确认 / 可正式召回',{fill:'#e5f3e9',color:C.green});
box(1730,162,680,55,'灰虚线：当前不自动进入',{fill:'#f4f6f8',color:C.muted,dashed:true});

panel(250,1250,'01  OpenHarvey → Proxy / Core：内容和进入时机','仅选择 TencentDB Memory provider 的本机业务请求自动记录；普通 provider、标题与压缩等辅助请求不记录。');
const cols=[100,730,1260,1850], widths=[550,450,510,560];
['OpenHarvey 侧内容','进入时机','传递接口 / 组件','Core 中的落点'].forEach((v,i)=>text(cols[i]+10,390,widths[i]-20,v,{size:28,color:C.muted}));
function row(y,values,colors=[C.blue,C.blue,C.blue,C.purple],fills=['#eaf1fb','#f5f8fc','#eaf1fb','#f0ebf7'],dashed=false) {
  values.forEach((v,i)=>box(cols[i],y,widths[i],145,v,{color:colors[i],fill:fills[i],size:24,dashed}));
  for(let i=0;i<3;i++)arrow([[cols[i]+widths[i]+8,y+72],[cols[i+1]-12,y+72]],{color:dashed?C.muted:C.line,dashed});
}
row(460,[
  '会话身份 ＋ 合同来源元数据\nTeam / User / Agent / Task / Session\n文档 ID、版本、段落引用与哈希',
  '每轮调度前\nOpenHarvey prepare()\n读取身份及合同来源信息',
  'POST contract-memory/context → Core\n会话绑定文件 → OpenCode 插件\nchat.headers → Proxy',
  '保存来源上下文和请求归属\n元数据本身不含合同全文\n这一步不触发提炼'
]);
row(650,[
  '用户输入 ＋ 助手输出\n实际业务对话\n不是助手口头声明的执行事实',
  '一次模型响应结束后\n流式：收尾后异步提交\n非流式：成功返回后提交',
  'OpenCode → Proxy 记录器\nPOST /v3/conversation/add\n工具续轮助手输出：capture-events',
  'L0：原始对话记录\n新增记录去重后持久化\n新增成功 → 提炼任务入队'
]);
row(840,[
  '实际工具结果\n原生 read 返回的合同段落\n成果保存的真实回执等',
  '工具执行后\n结果随下一次模型请求\n经过 Proxy 时收集',
  'OpenCode 请求中的 tool 消息\nProxy 按调用 ID / 名称 / 路径识别\nPOST contract-memory/capture-tools',
  'L0：工具结果与来源上下文\n已有结果按来源去重\n新增成功 → 提炼任务入队'
]);
row(1030,[
  '用户确认 / 手动新增 / 修改\n“经验与偏好”面板\n团队共享与审核操作',
  '点击确认或保存\n团队版本在管理员批准后\n不是每轮对话自动发布',
  '浏览器 → OpenHarvey\n/api/contract-memory/*\n后端 → Core 受控写入接口',
  '正式条目 / 版本 / 审计\n新增或确认经验可再触发 L3\n直接修改不走自动覆盖'
],[C.green,C.green,C.green,C.green],['#e5f3e9','#f1f8f3','#e5f3e9','#e5f3e9']);
row(1220,[
  '只上传但尚未读取的合同全文\n未进入工具结果的文档段落\n现有制度 / 风险库未读取部分',
  '上传本身\n不会自动启动全文沉淀\n没有单独的文档导入触发器',
  'Core 不主动下载合同\n不扫描 OpenHarvey 文件目录\n需 Agent 实际读取才有原文输入',
  '不自动成为 L0 合同原文\n文档校验元数据可已存在\n元数据 ≠ 全文内容'
],[C.muted,C.muted,C.muted,C.muted],['#f4f6f8','#f4f6f8','#f4f6f8','#f4f6f8'],true);
text(100,1410,2300,'边界：助手的合同转述只能作为消息依据；合同事实需匹配真实 read 输出、文档版本与段落哈希。',{size:25,color:C.purple});

region='pipeline';
panel(1540,1270,'02  L0–L3：后台模型沉淀的触发点和输入','Core 决定自动提炼时机；Hub 不负责触发。当前没有“达到 N 轮 / 会话空闲 / 合同审查完成”的门槛。');
box(100,1720,580,155,'触发事件：L0 新记录写入成功\n对话 / 工具 / 助手续轮都可触发\n仅重复记录不新建任务',{fill:'#eaf1fb',color:C.blue,size:27});
box(850,1720,650,155,'Core 后台任务队列\n立即尝试 tick；另每 3 秒检查\n同会话已有 pending 任务时合并',{fill:'#fff1df',color:C.orange,size:27});
box(1680,1720,730,155,'不是“3 秒完成一次提炼”\n受排队、模型耗时与重试影响\n失败自动尝试最多 3 次，可手动重试',{fill:'#f5f7fa',color:C.muted,size:26});
arrow([[695,1797],[835,1797]],{color:C.orange});arrow([[1515,1797],[1665,1797]],{color:C.line});
box(100,2000,540,250,'L0  原始记录\n来源：对话 ＋ 实际工具结果\n保存消息及证据上下文\n不调用提炼模型\n上传的全文不自动入库',{fill:'#eaf1fb',color:C.blue,size:26});
box(850,2000,650,250,'L1  原子事实与判断记录\n来源：本会话 L0 ＋ 同 Task 历史 L1\n工具仅选合格 read / saved:true 回执\n模型区分事实、意见、建议、决定等\n核验来源；保留条件与有效状态',{fill:'#fff1df',color:C.orange,size:26});
arrow([[1175,1890],[1175,1985]],{color:C.orange});
arrow([[655,2125],[835,2125]],{color:C.orange});text(690,2078,140,'模型抽取',{size:22,color:C.orange});
box(1680,1950,730,200,'L2  过往经验候选\n时机：同一任务完成 L1 后，有合适材料\n来源：本会话有效 L1，排除偏好\n原文事实须有已核验文档依据',{fill:'#fff1df',color:C.orange,size:26});
box(1680,2250,730,200,'L3  工作偏好 / 约定候选\n时机：有明确偏好或已有确认经验时\n来源：本会话 L1 偏好 ＋ 当前个人正式经验\n本轮未确认的 L2 候选不作原则依据',{fill:'#fff1df',color:C.orange,size:26});
arrow([[1515,2070],[1665,2070]],{color:C.orange});
arrow([[1515,2190],[1580,2190],[1580,2350],[1665,2350]],{color:C.orange});
box(100,2350,1400,185,'额外触发：用户确认经验 / 手动新增经验\nCore 另排队 profile 任务 → 用已有个人确认经验生成 L3 候选\n手动新增偏好不再触发这类任务；修改经验也不自动覆盖或重提炼',{fill:'#e5f3e9',color:C.green,size:27});
arrow([[1515,2425],[1665,2425]],{color:C.green});
box(100,2640,2310,100,'L1 是后台记录；L2 / L3 自动输出先保存到草稿区。一次任务可以没有候选，也可能分多次处理新增记录。',{fill:'#fff7ec',color:C.orange,size:26});
arrow([[2045,2165],[2460,2165],[2460,2590],[2045,2590],[2045,2625]],{color:C.orange});
arrow([[2045,2465],[2045,2625]],{color:C.orange});

region='confirmation';
panel(2850,1130,'03  从“已保存”到“可正式召回”：人确认，界面只管理','当前合同数据在 Core 专用 SQLite；原有 Memory Hub 未适配这一数据平面，不能假定旧 Hub 能展示合同候选。');
box(100,3040,560,200,'L2 / L3 草稿已持久化\n不进入正式经验 / 偏好召回或注入\nOpenHarvey 每 8 秒刷新建议\n“有 N 条建议记住”',{fill:'#fff1df',color:C.orange,size:27});
box(870,3040,650,200,'用户确认 / 修改后确认\n或手动新增并保存\nCore 校验身份、版本与操作幂等\n正式数据和审计落盘后返回回执',{fill:'#eaf1fb',color:C.blue,size:26});
box(1740,3040,670,200,'个人正式经验 / 工作偏好\nTeam ＋ Agent ＋ User 隔离\n后续 Proxy 注入 / 只读桥接召回\n删除立即退出正式召回',{fill:'#e5f3e9',color:C.green,size:27});
arrow([[675,3140],[855,3140]],{color:C.blue});arrow([[1535,3140],[1725,3140]],{color:C.green});
box(1740,3370,670,150,'共享申请 → 团队管理员批准\n独立团队版本才进入团队召回\n共享不开放原合同和个人对话',{fill:'#e5f3e9',color:C.green,size:27});
arrow([[2075,3255],[2075,3355]],{color:C.green});
box(100,3370,1420,150,'“不记录” / 删除 → 同来源抑制再次生成\n自动后台不能覆盖人工正式版本，只能提出新建议\n确认记忆 ≠ 合同事项已批准；L0 / L1 原始历史仍保留',{fill:'#f5f7fa',color:C.muted,size:27});
box(100,3620,730,225,'OpenHarvey\n发出业务请求、绑定身份与来源\n提供确认 / 管理 / 审核界面\n不负责当前自动提炼调度',{fill:'#eaf1fb',color:C.blue,size:27});
box(890,3620,730,225,'Memory Core（独立组件）\n保存 L0 / L1 / 草稿 / 正式条目\n调度模型提炼、校验与持久化\n是当前合同记忆的事实来源',{fill:'#f0ebf7',color:C.purple,size:27});
box(1680,3620,730,225,'Memory Hub（旧部署面板）\n是界面，不是记忆存储引擎\n本轮未接入合同专用数据平面\n合同管理使用 /experience',{fill:'#f4f6f8',color:C.muted,dashed:true,size:27});
text(100,3880,2300,'读取边界：L0 / L1 仍有受权限约束的查询接口；“未确认不召回”特指正式 L2 / L3 经验与偏好。',{size:24,color:C.muted});
const scene={type:'excalidraw',version:2,source:'https://excalidraw.com',elements,appState:{viewBackgroundColor:'#f7f9fc',gridSize:null},files:{}};
fs.mkdirSync('docs/diagrams',{recursive:true});
const output=process.argv[2]||'docs/diagrams/contract-memory-ingestion-timing.excalidraw';
fs.writeFileSync(output,JSON.stringify(scene,null,2)+'\n');
console.log(`${elements.length} editable elements → ${output}`);
