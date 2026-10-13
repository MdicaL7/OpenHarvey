# 华子合同记忆评测包 v2

当前交付状态：**材料与工具离线验证，真实实验未执行，等待人工审查测试集**。

先阅读 [审查入口](10_manual/REVIEW_CHECKLIST.md)、[条款与要点对照表](10_manual/CLAUSE_COVERAGE.md)，再检查 [人工逐步手册](10_manual/MANUAL_TEST.md) 和 [自动路径说明](10_manual/AUTOMATED_TEST.md)。两条路径共用 `09_scenarios_OPERATOR_ONLY/steps.json`；不要整包上传给 Agent。

本包包含 10 份原合同及 1 份新合同修订稿，154 个完整合同条款，21 份独立业务事件，58 个用例、12 类要点和 156 个顺序步骤。原 Q01–Q24 保留可追踪标识；Q21/Q22 改为实际审阅与更新操作，并在尚未接触后续材料的时点检查。素材是原创合成数据；公司名称不构成登记或身份凭证，签署栏均为空。来源说明统一放在操作员文档；业务文书正文不含测试目的或内部测试锚点。来源背景见 [来源说明](00_start_here/SOURCES.md)。

## 从哪里开始审查

| 内容 | 文件 |
| --- | --- |
| 11 份正常格式合同与修订稿 | `01_history/contracts_docx`、`03_future/contracts_docx`；TXT 是同内容的备用格式 |
| 审阅、审批、政策、撤回和执行记录 | `02_review_writeback/event_files` |
| 自然对话偏好建立／临时要求／长期更新／撤回 | `09_scenarios_OPERATOR_ONLY/dialogues.json` |
| 每条条款的用途、用例和层级 | `10_manual/CLAUSE_COVERAGE.md` |
| 每一步上传、对话、确认、等待和检查 | `10_manual/MANUAL_TEST.md` |
| 可执行的接口流程、模型设置与恢复方法 | `10_manual/AUTOMATED_TEST.md` |
| 候选与正式版本、来源、权限和评分标准 | `00_start_here/SCORING.md` |

每次实际运行创建全新团队；每份合同一个新工作空间。同一合同的新会话仍对应同一 Task。新建空间本身不会清空团队记忆。个人经验与偏好范围是实例＋Team＋Agent＋User，团队版本范围是实例＋Team＋Agent；当前 contract 模式不存在组织级 L3 共享。自动和人工两次运行使用不同团队。

## 三个层级分别验证什么

- **L1 原子记录**：本份合同与实际处理过程的事实、意见、建议、决定、执行结果及偏好是否正确；条件、有效状态和原文引用能否核验。
- **L2 过往经验**：是否从具体案例形成带条件的方法，并在不附历史材料的新合同中真实召回；不适用案例需要被排除。
- **L3 工作偏好与约定**：明确长期要求或已确认经验形成的原则是否跨会话生效；临时要求不变成长期偏好，偏好不能覆盖合同原文和有效制度。

L2/L3 自动输出先进入草稿区。确认／修改后确认才成为个人正式版本；团队共享需要提交独立申请并由团队管理员审核。确认记忆不代表合同事项已经批准。L0/L1 仍可受权限约束查询，不能把“草稿不进入正式召回”解释为全部历史完全不可见。上传不等于实际读取，模型口头确认不等于记忆落盘。

## 本轮可运行的离线命令

在本包根目录执行：

```sh
python3 07_tools/validate_pack.py
python3 -m unittest discover -s 07_tools/tests -v
python3 07_tools/run_suite.py plan > /tmp/contract-memory-plan.json
```

这些命令不接入应用，不调用真实模型。真实运行的 `run`、`resume`、`judge` 必须同时提供 `--execute` 和人工审查通过版本的 `--reviewed-pack-sha`。审查后修改材料或脚本会改变包哈希，旧运行不能继续。密钥、登录凭据和运行结果放在包外私有目录，不能提交 Git。

## 文件与输入边界

只把合同 DOCX（或等价 TXT 二选一）、主体简称说明、当步允许的独立业务事件上传。自然对话脚本逐句发送，不上传整个脚本。

`00_start_here` 的清单、`02_review_writeback/operator_only_indexes`、`04_queries` 全题集、`05_private_gold_DO_NOT_INGEST`、`07_tools`、`08_validation`、`09_scenarios_OPERATOR_ONLY` 和 `10_manual` 均为操作员资料，不进入被测 Agent。只发送当前步骤指定的问题，不一次性透露后续条件和答案。

跨组织负例只允许独立 outsider 组织或独立应用数据目录摄入。脚本读取组织映射核验隔离；同组织的另一个团队用于团队隔离测试，不能替代跨组织测试。

`materialize_stage.py` 仍提供旧时点的因果 TXT 子集，适用于单独重建环境验证；v2 的主要入口是有序步骤清单。Q21 在保函核验之前，Q22 在内部撤回之后、双方补充约定和六月政策之前。不能在已知未来更新的团队中回拨问题日期。

## 模型和验收范围

业务对话模型沿用应用中现有配置。记忆提炼及 judge 的配置互相独立，示例默认 ChatGPT 订阅 `gpt-6.1-sol`，DeepSeek `deepseek-flash` 作为显式 API 备选。订阅适配使用官方 Codex CLI，独立会话、结构化输出、官方 provider 和受限工具配置；不把订阅登录凭据当 API Key。

这次只做适配的模拟测试。实际模型可用性、订阅额度、Docker 到本机适配器的连通性及最终提炼效果，在审查通过后检查。未启动适配服务、未重建运行中 Core、未更换现有模型设置。

同模型抽取和 judge 属于同模型评估，独立会话不能消除模型偏差。结构检查、模型评分与人工复核分开报告；缺失或不确定证据不算通过。详细报告及已知边界见 `08_validation/QA_SUMMARY.md`。

## contract-v2 处置语义更新

默认自动路径已切换到 contract-v2，包含9个用例和27步：真实审查报告 → 保存风险反馈 → L1处置案例 → 新合同参考 → 多案例L2 → 长期L3 → 撤回/人工保护。完整手册见 `10_manual/CONTRACT_V2.md`，来源锚点及对话步骤见 `09_scenarios_OPERATOR_ONLY/v2_cases.json`。

```bash
python3 07_tools/run_suite.py plan
python3 07_tools/run_suite.py plan --suite legacy
```

旧58用例保留为历史对照，不在新版真实执行。原来的 L1 条款字段金标继续用于原文/证据准确性审查，不再要求无处置的条款成为长期记忆。

现有材料没有60天付款账期；v2用户保存的是拟调整到60天的附条件意见，必须与现稿、正式批准和实际执行区分。不得为制造风险命中而改报告或金标。缺少真实风险项、候选不唯一时停止并保留证据。

真实运行仍需 --execute 和重新审查通过的当前包哈希。本轮仅模拟和离线验证，未调用模型抽取或 judge。
