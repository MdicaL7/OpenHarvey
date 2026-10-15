# OpenHarvey 标准记忆管道接入契约

> 状态补充（2026-10-15，本地联调基线固化）：下文“本轮”“未部署”“真实模型未运行”等表述保留为各实现/审计阶段的历史记录，不代表当前运行状态。随后在隔离测试环境进行过真实 HTTP 与订阅模型调用；首次测试 1 因本地桥接 429 及 Proxy 可选用量上报失败停止。两项运行时问题已做针对性修复与模拟/临时 HTTP 回归，但真实复测按用户要求暂停。处置案例、修订乱序、L2/L3、权限和页面全链路验收均不能据此宣称通过；代码提交也不代表服务已按提交版本重新构建。

本轮实现业务端标准协议适配、可靠来源关联和保守投递状态。没有部署，没有对现有业务库执行迁移，没有向真实 Memory 写入测试数据。真实模型提炼及共享契约验收尚未完成。

## 职责与数据流

1. OpenHarvey 保存不可变的反馈修订，并在同一 SQLite 事务中写入事件 outbox 与 `contract_memory_deliveries`。原始备注保留空白、换行；业务原始反馈始终是事实来源。
2. 服务端使用已绑定的 Memory 用户凭据、team、agent、task、session 向标准 `conversation/add` 提交一条 L0 用户消息。浏览器不能覆盖这些身份。
3. Memory 异步提炼 L1。首版要求：有效已保存处置事件，只要 `note.trim()` 非空就提炼，不附加质量或数量门槛；空备注、待处理、撤回不作为新有效处置案例。
4. 历史案例工具保留本地受控入口。它调用标准 atomic/search，并在 search 缺来源字段时，以返回的精确 Atomic ID 从 atomic/query 分页结果补充完整记录。不会用 report/risk 或最新事件推测来源。
5. L1 `source_message_ids` → 本地投递的 `l0_id` → 不可变 event_id → 原始反馈修订。业务主键、版本、角色、备注由本地事件提供；仅摘要、条件和例外取自 L1。
6. OpenHarvey 重新验证当前账号/团队权限、合同空间、主合同和引用文档版本、反馈当前修订及未撤回状态，排除相反角色和当前合同。风险定义变化标为差异，未核验的提炼内容/条件/例外标为 conditional。
7. L2 场景及 L3 偏好是 team+agent 共享内容。页面按原生列表和正文显示，不假设所有场景都是风险处置，也不自动把个人确认写入共享层。

## L0 请求与接收契约

`POST /v3/conversation/add`，请求体：

```json
{
  "team_id": "server-bound-team",
  "agent_id": "server-bound-agent",
  "user_id": "server-bound-user",
  "task_id": "server-bound-task",
  "session_id": "server-bound-session",
  "messages": [{"role": "user", "content": "[CONTRACT_RISK_DISPOSITION]\n已保存事件说明……\nMETADATA_JSON: {...}"}]
}
```

服务端认证使用已有 `Authorization`、`x-tdai-service-id`、`x-tdai-user-key`，不接收浏览器提供的 Memory 身份。插件仍使用标准隔离请求头；旧 `x-openharvey-memory-version` 和 `x-openharvey-source-event` 不再生成，仅保留清除旧残留头的逻辑。源码和构建产物同步。

正文 JSON 字段：schema_version=1、稳定 event_id、workspace_id、document_version、report_id、risk_id、risk_name、topic、risk_definition_hash、our_role、decision、原文 note、revision、UTC created_at、document_refs。正文明确“接受风险不代表正式审批”“要求修改不代表修改已完成”。不依赖 messages[].metadata。

标准单条正文上限为 8192 个 JavaScript UTF-16 code units。按完整生成正文检查（包括 JSON、备注、条款和引用），超限保存反馈并标为 blocked_length，不截断、不投递。迁移预检也检查长度。

真实响应外层由 transport 解包：

```json
{"code":0,"data":{"accepted_ids":["msg-..."],"accepted_versions":["v1"],"total_count":1}}
```

一条事件只有在 accepted_ids 是一个非空字符串 ID，且整数 total_count=1 时才记为 l0_received，并原子保存 l0_id。零条、错误形状、超时均不能标成功。L0 接收不等于 L1 提炼完成。

## 可靠性与迁移

原 outbox 保留，包括旧 synced、失败信息和数据。新 delivery 以 `(event_id, backend='native-v3')` 去重，独立保存投递快照、目标身份、迁移批次、状态、L0/L1 ID。切换 Memory 地址或身份后阻止投递及来源使用，不能把旧接收结果当成新目标的接收结果。

