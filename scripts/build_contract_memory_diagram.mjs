import fs from 'node:fs';
let seq=0,region='mapping';const els=[];const C={ink:'#243244',muted:'#596979',blue:'#336da8',green:'#28734b',orange:'#a7601a',purple:'#78569f',line:'#bdc9d5'};
function base(type,x,y,w,h,o={}){return{id:`contract-${++seq}`,type,x,y,width:w,height:h,angle:0,strokeColor:o.color||C.ink,backgroundColor:o.fill||'transparent',fillStyle:'solid',strokeWidth:1.5,strokeStyle:o.dashed?'dashed':'solid',roughness:0.5,opacity:100,groupIds:[],frameId:null,index:null,roundness:type==='rectangle'?{type:3}:null,seed:seq*5431+11,version:1,versionNonce:seq*7523+8,isDeleted:false,boundElements:null,updated:1791504000000,link:null,locked:false,customData:{region}};}
function text(x,y,w,value,o={}){const size=o.size||23;const e={...base('text',x,y,w,value.split('\n').length*size*1.35,o),fontSize:size,fontFamily:2,text:value,originalText:value,textAlign:o.align||'left',verticalAlign:'middle',containerId:o.containerId||null,autoResize:true,lineHeight:1.35};if(o.center)e.customData.center=o.center;els.push(e);return e;}
function box(x,y,w,h,value,o={}){const e=base('rectangle',x,y,w,h,o);els.push(e);if(value){const t=text(x+15,y+15,w-30,value,{...o,align:'center',containerId:e.id,center:{x:x+w/2,y:y+h/2}});e.boundElements=[{type:'text',id:t.id}];}return e;}
function arrow(points,label,o={}){const [x,y]=points[0],ps=points.map(([px,py])=>[px-x,py-y]);const xs=ps.map(p=>p[0]),ys=ps.map(p=>p[1]);els.push({...base('arrow',x,y,Math.max(...xs)-Math.min(...xs),Math.max(...ys)-Math.min(...ys),o),points:ps,startBinding:null,endBinding:null,startArrowhead:null,endArrowhead:'arrow',elbowed:false});if(label)text(o.lx,o.ly,o.lw||300,label,{size:o.size||21,color:o.color||C.muted});}
function panel(y,h,title,sub){box(50,y,2260,h,null,{fill:'#ffffff',color:C.line});text(90,y+28,2170,title,{size:35});text(90,y+88,2170,sub,{size:22,color:C.muted});}
text(70,40,2220,'OpenHarvey × TencentDB Memory · 合同记忆映射与确认',{size:43});
text(72,108,2220,'contract-v1  ·  2026-10-10  ·  独立组件 / SQLite / 本机实验  ·  长期记忆 L0–L3',{size:23,color:C.muted});
box(80,165,500,50,'蓝：OpenHarvey 业务对象',{fill:'#eaf1fb',color:C.blue,size:22});box(610,165,500,50,'绿：上游身份模型复用',{fill:'#e5f3e9',color:C.green,size:22});box(1140,165,500,50,'橙：contract 新增行为',{fill:'#fff0dc',color:C.orange,size:22});
panel(250,790,'01  身份与权限：同一用户，多团队分别管理','企业管理员管理团队；正常 Memory User 不升级为 system_admin。合同原文、对话、成果仍默认本人可见。');
const ys=[440,580,720,860],left=['Organization · 企业\n下设多个业务团队','User · 应用用户\n一个人可加入多个团队','Team · 业务团队\nadmin / member 分别配置','合同空间 / 对话\n一份合同，多段会话'],right=['应用保存企业边界\nTeam A、Team B 分别映射','Memory User · normal\n跨团队沿用同一个身份','Memory Team ＋ 单一合同 Agent\n每个团队一个助手','Task / Conversation\n合同→Task；对话→Conversation'];
for(let i=0;i<4;i++){box(130,ys[i],710,105,left[i],{fill:'#eaf1fb',color:C.blue,size:25});box(1130,ys[i],1030,105,right[i],{fill:'#e5f3e9',color:C.green,size:25});arrow([[855,ys[i]+52],[1115,ys[i]+52]],null,{color:C.line});}
region='data';panel(1080,930,'02  数据映射：自动整理与正式记忆分开','contract 专用范围覆盖存储、任务、查询与注入；旧 chat/code 数据不自动迁入或召回。');
box(130,1280,390,145,'L0 原始记录\n输入 / 输出 / 工具结果\n文档版本与段落引用',{fill:'#eaf1fb',color:C.blue,size:24});
box(670,1280,390,145,'L1 原子记录\n事实 / 意见 / 决定\n条件 / 状态 / 来源',{fill:'#eaf1fb',color:C.blue,size:24});
box(1210,1280,430,145,'L2 经验候选\n按风险主题归纳\n保留一次性限制',{fill:'#fff0dc',color:C.orange,size:24});
box(1790,1280,390,145,'L3 约定候选\n明确长期偏好\n或已确认经验',{fill:'#fff0dc',color:C.orange,size:24});
arrow([[535,1350],[655,1350]],null);arrow([[1075,1350],[1195,1350]],null);
arrow([[1060,1270],[1060,1220],[1985,1220],[1985,1265]],'明确长期偏好',{lx:1410,ly:1186,lw:310,color:C.orange,size:21});
box(1150,1510,1070,125,'草稿区 · 持久化但不参与召回\n不注入模型，不把待确认案例继续提炼成原则',{fill:'#fff6e9',color:C.orange,size:26});
arrow([[1425,1440],[1425,1495]],null,{color:C.orange});arrow([[1985,1440],[1985,1495]],null,{color:C.orange});
box(130,1540,850,230,'合同语义约束\n保留主体、我方立场、前提、例外与反例\n没有审批证据，不标成正式批准\n制度和风险库仍引用权威来源与版本',{fill:'#f6f8fb',color:C.muted,size:25});
box(1150,1740,1070,155,'正式条目 · 用户确认后发布\n个人：Team ＋ Agent ＋ User\n团队：Team ＋ Agent，仅审核通过版本',{fill:'#e5f3e9',color:C.green,size:26});
arrow([[1685,1645],[1685,1725]],'业务确认',{lx:1710,ly:1669,lw:250,color:C.green,size:22});
text(135,1920,2090,'60 天账期 ＋ 20% 预付款 ＋ 仅本项目 → 带条件案例；不会变成企业统一接受标准。',{size:24,color:C.orange});
region='workflow';panel(2050,850,'03  业务面板：确认、个人管理与团队审核','用户无需登录 Memory Hub。浏览器只访问 OpenHarvey；Core 再次校验身份与团队权限。');
box(130,2250,550,120,'对话合并提示\n“有 N 条建议记住”',{fill:'#eaf1fb',color:C.blue,size:26});
box(850,2250,580,120,'用户确认 / 修改后确认\n不记录 / 稍后处理',{fill:'#fff0dc',color:C.orange,size:26});
box(1600,2250,580,120,'我的经验与工作偏好\n正式版本，可增删改',{fill:'#e5f3e9',color:C.green,size:26});
arrow([[695,2310],[835,2310]],null);arrow([[1445,2310],[1585,2310]],null);
box(1600,2490,580,120,'提交最终发布摘要\n不开放原合同和对话',{fill:'#eaf1fb',color:C.blue,size:26});
box(850,2490,580,120,'团队管理员审核\n核对发布文本及版本差异',{fill:'#fff0dc',color:C.orange,size:26});
box(130,2490,550,120,'团队经验与工作约定\n审核通过后才共享召回',{fill:'#e5f3e9',color:C.green,size:26});
arrow([[1890,2385],[1890,2475]],null);arrow([[1585,2550],[1445,2550]],null);arrow([[835,2550],[695,2550]],null);
box(130,2700,2050,120,'人工决定受保护：后台不覆盖正式版本；同来源删除或忽略不复活。\n版本检查 ＋ 幂等操作 ＋ 事务审计；退出团队后重新校验访问。',{fill:'#f6f8fb',color:C.muted,size:25});
text(80,2940,2240,'实现分支：两仓库 codex/contract-memory  ·  业务面板 /experience  ·  Memory /v3/contract-memory/*',{size:22,color:C.muted});
const scene={type:'excalidraw',version:2,source:'https://excalidraw.com',elements:els,appState:{viewBackgroundColor:'#f7f9fc',gridSize:null},files:{}};
fs.mkdirSync('docs/diagrams',{recursive:true});fs.writeFileSync(process.argv[2]||'docs/diagrams/contract-memory-mapping.excalidraw',JSON.stringify(scene,null,2)+'\n');console.log(`${els.length} editable elements`);
