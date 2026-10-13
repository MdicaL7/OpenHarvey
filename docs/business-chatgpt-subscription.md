# 业务对话接入 ChatGPT 订阅

合同实验账号原业务模型为 `tencentdb-memory/deepseek-flash`。现在增加
`tencentdb-memory/gpt-6.1-sol`，作为该账号的新默认选择。既有会话保存的模型选择
不批量修改；可以在对话模型菜单手动切换。DeepSeek 和记忆入口继续保留。

```text
OpenHarvey → 隔离 OpenCode → 腾讯合同 Memory Proxy（8106）
                            ├─ 身份、Task、Conversation、记忆注入及 L0
                            └─ 本机业务桥接（8767）
                               ├─ gpt-6.1-sol → 官方 Codex CLI → ChatGPT 订阅
                               └─ deepseek-flash → 原 DeepSeek API
```

业务桥接与测试包的 `memory_extraction`、`judge` 是三个独立角色。此次不改变 Core
提炼模型、不启动测试包、不运行真实抽取或评分，不代表已通过合同记忆完整验收。

官方 Codex 支持 [ChatGPT 订阅登录](https://learn.chatgpt.com/docs/auth) 和
[非交互结构化输出](https://learn.chatgpt.com/docs/non-interactive-mode)。本方案使用
官方 CLI 的已有登录，不导出 OAuth token 到浏览器、OpenCode、Docker 或 Git。
默认模型的可用性以实际调用结果为准，不以缓存目录或健康检查代替推理成功。

## 调用方式及首版限制

桥接接收 Proxy 转发的完整有序消息、可用函数工具和工具选择，调用一次独立的
Codex 结构化推理，返回下一条文本或函数调用。**OpenCode 执行工具**并把真实结果
送入下一次推理。桥接自身不读合同、不执行工具、不写成果。

每次推理使用新临时会话、只读沙箱；关闭仓库规则、个人配置、Skills、插件、
记忆、搜索、Shell 和 Code Mode 等工具。只允许结构化文本结果，真实工具事件、
失败回合及不完整输出均拒绝。当前 CLI 的精确“Code Mode 已禁用”启动提示属于
非失败提示，仍须收到成功完成的回合。错误不回退到其他模型。

输出通过 Chat Completions 和 SSE 兼容接口返回。**SSE 在结构化结果生成后才发送**，
不是原生逐 token 传输，因此首段正文有等待；输入首版仅支持文本，DOCX 等资料
仍通过 OpenCode 原有文档工具读取。函数名、JSON 参数、tool_choice 和并行限制
在桥接校验，工具自身参数和访问权限继续由 OpenCode 检查。

`model` 字段表示请求模型；CLI 未提供解析后的实际模型 ID 时不宣称已独立核验该
ID。订阅额度与账号权限错误会显示失败，不静默切换到 API Key。

## 本机启动与配置

本机登录先运行 `codex login` 并选择 ChatGPT。示例均在 OpenHarvey 仓库运行：

```bash
.venv/bin/python scripts/manage_business_subscription.py prepare
.venv/bin/python scripts/manage_business_subscription.py serve
```

另一个终端执行激活，仅重启合同 Proxy，不重启 Core：

```bash
.venv/bin/python scripts/manage_business_subscription.py activate \
  --memory-control-key-file /Users/dicam/CodeDir/TencentDB-Agent-Memory-contract/deploy/contract-memory/state/control.key

.venv/bin/python scripts/run_tencentdb_local.py \
  --data "$HOME/.local/share/openharvey/contract-memory-lab" \
  --port 8081 --contract-memory \
  --admin-key-file /Users/dicam/CodeDir/TencentDB-Agent-Memory-contract/deploy/contract-memory/state/admin.key \
  --memory-control-key-file /Users/dicam/CodeDir/TencentDB-Agent-Memory-contract/deploy/contract-memory/state/control.key \
  --core-url http://127.0.0.1:8430 \
  --proxy-url http://127.0.0.1:8106/opencode/default/v1
```

工作台：<http://127.0.0.1:8081/spaces>，账号 `openharvey-local`。登录文件仍位于
`~/.local/share/openharvey/contract-memory-lab/login.json`。模型菜单选择
“ChatGPT 订阅 · gpt-6.1-sol（合同记忆）”。当前本机服务未设置系统开机自启；重启电脑
后先启动桥接，再启动工作台。

状态目录为 `~/.local/share/openharvey/chatgpt-business`，目录权限 700、文件 600。
`bridge.json` 含私有桥接 token 和原 DeepSeek 转发凭据；`proxy-backup.json` 保存
原 Proxy 配置，`registry-backup.json` 保存个人模型菜单与默认选择。都不进入 Git
或 Agent 工作目录。Memory 控制凭据只由配置命令读取，不进入模型输入。

Docker Desktop 经 `host.docker.internal` 调用桥接，默认监听 `0.0.0.0:8767`，所有
推理和模型列表接口都要求独立桥接 token。健康接口不泄漏凭据、不调用模型。
仅合同 Proxy 使用桥接；普通直连 provider 不使用此链路。选择 DeepSeek 的合同
路径也依赖桥接进程；桥接关闭时可以选择原有普通直连模型，或执行恢复。

## 恢复

```bash
.venv/bin/python scripts/manage_business_subscription.py rollback
```

恢复原 Proxy 上游、个人模型菜单和账号默认模型，然后重启工作台让隔离 OpenCode
读取新配置。合同、Task、Conversation 和记忆数据不迁移或删除。

## 验证

离线测试：`tests/test_subscription_model.py`，覆盖消息与工具结果往返、工具拒绝、
模型失败、超时/不完整结果、工具选择限制、SSE、认证及精确启动提示识别。
接口健康、Docker 到桥接的网络、模型菜单与默认选择分别检查。

真实连通性仅使用不含合同与记忆的短消息。另在隔离 OpenCode 1.16.2 中实际读取独立
临时文件，验证模型函数调用 → OpenCode read → 真实结果 → 模型回答的完整往返。
此检查的可重复入口如下，默认不执行模型：

```bash
.venv/bin/python scripts/check_business_subscription.py
.venv/bin/python scripts/check_business_subscription.py --execute
```

同时经腾讯 Proxy 实际发送一条标题生成辅助请求，返回 HTTP 200；Proxy 日志确认
跳过会话初始化、注入、L0 与 Skill 提炼。没有调用测试包材料、记忆提炼或 judge。
完整合同读取、成果保存和跨会话记忆测试仍需遵守测试包审查后的运行步骤。