迁移预检只读，验证当前反馈/文档/权限/Task/长度，并说明已有原生投递状态。显式迁移只给符合条件且尚无原生 delivery 的事件建新任务，产生独立批次 ID，返回实际插入数；重复选择不会增加计数。不重置旧 synced，不修改旧事件。

状态：pending（待发送）、blocked（发送前被本地条件阻止，可显式安全重试）、blocked_length（超限）、uncertain（请求开始后结果未确认或进程中断）、l0_received（收到有效回执）、legacy_not_delivered（只有旧投递历史）。L1 单独显示 not_expected、not_observed、found。

当前原生 conversation/add 每次生成新 UUID，没有 event_id 幂等键。发送前以条件 UPDATE 领取任务并记 uncertain，避免多个 worker 同时发送；超时不自动重发。仅 blocked 支持本地 sync-retry，实际 UPDATE 成功才返回 queued=1。uncertain 的远端核对/人工消歧工具尚未实现，不能宣称 exactly-once。只有本地重复入队去重。

## L1 与页面响应适配

- atomic/search、atomic/query：`data.items` 是 AtomicDetail，正文 `content`，提炼条件和例外来自 `metadata.conditions/exceptions`，不是旧 e.data 经验对象。
- source_message_ids 必须来自原生记录；缺失、未知来源、多事件合并而无法确定条件归属，均不可用。query 补全最多扫描 1000 条，匹配不到保持不可用并返回 notice。
- scenario/ls：`data.entries`，路径以 `/` 结尾的是目录，列表不当正文卡片展示。
- scenario/read：请求 `path`，响应 `{path, content, version, ...}`；通过 URL 编码的路径传入本地详情接口。
- core/read：读取 `{content, version, ...}`，不假设返回 items。
- scenario/write 的原生契约是 `path/content/summary?`。本轮没有开放写入页面：个人编辑与审批尚无本地实现，不能将旧 data、delete、confirm、propose、review 请求映射为 scenario/write。
- ignore 不映射 atomic/update；整理 retry 不映射查询。旧操作明确 HTTP 501，界面不展示可执行按钮。

## 功能清单

| 状态 | 功能 |
| --- | --- |
| 保留 | 原始反馈及修订、合同和团队权限、风险定义比较、本地受控历史查询工具、团队成员管理 |
| 调整 | L0 正文提交及回执验证、来源关联、分层状态、保守适用性、L1/L2/L3 页面只读适配、旧投递迁移预检 |
| 暂不可用 | 个人记忆编辑/确认/忽略、个人到团队共享审批、页面删除、提炼重试、uncertain 自动恢复、L2/L3 合同来源和版本历史回溯 |

账号停用不再调用不存在的 meta/user/status。OpenHarvey 本地账号与登录仍停用，并禁用本地会话 Memory binding。此操作不是 Memory 全局密钥撤销；已离开本项目的独立凭据仍需 Memory 管理端处理。

## 对齐依据及待联调

核对相邻 `TencentDB-Agent-Memory-contract` 工作区原生文档、Python SDK 和服务端源码（检查时 HEAD 为 8b86874，工作区文件可能含未提交改动）：

- `MemoryCore/v3-api-memorycore-doc.md`：conversation/add、atomic、scenario、core 形状及长度。
- `MemoryCore/src/gateway/v2-router.ts`：原生 v3 共用 handler；conversation/add 生成新 UUID，query 解码 provenance，search 当前只输出 metadata 而未输出 source_message_ids。
- `MemoryCore/src/gateway/v2-schemas.ts`：source_message_ids 增量响应契约。
- `MemoryCore/src/core/prompts/l1-extraction.ts`：前轮核对时合同提示词存在完整性要求。本轮只读发现提示词已更新逻辑身份及修订规则，仍须真实提炼和调度验证。

共享契约待验收：Memory 落实首版提炼规则（包括单条事件的调度，无额外数量门槛）；query/search 的来源字段一致；确认 metadata 条件/例外形状及不损失来源；在隔离测试账号完成真实 L0 接收、真实 L1 生成及来源回查。L1 修改/删除后既有 L2/L3 自动失效传播不在本轮范围。

## 前轮验证记录（本轮结果见文末）

