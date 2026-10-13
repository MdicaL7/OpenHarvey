# OpenHarvey 记忆使用触发清单（contract-v2）

审计日期：2026-10-13。源码基线：OpenHarvey `bc49476`；TencentDB-Agent-Memory-contract `3bdcd3e`。本文件是源码行为清单。当前服务已升级为 `contract-v2`，真实实验结果见 [在线验收报告](../evidence/contract-memory-v2-live/README.md)。源码基线保留为首次审计版本，后续修复见验收报告。本次仅读取源码和制作图，未调用业务、抽取或相关性模型。

- [可编辑 Excalidraw](../diagrams/contract-memory-usage-triggers.excalidraw)
- [完整 PNG](../diagrams/contract-memory-usage-triggers.png)
- 分区预览：[业务请求](../diagrams/contract-memory-usage-triggers-requests.png)、[Agent 查询](../diagrams/contract-memory-usage-triggers-agent.png)、[报告卡片](../diagrams/contract-memory-usage-triggers-reports.png)、[管理与后台](../diagrams/contract-memory-usage-triggers-management.png)、[边界](../diagrams/contract-memory-usage-triggers-boundaries.png)。

## 先区分四种“使用”

1. **注入给业务模型**：Proxy 将正式 L3 正文、L2 目录附到 system；无需 Agent 发工具调用。
2. **Agent 主动取内容**：Agent 发出受限 Bash 工具调用，取 L1 案例、L2 正文或 L0 原话；结果进入后续推理上下文。提示词要求先查，不是程序强制执行了查询。
3. **给用户展示**：报告卡片、经验面板、建议卡片读取 Memory；结果不会自动作为新消息传给业务模型。
4. **后台再整理**：抽取及冲突分析模型读取现有案例、经验、偏好，产出新候选；不代表合同 Agent 正在使用它回答。

同一个用户操作可叠加多条路径。例如进入一个旧会话，可以自动打开已有报告查 L1，同时建议卡片查询候选；只有随后发送业务消息才会发生模型注入。

## R：业务请求自动注入

| ID | OpenHarvey 操作或事件 | 实际触发 | 读取层级与结果 |
|---|---|---|---|
| R01 | 在本机、已绑定团队的合同会话发送第一条消息 | 调度准备身份与来源 → OpenCode `chat.headers` → Proxy 业务请求 | L3 正文 + L2 正式目录 + 工具说明进入 system |
| R02 | 同会话续聊、同合同新会话发消息、新合同发消息、恢复旧会话后发消息 | 同 R01；合同空间保持其团队归属 | 取该用户在合同所属团队的个人正式内容和该团队已发布内容；不是只取当前 Task 的 L2/L3 |
| R03 | Agent 执行 read、bash、检索、保存等工具后，工具结果返回并继续请求模型 | 续轮再次经过 Proxy | v2 标记令 tdai 注入器绕过旧 session-init 缓存，再读取 L3 + L2 目录；一次发言可能对应多次读取 |

R01–R03 的前提是 Memory provider、有效会话绑定、contract Agent、本机模式及启用相应注入配置/记忆能力。服务端不是按业务话题分类：普通合同问答、整份审查、条款解释、报告写作、修订讨论、称呼问题、闲聊，只要进入该业务链路，都可获得相同类别的注入。

L3 不是无限量：每 Agent 的输出段按 6000 字符截断。L2 目录受 `l2Limit` 限制，每条摘要受长度上限；目录不含正文，遗漏条目可由 Agent 主动 `scenario/ls` 查询。注入成功只说明模型获得内容，不证明模型在答案中遵循或引用了它。

## A：Agent 按需检索（提示词指引，不是关键词硬路由）

