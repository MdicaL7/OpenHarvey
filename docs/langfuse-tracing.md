# 本地双端追踪契约 v1

默认关闭。只为明确选择的本地合成身份启用；不改变模型、提示词、消息正文、合同策略、去重规则或调度阈值。不追加解释提示，不增加模型调用，不把追踪写回 L0/L1。Langfuse 不是业务或记忆数据库。

## 关联字段

| 字段 | 语义 |
| --- | --- |
| `run_id` / `attempt_id` / `test_case_id` | 一次测试运行 / 一次实际执行尝试 / 用例引用；重试产生新 attempt |
| `request_id` / `pipeline_task_id` / `retry_count` | 业务请求 / 原生队列任务 / 原生重试次数 |
| `instanceId/teamId/userId/agentId/taskId/sessionId` | 通用身份；session 只用于筛选，不作为所有调用的唯一关联键 |
| `event_id` | 可选业务事件；普通聊天不要求有业务事件 |
| `l0_message_ids` / `source_message_ids` / `l1_record_ids` | 接收回执、提炼批次完整来源集合、正式记忆 ID；多输入不归给单一请求 |
| `business_revision` | OpenHarvey 反馈修订；不能当成 Memory 的记录 `version` 或重试 attempt |
| `versions` / `runtime_version` | 两仓库完整 commit、工作区清单指纹、实际构建输入与运行标识 |
| `logical_call_id` / `bridge_request_id` | Core/Proxy 逻辑调用与桥接每次物理请求的关联；工具循环可有多个物理请求 |
| `system_prompt_sha256` / `user_prompt_sha256` | 实际提示词原始 UTF-8 字节的 SHA256；提示词版本由源码版本及原生 prompt ref 共同标识 |
| `expected_result_ref` / score | 预留期望结果外部引用；未来 score 通过 trace ID + observation ID + test_case_id 关联，不注入模型输入 |

同步关联使用可选 `x-memory-trace-context`（白名单、有界 JSON，仅相关性，不用于授权）。身份由各服务正常认证、绑定及隔离逻辑确定。异步 L1 每个任务/身份批次是独立 trace，通过完整 L0 来源集合与运行标识连接。L2/L3 继续使用实际输入 ID 和现有 generation JSONL 的 `log_id/generation_id/input_refs/output_refs`，不伪造单请求父子关系。

OpenHarvey 的 outbox snapshot 可携带独立 `trace_context`，formatter 明确白名单，保证该信息不进入 L0 正文。`event_id → delivery.l0_id → L1.source_message_ids` 仍是业务来源核验路径。trace 不能替代该核验。

## 采集和用量

- OpenHarvey：请求/反馈保存、outbox started/l0_received/failed，区分 blocked 与 uncertain；有界召回候选与本地过滤数量、来源 ID 摘要。
- Core：明确选择的 memory span、队列入队/执行、批次边界与结果；现有 L1 decisionAudit 的同一 audit_id、sequence、实际请求/响应、候选顺序、计划、写入/skip 结果映射为 observation。
- L2/L3：逻辑调用、原生 generation 日志来源和输出关联。模型实际物理请求/响应由标准订阅桥接采集。
- 桥接是启用此隔离追踪范围后的唯一 Token 计数端。Core AI SDK root/step 和 Proxy observation 保留为 span，去除 Token/费用字段。桥接物理 attempt 的 input/output Token 只写一次；请求未开始、失败或缺失 usage 不推算 Token。费用未知不填 0。
- Core/Proxy/桥接的原有业务计费、原始用量日志保持；平台聚合必须限定本项目本 run 的 `usage_owner=subscription_bridge`，不能把多个独立业务账本相加。

## 配置

Python 与两 Node 服务以 `MEMORY_TRACE_CONFIG_FILE` 读取受限 JSON。`enabled:false` 或未设文件时关闭本次通用关联层。完整关闭平台导出还须将 Core 的 `observability.langfuse.enabled` 和 Proxy 的 `langfuse.enabled` 设为 false，避免回到原有 LLM 上报路径；保留本地 decisionAudit 与原始用量日志。配置含 `run_id/test_case_id/scopes/versions`；Memory scopes 必须明确 `instanceId/teamId/agentId`，可以加 user/session/task 限制。合成全文必须同时指定 `include_content:true, synthetic_data:true`。L2/L3 是共享 team+agent 层，需明确授权该合成身份范围。

Python 使用 `LANGFUSE_CREDENTIALS_FILE`，只接受 localhost、127.0.0.1、host.docker.internal。Core/Proxy 复用现有 Langfuse 配置和环境凭据 `LANGFUSE_HOST/PUBLIC_KEY/SECRET_KEY`，不能设 Cloud。容器宿主地址应核验为 `http://host.docker.internal:3000`。

Core 还需现有 `l1DecisionAudit` 选中该合成范围，保留 0700 目录、0600 JSONL/status；不开 explainDecisions。decisionAudit 未选中、输出失败/截断时不得声称冲突证据完整。

默认内容仅哈希；合成全文仍脱敏凭据。超过单项 512KiB 时明确 `capture:hash_only,truncated:true`。原 audit 的 maxBytes/status 独立有效；不能将哈希、脱敏或截断内容称为完整模型输入。桥接 attempt 的 input 是实际 Chat Completions wire body。`subscription_bridge.cli_input/cli_response` 另保存实际提交的 CLI 包装提示词、output schema、原始结构化回答和原始字节 SHA256；仅声明应用提交内容，不声明能获取提供方隐藏上下文。Core prompt 字节哈希以 Core 实际 prompt 为准。

Python 导出队列 128、单请求 2 秒、无重试、flush 最多 3 秒；Core/Proxy 队列 256、批次 32、导出超时 2 秒、有界关闭。追踪导出错误、队列满、序列化失败发出脱敏 incomplete 状态/日志，不能影响业务结果、重试、游标和写入。故障注入只针对专用测试 exporter，不停止共享 Langfuse。

## 版本兼容与验收

本机实测 health：Langfuse **3.179.1**，现有镜像系列 v3。本次复用 Core 的 OTLP exporter 和 Proxy 的已安装 `@langfuse/otel` / `@langfuse/tracing` **5.11.0**；Python 使用 OTLP JSON，不安装另一版 SDK。核对本机源码属性映射和实际 ingestion；以本机官方 `/api/public/traces`、`/api/public/observations` v1 读取验收。当前网站文档已出现 v4 API，不能直接套用（[官方 API 兼容性说明](https://langfuse.com/docs/api-and-data-platform/features/public-api)）。

部署、源码清单、测试结果、项目链接和真实验收记录在独立交付报告。本轮不运行 LLM-as-judge，不迁移预期答案到记忆，不继续测试 6–10，不将可观测性接通称为原 skip 修复。
