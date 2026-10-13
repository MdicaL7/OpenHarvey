import fs from 'node:fs';
let n=0,region='requests';const elements=[];
const C={ink:'#213547',muted:'#596779',blue:'#24639c',green:'#237149',orange:'#aa611c',purple:'#74539c',grey:'#a8b7c8'};
function base(type,x,y,w,h,o={}){return {id:`usage-${++n}`,type,x,y,width:w,height:h,angle:0,strokeColor:o.color||C.ink,backgroundColor:o.fill||'transparent',fillStyle:'solid',strokeWidth:1.5,strokeStyle:o.dashed?'dashed':'solid',roughness:0,opacity:100,groupIds:[],frameId:null,index:null,roundness:type==='rectangle'?{type:3}:null,seed:n*5779,version:1,versionNonce:n*1277,isDeleted:false,boundElements:null,updated:1791849600000,link:null,locked:false,customData:{region}};}
function text(x,y,w,value,o={}){const size=o.size||24;const e={...base('text',x,y,w,value.split('\n').length*size*1.35,o),fontSize:size,fontFamily:2,text:value,originalText:value,textAlign:o.align||'left',verticalAlign:'middle',containerId:o.containerId||null,autoResize:true,lineHeight:1.35};if(o.center)e.customData.center=o.center;elements.push(e);return e;}
function box(x,y,w,h,v,o={}){const e=base('rectangle',x,y,w,h,o);elements.push(e);if(v){const t=text(x+18,y+18,w-36,v,{...o,align:o.align||'center',containerId:e.id,center:{x:x+w/2,y:y+h/2}});e.boundElements=[{id:t.id,type:'text'}];}return e;}
function arrow(x1,y1,x2,y2,o={}){elements.push({...base('arrow',x1,y1,Math.abs(x2-x1),Math.abs(y2-y1),o),points:[[0,0],[x2-x1,y2-y1]],startBinding:null,endBinding:null,startArrowhead:null,endArrowhead:'arrow',elbowed:false});}
function panel(y,h,title,sub){box(40,y,2360,h,null,{fill:'#fff',color:C.grey});text(80,y+24,2280,title,{size:35});text(80,y+82,2280,sub,{size:23,color:C.muted});}
const styles=[{color:C.blue,fill:'#eaf2fc'},{color:C.orange,fill:'#fff2df'},{color:C.purple,fill:'#f2ecfb'},{color:C.green,fill:'#e7f5ed'}];
function row(y,values,{h=130,size=23,dashed=false}={}){const xs=[90,690,1290,1890];for(let i=0;i<4;i++){box(xs[i],y,i===3?450:530,h,values[i],{...styles[i],size,dashed});if(i<3)arrow(xs[i]+540,y+h/2,xs[i+1]-12,y+h/2,{color:C.grey,dashed});}}
text(70,30,2300,'OpenHarvey：记忆在哪些操作中被使用？',{size:45});
text(72,105,2280,'源码全路径审计 · 2026-10-13 · OpenHarvey bc49476 / Memory 3bdcd3e · v2 已部署；真实验收结果见配套报告',{size:23,color:C.muted});
box(80,157,540,60,'蓝：用户 / 页面触发',{...styles[0]});box(650,157,540,60,'橙：判断 / 调用与调度',{...styles[1]});box(1220,157,540,60,'紫：读取的记忆 / 接口',{...styles[2]});box(1790,157,550,60,'绿：输出 / 下一步',{...styles[3]});

panel(250,880,'01  每次业务模型请求：先自动注入，再由 Agent 决定是否进一步检索','程序按请求入口和身份决定；不按“这是审查 / 问答 / 闲聊”给 L2、L3 做硬分类。实线为程序路径，虚线为 Agent 可选取文流程。');
row(400,['R01 发送第一条消息\nR02 续聊 / 新会话 / 新合同\nR03 工具结果返回后继续推理','选择 Memory provider\n本机 + 身份绑定有效\ncontract 业务请求','L3 已确认正文\n＋ L2 正式经验目录 / 标题\n＋ 只读工具使用说明','进入模型 system 上下文\n形成回答 / 再调用工具\n适用于所有业务话题'],{h:150});
row(625,['问答 / 风险审查 / 条款解释\n报告撰写 / 修订讨论 / 偏好问题\n只要走同一业务请求入口','Agent 看当前问题与注入内容\n决定是否读 L1 案例 / L2 全文\n详见区域 02','工具返回结果进入当前对话\n之后的模型续轮再次经过 Proxy\nv2 不复用旧会话注入缓存','一次用户发言可能多次注入\n不等于 L1 / L2 全文必读\n也不证明回答实际采纳'],{h:160,dashed:true});
box(90,865,1080,170,'自动部分：L3 正文（每 Agent 段上限 6000 字符）\nL2 仅目录（数量受 l2Limit 限制），不是全文\n只含本人当前团队正式内容 + 团队已发布内容',{...styles[2],size:26});
box(1260,865,1080,170,'阻断 / 分流：普通 provider → 无新增记忆注入\n标题、压缩等辅助请求 → 跳过业务注入\n身份 / Task 错误或 Proxy 不可用 → 报错',{fill:'#f3f5f8',color:C.muted,size:26});