- Python 完整回归：374 项通过（随后增加原生来源补全、可靠重试与 UTF-16 测试，并重新跑相关模块）。
- 最后相关回归：35 项通过，覆盖反馈/outbox 原子性、原文与事件格式、真实回执、零接收、超时不重发、L0/L1 映射、来源不可用、版本/权限/角色/当前合同过滤、空备注、超限、迁移实际计数、L2/L3 适配、不可用操作及插件相关后端逻辑。
- Node 回归：174 项通过，包含源码和构建产物清除旧专用头。
- Playwright：使用本地静态页面及合成业务 API 响应，验证原子列表、团队场景和偏好卡片、禁用个人编辑、路径详情弹窗及正文。截图位于 `output/playwright/native-memory-team.png`、`native-memory-detail.png`。这是模拟页面验证，不是真实服务或真实模型验证。
- 真实服务请求：未执行；真实模型提炼：未执行。未部署，未对现有数据执行迁移或回填。

## 2026-10-14 审计修复与最新契约

本节替代上文旧的状态细节和旧验证记录；下述共享契约以本项目实际 formatter 和原始反馈为准。

### 投递异常与并发

- `MemoryTransportError` 保留 `transport_kind`、`safe_to_retry` 及原始异常链；对用户仅输出脱敏分类。
- HTTPX `ConnectError`、`ConnectTimeout`、`PoolTimeout` 表示尚未建立连接/取得连接，确定本次 HTTP 请求未发送，回到 `blocked`，可显式安全重试。未自动循环重试。
- `ReadTimeout`、`WriteTimeout`、读写错误、协议异常、HTTP 错误、JSON/回执错误均不能证明未落盘，保持 `uncertain`。进程在领取后退出也保持 uncertain。没有 exactly-once 保证。
- 领取以 pending + attempts + data 条件更新；完成以 uncertain + attempts 条件更新；异常回写同时校验原状态、attempts 和快照，防止迟到 worker 覆盖其他投递。
- `sync-retry` 只恢复 blocked，返回实际 `queued`；目标不匹配时明确指向独立 target API，不再指向不能处理已有 delivery 的 migration API。
- 状态接口返回脱敏 error，页面展示原因与下一步。L0 接收仍不代表 L1 提炼成功。

### 目标重新预检与绑定

`POST /api/contract-memory/target-preview {event_id}` 只读，返回 `eligible/preview_token/writes:0`。
`POST /api/contract-memory/target-rebind {event_id,preview_token}` 再次核验，条件更新后返回实际 `queued`。浏览器不能指定远端身份。

仅 blocked 且无 L0 ID 的任务可用；pending、uncertain 和 l0_received 拒绝。服务端读取当前授权 binding、团队、Task 映射和原报告线程 Session；检查合同所有权、当前反馈、文档和风险定义。标准 meta 只读验证 auth/verify、team-member/get、agent/get、task/get、task-agent/list。Session 是本地运行时标识，无独立 Memory meta Session 实体，验证其原报告线程与合同归属；Task/用户/团队/Agent 的新目标归属另由上述远端查询验证。

Task-Agent 关联最多核验前 100 项，找不到明确拒绝；缺失新目标的 Task 或归属不一致时要求管理员先修复授权映射。本轮不自动创建远端身份、Task 或 Session。原 delivery 完整快照（含状态、attempts、batch、data）追加到 `contract_memory_delivery_history`，原 outbox 不变，仅未发送 delivery 更新当前目标。重复操作不新建任务，不虚增计数；状态不允许时返回 409。

### 原子列表分页

`GET list?team_id=...&scope=personal|atomic&limit=20&offset=0` 和 `GET candidates?...&limit=20&offset=0`：limit 1–100，offset 0–1000000。响应保留 `total`（上游未给出时为 null）、`limit/offset/next_offset`。每次只拉一页。页面继续加载，切换团队或标签立即清空并失效旧请求；聊天提示明确“前 N 条/共 M 条”，链接到完整列表。

### 有界召回

atomic/search 无 offset，使用 limit 20、50、100；有效案例不足 3 条时扩大，按 Atomic ID 去重，最多 3 次 search、100 个候选。来源补全共享最多 10 次 atomic/query、1000 条预算，总网络调用最多 13 次。短页结束；所有候选和缓存命中仍重新进行权限、来源、版本、角色、当前合同排除检查。无结果仅表示本次有界检索未命中，不宣称全库不存在。普通对话没有本地处置事件是正常情况，只是不能用作处置案例。

### 最新内容及直接来源

