# 自动接口测试与模型配置

本轮真实实验未执行。先人工审查测试集，再锁定包哈希及配置。以下真实运行命令是后续入口，本次仅验证模拟响应。

## 准备账号与独立模型角色

复制 `07_tools/run.example.json`、`models.example.json` 到包外私有目录。路径按当前运行环境填写，登录文件权限设为 0600，内容为 `username` 和 `password`。owner 是已配置合同记忆的企业管理员；member 是同企业普通账号；outsider 为另一组织的管理员或独立应用实例账号，同样通过既有配置机制绑定 normal Memory User。所有账号先配置本机 OpenCode 和模型，不让测试脚本直接写应用数据库。

默认业务模型示例 `tencentdb-memory/deepseek-flash` 和普通模型 `deepseek/deepseek-flash` 需要以 `/api/models` 的实际 ID 核对。两者属于对话模型。`models.roles.memory_extraction`、`models.roles.judge` 属于提炼和评分，默认 `codex_subscription` / `gpt-6.1-sol`。模型不可用时停止，不自动换成 DeepSeek。

若选择 DeepSeek，把对应角色改为 `models.example.json` 中的 `available_alternative`，API Key 只在指定环境变量中提供。不要将 key 写进示例或 Git。

## Core 提炼订阅适配

官方依据：[认证](https://learn.chatgpt.com/docs/auth)、[非交互调用与结构化输出](https://learn.chatgpt.com/docs/non-interactive-mode)。真实执行前用 `codex login status` 核对 ChatGPT 登录；本机全局自定义 provider 不作为此次配置来源。

适配服务在用户审查后显式启动，按角色使用两个不同的私有 bearer token；Core 只获得 extraction token，judge 直接调用受限本机模型函数。服务默认监听 127.0.0.1:8766。

```sh
python3 07_tools/structured_model.py --config /path/private/models.json --execute --reviewed-pack-sha REVIEWED_SHA
```

这里 `REVIEWED_SHA` 必须替换为 `run_suite.py plan` 输出中用户审查通过的包哈希。服务令牌来自 `CONTRACT_EXTRACTION_ADAPTER_TOKEN` 和 `CONTRACT_JUDGE_ADAPTER_TOKEN`，不共享、不打印。

独立 TencentDB Memory contract 仓库新增 `deploy/contract-memory/contract-model.example.json`。复制成私有配置后，后续使用部署脚本的 `start --contract-model-config /path/private/contract-model.json` 显式重建 Core；此操作留待用户审查后。配置挂载为只读，提炼令牌进入原私有 core.env。普通 chat/code 与 Proxy 业务模型不改动。

Docker 端示例地址为 `http://host.docker.internal:8766/v1/structured-completions`。审查后先检查健康与网络连通性；若本机网络无法从 Docker 访问 loopback 监听，报告不支持，先解决本机路由，不自动改成对外公开监听。

适配每次采用新临时会话，忽略用户配置与规则，关闭 shell、应用、浏览器、记忆、Skills 搜索和多 Agent 工具。输出由固定阶段 Schema 校验；出现工具事件或未知输出时报错。模拟测试不等于真实账号和额度已通过。

## 有序运行

离线查看：

```sh
python3 07_tools/run_suite.py plan > /tmp/contract-memory-plan.json
```

用户审查后，从包根目录执行：

```sh
python3 07_tools/run_suite.py run --config /path/private/run.json --out /path/private/run-001 --execute --reviewed-pack-sha REVIEWED_SHA
python3 07_tools/run_suite.py resume --config /path/private/run.json --out /path/private/run-001 --execute --reviewed-pack-sha REVIEWED_SHA
python3 07_tools/run_suite.py judge --config /path/private/run.json --out /path/private/run-001 --execute --reviewed-pack-sha REVIEWED_SHA
python3 07_tools/run_suite.py report --out /path/private/run-001
```

`run` 要求空输出目录，先核对账号、服务与应用模型 ID，再做两个模型角色的结构化连通性检查，然后创建团队和逐步处理材料。按 HTTP 202 的实际消息 ID、原生 completion_id、队列状态、L0 新记录和提炼作业完成状态等待。默认每步上限 600 秒，轮询 2 秒；提炼状态短暂稳定不是语义成功证明。

每轮材料、模型和账号配置固定。消息 request_id 与记忆 operation_id 写入原子检查点；恢复时沿用相同 payload。无响应的上传、新团队和新会话属于非幂等操作，暂停让操作员核对，不盲目重发。若确认／编辑结果已在 journal 中保存，复用真实回执。

候选按类型、业务内容与来源匹配；无法唯一匹配时暂停并保存 `blocked-observation.json`，不选择“第一条”，不把金标正文写入应用补齐。未知权限和问题请求需人工处理后恢复；不放开通用 bash。

## 只读分层诊断

`snapshot_memory.py` 使用 `sqlite mode=ro` 读取应用身份映射，用只读 Node SQLite 查询 Core。限定当前有效账号、团队、Agent、服务实例，仅导出本人原始记录、L1、候选、正式版本及已发布团队摘要；团队其他成员个人内容和运行凭据不导出。此工具不实例化 Store，不运行迁移，不使用管理员 key。

```sh
python3 07_tools/snapshot_memory.py --config /path/private/run.json --team-id ACTUAL_TEAM_ID --username ACTUAL_USERNAME --out /path/private/checkpoint-snapshot.json
```

完整 Core trace 中实际模型名称可能不可获得；此时保存 `actual_model:null` 与 `model_verified:false`，不把配置名称伪装成服务实际回报。任务和提炼轨迹的 requested_model/provider 必须与审查配置一致。

## 重启、服务失败和恢复检查点

脚本不会直接停止正在服务其他任务的进程。故障及重启步骤只在专用隔离实例人工操作。检查点需要保存原始错误、停止／恢复时间、重启前后快照和续聊回执；然后将证据文件路径填入配置的 `operator_evidence` 对应步骤 ID。

证据 JSON 格式：

```json
{"run_id":"ACTUAL_RUN_ID","step_id":"ACTUAL_CHECKPOINT_ID","artifact_paths":["/absolute/path/before.json","/absolute/path/error.json","/absolute/path/after.json"],"notes":"实际操作和结果"}
```

使用当前步骤清单的 ID，不能复制旧运行 ID。未提供证据时保持暂停，报告 `not_executed`，不默认通过。证据只是原始材料，judge 和人工仍需核对它证明了什么。

## 评分与报告

完整证据保留在运行目录；judge 逐用例接收当前结果和 rubric，使用独立临时会话。被测 Agent 不接触 rubric、gold 或 judge 结果。评分缓存绑定输入和模型配置哈希。引用必须在指定实际来源中存在，且不能以“我记住了”替代真实记录。

报告保留确定性检查、模型判断、引用、关键失败及待复核项。结构失败或关键失败优先于模型的 pass。所有用例未执行／未评分均明确标记；不把模型评分总分宣称为法律准确率。最终验收仍由人工复核。

## 文书重建与视觉 QA

文书构建使用 documents 技能指定的 bundled Python：`build_pack_v2.py` 生成 DOCX／TXT 和来源索引，再用 `build_scenarios_v2.py` 生成统一步骤及手册。任何重建后必须重新审查哈希。

`render_pack.py` 使用 bundled `render_docx.py` 与 LibreOffice，参数显式指定 bundled Python、renderer、字体目录和包外 QA 输出目录。中文正文采用 Arial Unicode MS，清理主题字体覆盖；本机 QA 使用现有系统 Unicode 字体及 bundled 字体目录，显式配置 Fontconfig 后逐页检查，不以 DOCX 文字抽取替代视觉检查。
