# 合同记忆的数据来源与沉淀时机

本图描述 2026-10-12 的当前实现，不是按合同业务阶段触发的改造方案。
核对基线：OpenHarvey `90d91f4`；独立 TencentDB Memory contract 分支 `41b3e0a`。

- [可编辑 Excalidraw](../diagrams/contract-memory-ingestion-timing.excalidraw)
- [完整 PNG](../diagrams/contract-memory-ingestion-timing.png)
- 分区预览：[进入路径](../diagrams/contract-memory-ingestion-timing-ingestion.png)、[提炼时机](../diagrams/contract-memory-ingestion-timing-pipeline.png)、[确认与界面](../diagrams/contract-memory-ingestion-timing-confirmation.png)

## 内容进入

仅本机任务选择 `tencentdb-memory` provider 时启用该路径。普通 provider 的绑定关闭；标题和压缩等辅助请求不记录业务记忆。

| 内容 | 时机及路径 | 结果 |
| --- | --- | --- |
| 身份及合同证据元数据 | OpenHarvey 每轮调度前 `prepare()` 调用 Core context 接口，并写会话绑定文件；OpenCode 插件通过 `chat.headers` 传身份头给 Proxy | 保存文档 ID、版本、段落引用和哈希，不传合同全文，不直接触发提炼 |
| 用户消息、助手文本 | 非流式成功响应后记录；流式响应收尾后异步记录 | Proxy 调用 `conversation/add` 保存 L0；工具续轮的助手文本通过 `capture-events` 保存 |
| 实际工具结果 | 执行完成后，工具结果随下一次模型请求经过 Proxy | `capture-tools` 保存 L0，包括工具名称、调用来源、文件路径及结果内容；已有工具来源去重 |
| 用户面板操作 | 确认、手动保存或管理员审核时 | OpenHarvey 转发受控 Core 写入，保存正式条目、版本、共享申请和审计 |
| 未读取的上传合同全文 | 无自动沉淀入口 | Core 不主动下载或扫描 OpenHarvey 合同；Agent 实际读取过的内容才可能通过工具结果进入 |

工具执行并不保证结果已进入记忆：需要结果经过 Proxy，并且 Core 写入成功。助手口头说“已保存”或“已记住”不等于真实回执。

## 模型沉淀

1. **L0**：原始记录去重并持久化；此步不调用提炼模型。有新增记录才创建后台任务。同用户、同会话已有 pending 任务时合并。
2. **启动**：Core 收到写入后立即尝试执行任务；另有每 3 秒一次的队列检查。每实例一次执行一个任务。当前无最低轮数、会话空闲或审查完成门槛，3 秒不是完成时限。
3. **L1**：读取本会话累积 L0，而不是只处理最新一条；同 Task 的历史 L1 作为参考。工具输入仅保留与已绑定文档、原生 read 路径和段落引用匹配的结果，或包含 `saved:true` 的回执。具体合同原文引用还要通过版本、段落内容哈希及来源核验。模型提出的事实、意见、决定、建议、执行结果、偏好与待办经结构校验后保存。
4. **L2**：同任务内，在 L1 后进行。输入为本会话有效 L1，排除偏好；原文事实必须有已核验文档依据。输出是按风险主题组织的经验候选，不自动成为正式经验。
5. **L3**：同任务内，有本会话明确 L1 偏好或当前个人已确认经验时才调用模型。未确认 L2 候选不作为原则依据。输出仍是候选。
6. **额外 L3 任务**：用户确认或手动新增一条经验时，Core 排队 profile 任务，用个人已确认经验提炼原则候选。手动新增偏好不排此类任务；当前修改经验也不会自动重提炼。

失败任务最多自动尝试 3 次；耗尽后可从面板手动重试。后台无权覆盖人工正式版本。同来源忽略或删除后有抑制标记。

## 正式生效与界面

L2/L3 候选已持久化，但不进入正式经验和偏好的检索视图、注入或高层事实传播。用户确认后成为个人正式版本；团队共享内容须经过团队管理员批准。确认记忆不代表合同事项已批准。

对话中的建议卡片每 8 秒刷新。卡片刷新不触发模型提炼。L0/L1 仍有受身份、团队、用户及任务边界限制的查询接口，因此“未确认不召回”特指正式 L2/L3。

合同模式使用 Core 专用 SQLite 数据平面。Memory Hub 是界面，不是存储引擎；本轮保留的旧 Hub 未适配合同候选与正式条目。当前业务管理入口是 OpenHarvey `/experience`。旧 Hub 与新合同数据不能等同。

## 源码依据

OpenHarvey 仓库：

- `contract_web/contract_memory.py`：`prepare()` 绑定文档来源、context 提交及业务管理接口。
- `contract_web/tencentdb_memory.py`：按 provider 启停绑定。
- `scripts/tencentdb-plugin/runtime.js`：逐 OpenCode session 请求头。
- `static/memory-suggestions.js`：每 8 秒查询候选与确认操作。

TencentDB Memory contract 仓库：

- `MemoryProxy/src/handler.ts`：辅助请求排除、工具收集、流式及非流式记录时机。
- `MemoryProxy/src/tdai/recorder.ts`、`client.ts`：原始消息及工具提交。
- `MemoryCore/src/contract-memory/store.ts`：`capture()` 去重、任务入队、候选确认与来源核验。
- `MemoryCore/src/contract-memory/service.ts`：立即触发、3 秒调度、L1/L2/L3 输入条件及 profile 任务。

图形生成脚本为 `scripts/build_memory_ingestion_timing_diagram.mjs`。交付画布由 Excalidraw 0.18.1 实际导出 PNG，并核对中文、文字边界和箭头；此过程不调用记忆模型。