region='agent';panel(1170,1030,'02  Agent 的按需读取：哪些话题对应哪些层级？','这是提示词规定的用法，不是后端关键词路由器。模型必须真正发出工具调用，正文或案例才会进入其上下文。');
row(1320,['A01a/b 识别当前风险\n“类似账期以前怎么处理？”\n审查前 / 已有报告后均可','只读 recall_precedents.py\n当前风险 + 文档段落\n或报告 ID + 风险 ID','L1：本人同团队其他合同案例\n专用后端筛选 + 相关性判断\n重新校验来源 / 状态 / 版本','最多 3 条处置参考\n含历史意见、条件及差异\n用于建议，不自动批复'],{h:145});
row(1520,['A02 当前风险涉及已有方法\n“按以前的付款审查经验分析”\n或 Agent 从目录发现相关主题','查看已注入 L2 目录\n必要时 scenario/ls 刷新目录\nscenario/read 按 ID 读正文','L2：本人已确认经验\n＋ 本团队已发布经验\n正文附适用条件、例外、版本','方法供本次分析参考\n未调用 read 时\n模型只有目录标题'],{h:145});
row(1720,['A03 问称呼、风格、长期约定\n“以后报告怎么写？”\n答案是否已在 L3 中？','L3 已有答案：可直接使用\n需要回查：atomic/search/query\n需要原话：conversation/*','L3：正式约定已自动注入\n旧 atomic 入口仅回查已确认\n偏好来源，受当前 Task 限制','不能查询任意 L1 处置案例\n待确认偏好不生效\n跨合同案例走 A01'],{h:145});
row(1920,['A04 追问历史原话 / 时间线\n“刚才或上次我具体怎么说？”\n当前上下文不足','conversation/search 或 query\n经受限 Bash / curl 桥接\n无需用户显式点“查记忆”','L0：当前 Task 内的原始消息\n含允许范围内历史会话\n不是自动查询全部合同','原话用于追溯\n仍需区分旧意见与现行约定\n不能把原话当批准证据'],{h:145});
text(90,2110,2230,'L3 自动提供工作方式；L2 按主题读方法；L1 按风险查真实处置。三条路径可在同一次审查中同时发生。',{size:25,color:C.muted});

region='reports';panel(2240,860,'03  报告 / 风险卡片：无需发消息，也会自动查询 L1','这是页面触发的独立请求；返回结果只展示在报告区域，不会自动发给 Agent，也不重写原报告。');
row(2400,['B01 进入 / 恢复有报告的会话\nB02 打开或切换报告\nB03 对比 / 从历史来源打开报告','openArtifact → 渲染风险卡片\nloadPrecedents 为可见项发请求\n默认“命中 + 信息不足”','GET /api/artifacts/.../precedents\n同用户同团队其他合同 L1\n与 Agent A01 共用后端','显示“历史处理参考”\n每项风险最多 3 条\n相同点 / 差异 / 来源链接'],{h:160});
row(2640,['B04 切换风险筛选\nB05 保存反馈后重绘卡片\nB06 同步重试后重新打开报告','为重新渲染的可见风险再查询\n包括“全部 / 未命中 / 不适用”\n同一 DOM 已加载则不重复','缓存最多 60 秒；命中仍验权限\n无合格案例则直接返回空\n无缓存且有候选时可调用匹配模型','保存反馈本身另走写入队列\n本卡片不会召回同合同案例\n重绘可能复用此前查询缓存'],{h:160});
box(90,2885,2250,125,'当前实现边界：报告查询没有按聊天框 provider 或原报告 provider 禁用。普通模型不新增聊天记忆注入，\n但有团队与有效来源的报告仍可能查询 L1；这是源码现状，不能描述为“普通模型完全不读记忆”。',{fill:'#fff2df',color:C.orange,size:26});

