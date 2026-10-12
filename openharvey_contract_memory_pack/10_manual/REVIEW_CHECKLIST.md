# 测试集人工审查入口

状态：材料和工具已离线验证，真实模型／真实实验未执行。审查通过后再批准包哈希。

## 建议审查顺序

1. 浏览下方合同与业务事件，检查文书真实感、条件和业务语义。
2. 阅读 [条款对照表](CLAUSE_COVERAGE.md)，检查每条条款为什么存在。
3. 阅读 [逐步手册](MANUAL_TEST.md)，确认从新团队、新空间逐文件对话的过程符合预期。
4. 阅读 [自动测试说明](AUTOMATED_TEST.md)，核对两个模型角色和暂停／恢复方式。
5. 审查完成后批准当前包哈希；修改过任何材料或脚本后重新审查。

## 合同清单

|逻辑文件|正常编号|版本|可编辑文书|
|---|---|---|---|
|H01|HZ-CG-2026-001|R1|[H01_工业控制终端采购合同](../01_history/contracts_docx/H01_工业控制终端采购合同.docx)|
|H02|HZ-XS-2026-001|R1|[H02_控制终端配套组件销售合同](../01_history/contracts_docx/H02_控制终端配套组件销售合同.docx)|
|H03|HZ-CG-2026-002|R1|[H03_流程协作软件试点服务合同](../01_history/contracts_docx/H03_流程协作软件试点服务合同.docx)|
|H04|HZ-CG-2026-003|R1|[H04_商品目录数据清洗服务合同](../01_history/contracts_docx/H04_商品目录数据清洗服务合同.docx)|
|H05|HZ-XS-2026-002|R1|[H05_设备运行数据处理服务合同](../01_history/contracts_docx/H05_设备运行数据处理服务合同.docx)|
|H06|HZ-CG-2026-004|R1|[H06_产品交流会会务服务合同](../01_history/contracts_docx/H06_产品交流会会务服务合同.docx)|
|F01|HZ-CG-2026-005|R1|[F01_工业控制终端补充采购合同](../03_future/contracts_docx/F01_工业控制终端补充采购合同.docx)|
|F02|HZ-XS-2026-003|R1|[F02_协同接口开发及许可服务合同](../03_future/contracts_docx/F02_协同接口开发及许可服务合同.docx)|
|F03|HZ-CG-2026-006|R1|[F03_流程协作软件年度服务合同](../03_future/contracts_docx/F03_流程协作软件年度服务合同.docx)|
|F04|HZ-CG-2026-007|R1|[F04_商品知识库数据加工服务合同](../03_future/contracts_docx/F04_商品知识库数据加工服务合同.docx)|
|F01-R2|HZ-CG-2026-005|R2|[F01_R2_工业控制终端补充采购合同](../03_future/contracts_docx/F01_R2_工业控制终端补充采购合同.docx)|

历史合同的审批及更新材料在 `02_review_writeback/event_files`；未来合同没有实际最终审批结果。修订稿仅改变未来合同交付迟延条款，不伪造已签署新版本。

## 覆盖清单

|要点|层级|用例|正例／反例|
|---|---|---|---|
|L1 事实准确性|L1|Q02, Q15, Q23|2 / 1|
|L1 信息性质|L1|Q12, Q19, L1-NATURE, L1-EXECUTION|1 / 3|
|L1 证据与状态|L1|Q05, Q06, Q16, Q17, L1-READ, L1-VERSION|3 / 3|
|L2 经验沉淀|L2|L2-PUBLISH, L2-UNRELATED|1 / 1|
|L2 跨合同适用|L2|Q01, Q03, Q04, Q07, Q10, Q13, Q24, L2-ROLE|2 / 6|
|L3 用户偏好|L3|Q11, L3-LONG, L3-TEMP|1 / 2|
|L3 原则形成|L3|L3-PRINCIPLE, L3-NO-GENERALIZE|1 / 1|
|候选与正式记忆|L1/L2/L3|Q21, CONFIRM-PUBLISHED, L2-DRAFT|1 / 2|
|更新与冲突|L1/L2/L3|Q08, Q09, Q18, Q22, L3-UPDATE, L3-WITHDRAW, L2-UPDATE, CONFLICT-CONDITIONS|5 / 3|
|人工保护|L2/L3|PROTECT-EDIT, PROTECT-IGNORE, PROTECT-DELETE, PROTECT-IDEMPOTENT, PROTECT-STALE|2 / 3|
|作用范围|L1/L2/L3|Q14, Q20, SCOPE-THREAD, SCOPE-TASK, SCOPE-TEAM, SCOPE-USER, SCOPE-SHARE, SCOPE-REVOKE|3 / 5|
|可靠性|L0/L1/L2/L3|RUN-ASYNC, RUN-RESUME, RUN-FAIL, RUN-RESTART, RUN-ORDINARY, RUN-AUX|3 / 3|

## 审查时需要确认

- 60%预付、60天账期、20%预付款保障是不同信息，没有被混为一个规则。
- 个案、长期偏好、正式制度、记忆确认和合同批准分别表达。
- 早期提问没有提前提供保函核验、双方补充约定或新政策。
- 不把候选正文或金标直接灌入记忆制造成功；确认操作选择系统真实生成的候选。
- 跨合同召回不靠再次上传历史文件；其他团队、用户和组织分别测试。
- 服务故障与重启在专用隔离实例人工操作，自动报告保留原始证据及未执行状态。

## 实验前能力边界

本轮不证明真实模型已完成抽取，也不证明 CLI 账号额度、Docker 连通性和全部语义已通过。后续真实运行出现候选缺失／歧义、来源核验失败、模型配置不一致或后台失败时，脚本暂停保留证据，不自动创建金标记忆或静默换模型。

## 审查记录

审查人：____

批准的包哈希：____

需要调整的文件、条款、用例及理由：____

审查结论：待调整 / 通过，可进入真实实验。