同一授权范围内逻辑案例身份是 `workspace_id + report_id + risk_id`，文档版本及风险定义用于防止错误跨版本覆盖。每次业务修订独立稳定 event_id，revision 单调递增。Memory 用较高兼容 revision 的最新内容替换旧 L1；当前 `source_message_ids` 只列最新内容的直接 L0 消息来源，不收集被替代事件历史。不同合同、不同风险不可合并。

OpenHarvey 不依赖模型 metadata 中的 event_id/revision/decision/note，也不依赖 Memory 数据库严格唯一性。只通过 L0 ID → delivery → 本地不可变事件解析，并核对当前反馈 revision、decision、原文 note。旧修订仍返回时过滤；最新备注为空、待处理或撤回后旧案例不可推荐；多个事件来源继续保守拒绝。普通对话可有 L0 ID 而无业务 event_id，这不是数据损坏。L1 变化自动传播到既有 L2/L3 不在范围内。

### 共享样例

`docs/disposition-samples.json` 由 `python -m scripts.generate_disposition_samples` 调用生产 `format_disposition_message()` 生成，只有虚构数据。每项含原始 payload、完整 message、预期有效性及示意 L0 ID；Memory 测试直接使用 message。schema_version 为 JSON **整数 1**；revision 为整数，event_id 为事件字符串；示意 L0 ID 由测试接收回执替换，不能当真实来源。

实际 decision 枚举：`待处理`、`要求修改`、`接受风险`、`升级审批`、`补充材料`、`判断有误`。当前反馈接口没有独立 `撤回` 枚举，撤回既有决定用新的 `待处理` 修订表达；过滤器兼容历史 `撤回`，不编造不存在的接口取值。样例包含有效备注、修订、空白备注及撤回到待处理。

首行固定 `[CONTRACT_RISK_DISPOSITION]`，其后为中文标签/说明文字，最后一行 `METADATA_JSON: ` 后接紧凑 JSON；note 保留原文空白换行，JSON 内转义换行。不要依赖模型把中文 decision 归一化为英文枚举。source_message_ids 不在业务正文 metadata 中，由 Memory 引用实际 L0 消息 ID。

### 待 Memory 联调

只读核对了相邻工作区当前文档/源码，未修改该仓库。当前合同提炼提示词已描述逻辑案例身份、较高 revision 替换及普通聊天无 event_id；这不等于已完成真实模型验收。仍需在隔离账号验证：单条有效事件提炼、中文枚举及空白处理、最新修订替换和直接来源、旧事件乱序到达、多来源保守处理、search/query 来源一致性、真实错误回执与投递核对。uncertain 的远端消歧工具仍未实现。


### 本轮验证结果（2026-10-14）

- `.venv/bin/python -m unittest discover -s tests -q`：385 项通过（117.829 秒）。随后补充共享样例一致性测试、重绑定失败检查及小范围防护，最终相关回归 `.venv/bin/python -m unittest discover -s tests -p 'test_contract*.py' -q`：39 项通过（7.036 秒）。所有业务 fixture 使用临时目录/临时 SQLite。
- `npm test`：174 项通过，含插件和现有页面回归。`node --check static/{app,experience,risk-ui}.js` 分别通过；`git diff --check` 通过。
- 浏览器模拟：`scripts/check_memory_page.playwright.js` 使用 Playwright route 返回虚构 45 条数据，验证 20/20/5 分页、团队切换 offset 归零、旧团队迟到响应被丢弃、标签切换重置。页面截图：`output/playwright/audit-pagination-45.png`、`audit-team-isolation.png`、`audit-tab-reset.png`。已查看渲染截图。
- 复现浏览器模拟：先 `python -m http.server 18763 --bind 127.0.0.1 --directory .`；用 Playwright CLI 独立 session 打开 `http://127.0.0.1:18763/static/experience.html`，再执行 `playwright-cli -s=oh-audit run-code "$(cat scripts/check_memory_page.playwright.js)"`。首次未装模拟路由前的 API 404 来自静态服务器，不是真实 Memory 错误。
- 本轮没有部署，没有启动业务应用连接现有数据库，没有迁移或回填现有业务数据；相邻 Memory 仓库仅只读核对。
- **真实 Memory 服务验收：未执行。真实模型提炼：未执行。** HTTPX 异常和标准 meta 回执为模拟，不能把这些测试表述为真实服务/模型联调通过。

本地团队归属变更不支持通过此重绑定入口跨团队搬迁旧事件，接口明确返回限制；同一本地团队当前授权配置中 core/service/远端 team/agent/user 变化可在完整归属校验后恢复。