| ID | 场景 | 调用方式 | 层级及范围 | 使用形式 |
|---|---|---|---|---|
| A01a | 审查当前条款并识别风险，希望参考以前处理 | `recall_precedents.py --risk-id ... --document-id ... --blocks ...` | L1 真实处置案例；本人同团队**其他合同空间** | 工具返回历史处理、条件、版本、匹配点和差异；后续模型形成建议 |
| A01b | 已有报告，追问某项风险以前怎么处理 | 同脚本，传报告 ID、风险 ID | 同 A01a | 同一检索服务；需当前报告权限、文档版本、风险定义和原文来源可验证 |
| A02 | 当前问题对应已有风险方法，或明确要求参考过去经验 | 先看 L2 目录；必要时 `scenario/ls`；`scenario/read` 按真实 ID 取文 | L2 本人已确认 + 团队已发布 | 正文带条件/例外/版本进入工具结果；单看到标题不等于已经读过经验 |
| A03a | 询问或执行长期报告结构、证据要求、称呼等；答案已在注入中 | 无须新检索 | L3 正式约定 | 模型直接参考 system 内容 |
| A03b | 要求回查偏好/约定的记忆记录 | `atomic/search` 或 `atomic/query` | contract-v2 兼容入口仅返回被正式偏好条目引用的偏好声明，受桥接当前 Task 范围约束 | 不是任意历史处置案例搜索；跨合同处置要走 A01 |
| A04 | “我上次怎么说”“找当时原话”“回顾本合同历史过程”，当前上下文不足 | `conversation/search` 或 `conversation/query` | L0 当前 Task 的消息；指定 Conversation 时继续收窄 | 用原话核对来源和时间线；不能把过时原话直接当现行批准 |

A01 服务先做权限及有效案例筛选，再按当前风险定义、主题与文本相关性取候选；模型判断适用性，最多返回 3 条。相反交易角色排除，未知条件、项目限定和标准变化需核对。没有合格候选直接返回空。历史案例不自动改写报告、风险结论、反馈或执行动作。

当前没有“识别一个风险就由应用强制执行一次脚本”的业务回调。系统指令要求查询，审查 Skill 提供调用方式，但 Agent 是否实际调用仍取决于模型行为；应以真实工具轨迹验收，不能只检查最终回答提到“历史”。

## B：报告页面自动使用 L1（不必发消息）

| ID | UI 触发点 | 程序行为 |
|---|---|---|
| B01 | 进入、恢复或切换至已有报告的会话；工作区刷新后自动选中报告 | 自动调用 `openArtifact` 后，对当前可见风险调用 `loadPrecedents` |
| B02 | 下拉选择报告、点击报告标签/成果链接、重新加载报告 | 同 B01 |
| B03 | 开启报告对比、切换对比报告、从历史处置链接跳到来源报告 | 对渲染的报告查询，来源报告也可能继续显示其他合同参考 |
| B04 | 点击“需关注 / 全部 / 未命中 / 不适用 / 已反馈”筛选 | 重建卡片，对新 DOM 中的可见风险再次查询 |
| B05 | 保存或修改风险反馈成功，重绘风险卡片 | 再查卡片参考；反馈自身另走异步写入，不表示新案例同步已完成 |
| B06 | 点击失败记忆同步的“重试”，成功排队后重新打开报告 | 再次查询报告卡片；同步重试本身属于写入队列 |

调用链：`loadPrecedents` → `GET /api/artifacts/{aid}/risks/{rid}/precedents` → `ContractPrecedents.recall` → Core `case-list` / `precedents`。

- 默认“需关注”显示命中、信息不足；切换全部等筛选后，未命中和不适用项也有查询容器。不是“只有命中项才会查记忆”。
- 同一已加载 DOM 用 `dataset.loaded` 抑制重复调用；DOM 重建会再次请求。应用相关性结果缓存 60 秒，命中仍重新核验权限与来源。匹配无缓存且有候选时，可调用相关性模型；打开报告不总是纯数据库读取。
- 结果只填充“历史处理参考”区域。没有代码把页面取到的结果自动发进当前聊天；Agent 若要使用仍通过 A01 自己查询。两条路径共用服务和案例版本检查。
- **重要源码边界：该 GET 入口和 `current(..., for_recall=True)` 不以聊天框当前 provider 或原报告 provider 为门槛。** 有有效团队、身份及原文来源时，普通模型生成的报告也可能查询 L1。与之不同，风险反馈的 `enqueue` 明确检查原报告使用 Memory provider 才入队。因此“普通 provider 完全不碰记忆”并不是现有实现。
- 同一合同空间被专用匹配排除，不能把自己的新反馈立刻当作本卡片的跨合同历史参考。已有本合同反馈仍在“反馈记录”中显示。