region='management';panel(3140,960,'04  记忆管理、确认与后台整理：读到记忆，不等于用于当前回答','这些读取服务于界面或后台整理；没有自动发送一轮合同对话。正式状态改变后，在下一次读取 / 模型请求中生效。');
row(3300,['C01 打开经验页 / 切换团队或范围\nC02 点击“来源与版本”\n编辑 / 准备共享','应用列表、详情、来源接口\n按登录用户与所选团队校验\n无业务模型调用','L2 / L3 正式正文、历史版本\n详情追溯到许可来源\n他人原合同不会因共享开放','展示、编辑、删除、共享\n不直接注入当前对话\n不要求当前选择 Memory 模型'],{h:150});
row(3510,['C03 会话切换 / 每 8 秒刷新\nC04 进入“待确认 / 待审核”\n或查看旧版历史','candidates / proposals / list\n会话建议按 Conversation 过滤\n页面待确认按团队查看','L2 / L3 候选与共享申请\n旧版内容仅供历史查看\n候选不是正式记忆','“有 N 条建议记住”\n确认 / 修改后确认 / 不记录\n不会让候选进入回答'],{h:150});
row(3720,['C05 确认 / 新增 / 修改 / 删除\n团队申请获批准\nC06 保存真实风险反馈','改变正式内容或有效状态\n反馈异步同步为 L1 案例\n确认经验另排 L3 整理任务','后台 L2 读合格 L1 案例\n后台 L3 读长期声明 / 正式 L2\n冲突分析读相关个人正式条目','后续请求刷新 L2 目录 / L3\n下次检索可见有效 L1\n当前已生成的回答不回写'],{h:150});
text(90,3940,2230,'C07 后台再利用：新消息 / 反馈入队 → L1 整理；满足案例条件才做 L2；长期声明或 profile 任务才做 L3；输出仍须确认。',{size:24,color:C.muted});

region='boundaries';panel(4140,940,'05  不触发、间接触发及技术入口：避免把不同操作混为一谈','以下按程序实际行为描述；没有“上传完成就自动查遍 L1–L3”或“审查结束就自动把所有经验用于报告”的统一触发器。');
box(90,4310,1080,260,'D01 仅新建团队 / 空间 / 会话：不启动回答记忆读取\nD02 仅上传 / 打开原文 / 下载成果：不直接查 L1–L3\nD03 只切换模型：下次发消息才改变聊天读取路径\nD05 标题 / 压缩：不发起新业务记忆注入\nD08 重启本身不读；页面重载可走 B / C\n若同时自动打开报告或轮询建议，另走 B / C 路径',{fill:'#f3f5f8',color:C.muted,size:25});
box(1260,4310,1080,260,'D04 普通 provider：关闭新增聊天注入和专用工具\n但页面 B / C 路径独立；不是全局记忆开关\nD06 切换团队视图：已有合同仍使用创建时归属\nD07 当前对话已含的记忆文字不会被追溯抹除\n删除 / 撤权阻止后续读取，不撤回已生成的内容',{fill:'#fff2df',color:C.orange,size:25});
row(4650,['E01 技术输入 mem:sync\n上游兼容命令，非业务按钮\n不是自然对话必经流程','Proxy 命令拦截\n重新预热记忆等注入缓存\n不走普通合同回答','读取 L3 + L2 目录\n其他 mem 命令属于 Task / Skill\n不等于使用合同 L1–L3','返回刷新状态\nv2 业务请求本就逐次刷新\n兼容命令未做合同真实验收'],{h:160});
box(90,4870,2250,125,'本图说明 v2 源码触发路径；部署与真实实验验收见配套报告，图形本身不证明每次模型调用都符合预期。\n原通用工具说明仍含 code/chat 术语；contract 的 atomic 实现也不是通用向量检索，详见配套逐项清单。',{fill:'#f3f5f8',color:C.muted,size:25});
const scene={type:'excalidraw',version:2,source:'https://excalidraw.com',elements,appState:{viewBackgroundColor:'#f7f9fc',gridSize:null},files:{}};
fs.mkdirSync('docs/diagrams',{recursive:true});fs.writeFileSync('docs/diagrams/contract-memory-usage-triggers.excalidraw',JSON.stringify(scene,null,2)+'\n');console.log(`${elements.length} editable elements`);
