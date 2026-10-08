# 阶段 C：规则检索与完整经营周报验收

日期：2026-10-08。基线：`daca2e5`。本阶段完成规则级检索、统一经营诊断、基础周报和下载；环境固定、真实 API、临时服务及云端部署验收仍留待后续阶段。

## 实现与文件

新增：

- `commerce_diagnosis.py`：诊断结果对象与统一入口；复用确定性指标、完整商品变化、重点商品完整订单证据、每日趋势和固定规则绑定。
- `commerce_report.py`：统一金额格式、中文 Markdown、CSV、Manifest 和 ZIP；不调用模型、不执行生成代码。
- `report_charts.py`：固定净销售额趋势和商品变化 PNG，数据直接来自诊断对象。
- `report_ui.py`：无密钥生成、预览、五个下载入口与可选 AI 解读；周期变化使旧报告失效。
- `scripts/calibrate_rules.py`、`tests/fixtures/rule_queries.json`、`docs/rule-calibration.json`：固定校准／验证查询、实际分数及语料 SHA-256。
- `tests/test_commerce_report.py`、本验收文档。

修改：`rag_knowledge.py`、`knowledge/commerce_metrics.md`、`commerce_metrics.py`、`commerce_agent.py`、`commerce_conversation.py`、`commerce_session.py`、`commerce_ui.py`、`tests/test_rag_knowledge.py`、`tests/test_commerce_conversation.py`、`tests/test_commerce_ui.py`、`README.md`。

经营概览新增共享对比周期；助手和报告使用相同页面条件。Agent 新增 `diagnose_business` 工具，一次返回经营诊断、真实规则来源和证据数量；对话中的证据预览最多 100 条，报告 CSV 则包含所选重点商品的完整记录。

金额仍按整数分计算和对账。导出财务金额固定两位小数并保留 `*_minor`；有效小数数量不再被统一截为两位，以免 0.125 等有效数量在报告中被误写为 0.12。

## 检索校准结果

13 条独立版本化规则，阈值 0.13。阈值选择依据为校准负样本最大分数 0.124478 向上取两位小数，低于校准正样本目标规则最小分数 0.145672。16 条校准查询通过 16 条，8 条独立验证查询通过 8 条。

负样本包含“商品图片如何去除水印”“订单系统登录失败怎么办”等有业务词语重合的无关问题；无命中时 `status=not_found`、原文和来源为空，不伪造依据。原始结果、规则语料摘要及样本见校准 JSON。该结果仅覆盖固定样本，TF-IDF 不是通用语义判断器，其他查询仍可能误召回或漏召回。

报告中的规则使用固定指标与函数绑定直接获取；检索规则用于解释，Markdown 原文变更或新增规则不会执行代码或自行更改计算公式。测试将净销售额文本改为错误公式并新增未绑定规则，数值计算仍保持原结果。原文与代码是否一致仍需规则维护者审阅。

## 验证方法与范围

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app.py commerce_data.py commerce_metrics.py commerce_agent.py commerce_conversation.py commerce_session.py commerce_ui.py commerce_diagnosis.py commerce_report.py report_charts.py report_ui.py rag_knowledge.py scripts tests
.\.venv\Scripts\python.exe scripts/calibrate_rules.py --output docs/rule-calibration.json
```

最终回归结果：48 项单元、工具链及页面交互测试全部通过（本次运行 12.977 秒），上述 `compileall` 编译检查通过。计时仅记录本机本次测试耗时，不作为产品性能指标。

覆盖：

- 12 个同名不同编号商品完整计算，变化之和为 660 分；前 10 名以外 2 个商品变化合计 10 分，报告明确说明且 CSV 保留全部商品。
- 每日净销售额合计与各周期指标一致；无订单日期填零；零总变化时正负商品变化保留、贡献百分比不适用。
- 151 条订单证据完整导出，保留前导零与 GBP 币种；对话预览为 100 条并说明总条数。
- ZIP 包内 Markdown、四份 CSV、Manifest、两张 PNG 完整，金额、日期和规则引用可以对账。
- 空周期、零基期、客户字段缺失、商品字段缺失分别说明；可用基本指标报告，不伪造客户或商品结果。
- 输入数据修改不影响已生成诊断快照；可选模拟 AI 解读不改变 CSV 或图表。
- AppTest 实际点击生成、验证五个下载入口，核对页面与 CSV 金额；AI 无密钥失败保留报告，修改对比周期清除旧下载。
- 模拟模型驱动真实 LangChain `diagnose_business` 工具链，核对共享周期、指标、商品变化及真实规则来源。
- 全部阶段 A/B 的数据导入、金额、会话、配置和错误回归。

公开模拟样例人工可核对：当前 2026-09-08 至 2026-09-09，净销售额 44.90 CNY；对比 2026-09-01 至 2026-09-02，净销售额 88.70 CNY，变化 -43.80 CNY。两张 PNG 已通过本地图片检查，中文字体和标签可见，无图表内容裁切。

## 验收界限

- 没有调用真实 DeepSeek／其他模型 API；模拟模型测试验证编排和接口，不代表真实模型问答或解读质量。模型解读始终单独标注，需人工核对。
- 页面采用 Streamlit AppTest 验证，不代表真实浏览器手动验收；没有启动常驻服务。完整临时服务检查留待阶段 D。
- 只验证模拟样本及边界用例，尚未开展大数据量导入、诊断或导出性能测试；报告缓存在当前 Streamlit 会话内，大数据导出可能占用较多内存。
- 图表本地采用可用中文字体，未验收 Linux 字体；未安装 CJK 字体时中文字形可能不完整。
- 单独下载 Markdown 的图表使用相对路径，完整图表请下载 ZIP 并解压。CSV 文本编号需要在 Excel 中按文本导入，文件本身保留前导零。
- 全数据集排除记录不能可靠分配到某一周期；重点商品证据不是全部商品的全部订单。周期重叠时同一记录会分别进入两个周期，报告明确说明。
- 高级工具继续保留上游代码执行能力，不是安全沙箱；本阶段固定诊断和报告流程不执行模型生成代码。
