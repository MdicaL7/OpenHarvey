# 合同记忆 v1：身份、数据与业务确认

实验基线：OpenHarvey `7dfb305`（main `81e55c5` 的独立接入），TencentDB Memory `8b86874a2daea49e3ff0fb53d699203146c5c77d`。两个仓库使用 `codex/contract-memory`；保留原开发目录和旧 Memory 服务。

## 身份与权限

Organization 在 OpenHarvey 管理，下设多个 Team。应用 User 对应一个 normal Memory User，Team 一对一对应；成员关系按团队保存 admin/member。每个团队一个合同 Agent；每份合同工作空间一个 Task；每段对话一个 Conversation。

个人范围为实例＋Team＋Agent＋User，团队范围为实例＋Team＋Agent。合同模式使用 Core 独立 SQLite 数据平面；旧 chat/code 的存储与自动提炼不参与合同模式。业务用户无需登录 Hub。

企业管理员创建团队和分配成员；这不自动赋予 Memory system_admin 权限，也不能阅读其他人的合同或个人内容。团队管理员审核成员提交的发布摘要，原合同始终按本人及有效团队成员关系检查。团队发布内容不携带个人来源 ID，面板显示受限来源；不开放原合同标题、片段或下载链接。多人使用同一个团队 Agent 时仍保留真实用户身份，不能替换成 Agent Owner。

Memory 初始化管理员凭据仅在控制端通过文件读取。正式写入和证据上下文还需要独立的组件控制凭据，Agent 的普通 User Key 不能自行调用这些写入接口。运行身份使用各自加密存储的 normal User Key。浏览器请求不接受上游 user_id/agent_id/task_id；后端解析身份，Core 再次验证 User Key、Agent、成员和 Task。旧分层写入不能绕过确认。

## L0–L3 合同语义

| 层级 | 定位 | 行为 |
|---|---|---|
| L0 | 原始记录与证据引用 | 记录真实用户输入、助手输出和 OpenCode 原生工具结果；来源上下文保存文档版本与段落校验信息 |
| L1 | 原子事实与判断记录 | 区分原文事实、人的意见、处理决定、助手建议、执行结果、偏好和待办；完整保存条件、例外、状态与消息来源 |
| L2 | 过往经验 | 按风险主题归纳带条件案例；长期偏好不重复生成风险经验 |
| L3 | 工作偏好与约定 | 从明确长期偏好或已确认经验提出约定；未确认案例不向原则传播 |

长期管线不增加 L4。上下文卸载和自动 Skill 生成不在本轮。

`contract-v1` 提示词覆盖 L1、冲突分析、L2 和 L3。模式由 Agent 的受管理元数据 `prompt_mode=contract` 决定。抽取不使用写文件／执行工具。source_ids 必须指向本用户范围内已存在记录。模型不能设置 Owner、权限、正式审批或执行状态。文档证据需要版本、段落 ID 和真实工具输出中的段落内容哈希同时匹配；无法核验保持消息依据，不冒充原文证据。

一次性条件保留为案例。例如“60 天账期＋20%预付款＋仅本项目”不能推广成企业统一接受标准。“记忆确认”“团队发布”和“合同批准”是独立语义。

## 确认、编辑与共享

候选保存到草稿表，不出现在 scenario/core 召回视图。对话内按 Conversation 合并提示“有 N 条建议记住”，支持确认、不记录、修改后确认或稍后处理。确认成功才创建正式版本。

正式内容、候选、版本、申请、删除标记与审计由 Memory 保存；应用只保存身份和合同关系。scenario/core 是由有效正式条目动态构造的可重建视图，首版无需异步向量索引，因此确认后即可使用，删除立即停止召回。

人工内容受保护。后台从不覆盖正式版本，只生成新候选；同来源忽略或删除后不复活。候选指纹由范围、类别、主题和来源组成；真正新来源可以提出新建议。并发修改必须提供 version；mutation 必须提供 operation_id，相同操作重试不重复发布，操作标识复用到其他内容返回 409。

团队新增、修改、删除均形成申请，管理员批准后才发布。审核检查申请版本，原始版本已变更时返回 409；审计与正式数据在同一个 SQLite 事务中提交。共享版 source_ids 清空，私有原始内容不进入审核响应。

个人约定和团队约定共同参与召回；发现冲突须提示用户核对。经验始终作为参考，不能替代当前原文、风险库、制度版本或业务审批。

## 接口与故障

应用 `/api/contract-memory` 提供 teams、team-selection、members、list、detail、candidates、proposals，以及 create/update/delete/confirm/ignore/propose/review/retry。Memory `/v3/contract-memory/*` 使用服务实例＋正常用户凭据鉴权。

业务查看先校验企业及团队成员；源文档由应用逐个校验所有者、有效版本和合同存在性。普通 provider 不开启 Memory 请求头及桥接。合同 Memory 仅本机可用，模型地址与身份 Key 必须吻合；Proxy 故障明确报错，不自动切换。

后台任务持久化，最多三次自动尝试；重启恢复正在执行的任务。失败状态可在待确认页面观察，耗尽自动尝试后可显式重试。服务写入不确定时提示刷新确认，不能将模型说“记住了”当作回执。

## 迁移与运行

旧实验账号显式执行 `--contract-memory` 升级：创建 contract Agent，把本人已有工作空间归属到默认实验团队，原 Task／Conversation 标识保持。旧 code Agent 和记忆保持原状。首版不支持跨团队迁移已有合同。

独立组件启动：

```sh
cd /Users/dicam/CodeDir/TencentDB-Agent-Memory-contract
python3 deploy/contract-memory/manage.py start
```

启动脚本基于已固定的上游镜像 digest 加载本分支源码；配置复制到忽略的 `deploy/contract-memory/state`，权限 0600。源码内容哈希和镜像 ID 记录在 state/deployment.json。端口为 Core 8430、Proxy 8106；数据卷使用独立 `tdai-contract-*-data`。

应用启动：

```sh
cd /Users/dicam/.codex/worktrees/contract-memory/OpenHarvey
/Users/dicam/CodeDir/OpenHarvey/.venv/bin/python scripts/run_tencentdb_local.py \
  --contract-memory --data /Users/dicam/.local/share/openharvey/contract-memory-lab \
  --port 8081 --core-url http://127.0.0.1:8430 \
  --proxy-url http://127.0.0.1:8106/opencode/default/v1 \
  --admin-key-file /Users/dicam/CodeDir/TencentDB-Agent-Memory-contract/deploy/contract-memory/state/admin.key
```

业务面板：<http://127.0.0.1:8081/experience>。本机预览账号 `openharvey-local`；应用登录凭据在数据目录 login.json。Memory Hub 继续保留旧部署做独立观察，本轮合同管理入口为业务面板，不能用旧 Hub 操作合同草稿。

## 兼容性与验收说明

本机模型与提炼配置显式采用非思考模式，以适配当前 OpenCode 的 OpenAI-compatible 工具调用；参数参考 [DeepSeek 官方说明](https://api-docs.deepseek.com/guides/thinking_mode/)。同一输入的 code/contract 对照已记录模型、输入、输出及用量；不将单次对照当作法律正确性保证。

上游 Proxy 完整类型检查有 60 个基线错误；比较时忽略代码新增导致的行号移动，本次没有新增错误。新的合同服务单独进行 TypeScript 检查。

真实验收发现原生调用可能以空 unknown 响应结束；应用现已明确标记失败并暂停后续队列，保留草稿供恢复。团队空间的成果保存回调已补齐完整账号信息，新增团队保存与撤销成员后的保存拒绝测试。
