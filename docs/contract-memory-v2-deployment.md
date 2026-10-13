# contract-v2 本机启动与恢复

当前工作台 `http://127.0.0.1:8081/spaces`；Core 8430、Proxy 8106。账号 `openharvey-local` 的登录文件位于 `~/.local/share/openharvey/contract-memory-lab/login.json`。所有密钥仅在本机私有文件中，不能加入 Git 或 Agent 目录。

## 当前部署

腾讯组件仓库的 `deploy/contract-memory/manage.py` 根据提示词版本、Git 提交和 TS 源码摘要生成镜像标签，并记录实际 image ID。部署仅启用记忆注入/提取，合同 Skills 使用 OpenHarvey 自带版本。管理命令依赖 Python 和 PyYAML。

组件停止/启动：

```bash
cd /Users/dicam/CodeDir/TencentDB-Agent-Memory-contract
python3 deploy/contract-memory/manage.py stop
python3 deploy/contract-memory/manage.py restart
```

从源码重建：`python3 deploy/contract-memory/manage.py start`。已选择的提炼配置及角色凭据继续从被忽略的 `deploy/contract-memory/state` 加载；Core 健康后才启动 Proxy。

业务订阅桥接按 `docs/business-chatgpt-subscription.md` 启动，默认 8767。提炼桥接使用 `scripts/serve_contract_v2_extraction.py`：

```bash
cd /Users/dicam/CodeDir/OpenHarvey
.venv/bin/python scripts/serve_contract_v2_extraction.py \
  --state-root /Users/dicam/.local/share/openharvey/contract-v2-experiment/20261013 \
  --execute --reviewed-pack-sha 3f301503aaef1e654a948e02973df6699f38c0ddf4230787d399d492e22d4d68
```

该服务读取私有 `models.json` 和两个不同角色 token，仅允许注册的结构化阶段；Docker 经 `host.docker.internal:8766` 访问。推理仍有原时限，并发 429 在 Core 端有界重试。

工作台启动：

```bash
.venv/bin/python scripts/run_tencentdb_local.py \
  --data /Users/dicam/.local/share/openharvey/contract-memory-lab \
  --port 8081 --username openharvey-local --require-login --contract-memory \
  --admin-key-file /Users/dicam/CodeDir/TencentDB-Agent-Memory-contract/deploy/contract-memory/state/admin.key \
  --memory-control-key-file /Users/dicam/CodeDir/TencentDB-Agent-Memory-contract/deploy/contract-memory/state/control.key \
  --core-url http://127.0.0.1:8430 \
  --proxy-url http://127.0.0.1:8106/opencode/default/v1
```

省略 `--require-login` 会启用既有的本机预览自动登录；多角色验证应保持该参数。全局 OpenCode 安装不修改，使用脚本原有隔离 `1.16.2` 路径。

本轮服务进程已独立启动并保留私有日志，不依赖本聊天的终端会话；未设置系统开机自启。重启电脑后按桥接 → Core/Proxy → 工作台恢复，不能启动第二个占用相同端口的进程。

## 一致性备份与回退

升级前已在没有运行中任务时停止应用及两个组件，复制应用数据、两个数据卷、私有配置和旧镜像 inspect 到：

`~/.local/share/openharvey/contract-v2-experiment/20261013/backup-before-v2/`

实验生成的数据与旧数据均保留。需要回退时：先停止任务及服务；把当前数据另存为失败现场；恢复备份的应用数据、两个卷和配置；使用匹配的旧应用源码与保存的镜像 ID 启动。SQLite 已发生迁移，禁止仅切换镜像而继续使用新数据库。旧配对应用的回退没有在本轮演练，不把恢复备份宣称为已测试通过。

## 实验重跑

原包保持审查哈希；每次 `run` 使用全新输出目录及团队，已有运行用 `resume`。补充脚本均要求 `--execute --reviewed-pack-sha`，权限及模型输入校验保留。私有运行配置在上面的实验目录 `run.json`，正式执行前核验登录文件及服务。

核心套件入口 `openharvey_contract_memory_pack/07_tools/run_suite.py`；本轮新增的 `validate_contract_v2_*` 工具分别执行权限、并发风险、偏好、L2 正文、来源状态、重启和故障检查。`export_contract_v2_native.py`、`audit_contract_v2_evidence.py` 为只读证据补充；judge 只读取冻结结果，结果不回流到记忆。

已运行结果与未覆盖范围见 [在线实验报告](evidence/contract-memory-v2-live/README.md)。