## C：面板、确认和后台再利用

| ID | 触发点 | 读取或改变哪些内容 | 是否用于当前 Agent 回答 |
|---|---|---|---|
| C01 | 打开经验页，切换我的/团队内容或团队 | 正式 L2/L3 列表 | 否，页面展示 |
| C02 | 点击来源与版本、编辑、准备共享 | L2/L3 正文、历史版本及有权访问的来源；编辑可直接使用已加载内容 | 否 |
| C03 | 会话切换事件、页面每 8 秒刷新建议 | 当前 Conversation 的 L2/L3 候选；接口同时返回整理任务状态 | 否；轮询本身不触发模型提炼 |
| C04 | 打开待确认、共享申请与审核、旧版历史 | 候选、待复核记录、申请或 v1 历史正文 | 否；v1 和候选不进入 v2 正式注入 |
| C05 | 确认/修改后确认/手动新增/修改/删除；团队审核通过 | 正式 L2/L3 及版本/状态改变；确认或手动新增经验还排入 profile 任务 | 本次操作不自动发送聊天；之后的业务请求或检索采用新状态 |
| C06 | 保存真实风险反馈，或对失败同步重试 | 反馈成功同步后生成/更新 L1 案例；恢复待处理使旧处置退出有效参考 | 写入本身不生成业务回答；UI 重绘可叠加 B05/B06 |
| C07 | 新原始记录入队、处置事件入队、后台失败重试、profile 队列 | L1 整理可读当前有效案例；L2 读取合格 L1 处置案例及个人正式经验；L3 读取长期声明与个人正式 L2；冲突分析读取相同主题/类型的个人正式条目 | 属于抽取模型使用，不是合同 Agent 回答使用；输出候选仍待确认 |

后台不是每次入队都调用所有层级：新用户消息或未处理事件才调 L1；有合格案例且有新事件/复用指令才调 L2；profile 任务或新长期声明且存在合适输入才调 L3。L2 需两个不同合同空间的有效案例或明确复用已有案例指令。未确认 L2 不作为正式经验传给 L3。

页面管理独立于聊天模型选择。本人个人记忆按团队隔离；团队内容须审核发布。点击“来源与版本”不开放其他人的合同。只读迁移预检读取旧反馈的业务证据；显式重建属于写入路径，不能从 v1 摘要伪造 L1 案例。

## D：没有直接记忆读取的操作与间接触发

| ID | 操作 | 真实边界 |
|---|---|---|
| D01 | 单独创建团队、合同空间、空会话 | 不启动 L1–L3 回答读取；页面另行轮询/打开报告时按 B/C 计算 |
| D02 | 单独上传文件、查看原文、下载 Word/成果、查看原始反馈记录 | 这些动作自身不查询 Memory L1–L3；后续发消息或自动打开报告是另一触发点 |
| D03 | 只切换模型，不发消息 | 不立即重新注入；下一次调度决定新请求路径 |
| D04 | 普通 provider 的新业务请求 | 不新增外部记忆注入/专用检索权限；B/C 页面读取独立，不能视为全局关闭 |
| D05 | 标题、压缩等辅助请求 | 插件不带业务身份头，Proxy 跳过业务记忆注入/记录；它们仍可能处理已在对话上下文中的文本 |
| D06 | 只切换团队视图 | 不移动已有合同；旧合同下一次请求仍由其固定团队决定。经验页换团队会触发 C01 |
| D07 | 删除记忆、成员撤销、普通模型切换 | 后续读取重新校验/分流，但不会追溯擦掉模型此前读到的历史消息、工具结果、已生成报告或浏览器已显示内容 |
| D08 | 服务重启或页面刷新 | 重启本身不是业务回答触发；页面重载可触发 B/C，待处理后台任务恢复可触发 C07 |

## E：上游兼容技术入口（不是合同业务按钮）

`mem:sync` 在符合上游命令解析且已有 Session 的模型请求中，由 Proxy 提前拦截，重载会话资产并预热注入缓存，其中包括 L3 和 L2 目录，然后返回状态。它不走普通合同模型回答；v2 业务请求已逐次绕过旧缓存。该兼容命令在 OpenHarvey 合同链路中的真实可达性及交互尚未验收，不能当作业务人员必须执行的操作。

`mem:help`/未知命令返回说明；`mem:create-task`、`mem:update-task`、`mem:session-reset` 属于上游 Task/绑定控制；`mem:create-skill` 属于归档/Skill 提取。它们不是新增的合同 L1–L3 使用策略，不应拿来改变 OpenHarvey 管理的合同 Task。本文未执行任何这些命令。

## 此次审计发现的解释限制

1. **普通 provider 隔离有两种路径**：聊天新增注入已隔离，报告展示与记忆管理未按 provider 禁用。此前泛称“普通 provider 不启用这套链路”需要限定为聊天模型链路。
2. **通用工具说明仍有上游语义**：说明文字称 atomic/search 为 hybrid、按 query 检索，但 contract-v2 的兼容分支实际筛选“被正式偏好引用的声明”，未按 query/type/时间实现通用检索。因此图中把它写成偏好来源回查，而非一般 L1 语义搜索。说明中也混有 code/chat 示例；本任务仅如实记录，未修改实现。
3. **尚无程序保证每项审查必查 L1/L2**：只有报告页程序查询是确定性入口；Agent 工具使用须以运行轨迹核实。
4. **不将旧上下文清除等同于查询失效**：从后续接口退出，不意味着从已经返回的上下文或旧答案消失。

## 主要源码证据

OpenHarvey：

- `contract_web/app.py`：业务调度 `tdai.prepare` / `tdai.prompt`，历史处置 GET 与内部只读 POST，反馈保存事务。
- `scripts/tencentdb-plugin/index.js`：`chat.headers`、辅助请求分流、受限工具检查。
- `static/app.js`：`openArtifact`、首次/恢复会话自动打开报告、筛选和反馈保存后的 `loadPrecedents`。
- `static/risk-ui.js` / `static/precedents.js`：可见风险筛选、逐项请求、DOM 去重和展示。
- `contract_web/contract_precedents.py`：`current` / `recall` / `enqueue`，权限、provider 写入限制、60 秒缓存。
- `static/memory-suggestions.js`：会话事件及 8 秒候选刷新。
- `static/experience.js` / `contract_web/contract_memory.py`：面板路由、状态变更及来源校验。
- `runtime/skills/contract-review/SKILL.md`、`contract_web/tencentdb_memory.py`：Agent 查询指引。

TencentDB-Agent-Memory-contract：

- `MemoryProxy/src/handler.ts`：辅助请求、mem 命令、业务注入顺序。
- `MemoryProxy/src/injection/pipeline.ts`：v2 请求 bypass session-init 缓存。
- `MemoryProxy/src/injection/injectors/tdai-profile-memory-injector.ts`：L3 正文、L2 目录和截断。
- `MemoryProxy/src/injection/injectors/tdai-tools-injector.ts`：工具说明与按需调用。
- `MemoryProxy/src/tdai/client.ts`：L2 目录限制；L2/L3 读取不带当前 Task 限制。
- `MemoryProxy/src/memory/memory-bridge.ts`：通用桥接身份/Task 绑定和只读允许列表。
- `MemoryCore/src/contract-memory/service.ts`：正式/候选路由、atomic 兼容行为及 tick 输入条件。
- `MemoryCore/src/contract-memory/v2.ts`：案例排除当前工作空间、匹配与来源校验。
- `MemoryProxy/src/mem-command/commands/sync.ts`：技术刷新路径。

## 图形验证

使用 Excalidraw 官方 `restoreElements` / `exportToBlob` 在本地浏览器渲染。画布有 171 个可编辑元素；全文 PNG 为 2420 × 5110，另有五张分区预览。已检查全部分区的中文、箭头、颜色图例与编号，并用最终文字边界校验确认无文字溢出。仅新增说明、生成脚本和图形文件，没有修改业务代码或运行服务。
