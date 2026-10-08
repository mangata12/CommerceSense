# CommerceSense

基于 DataSense 二次开发的电商经营分析 Agent。

第一版目标：

- 上传订单明细并完成经营指标问答；
- 对比两个时间周期，分析商品对销售变化的贡献；
- 使用 LangChain Agent 编排业务分析工具；
- 支持 DeepSeek OpenAI-compatible API；
- 使用 RAG 检索指标口径，并在回答中给出依据；
- 导出带数据依据的经营诊断周报。

## 开源来源

- 上游项目：[DataSense](https://github.com/Saishhhhhh/DataSense)
- 上游许可证：以仓库中的 LICENSE 文件为准
- 本项目仓库：[CommerceSense](https://github.com/mangata12/CommerceSense)

## 当前状态

当前已完成订单字段映射、数据质量摘要、确定性经营指标、Commerce Agent 工具调用和指标口径 RAG。可用性优化阶段 A 已完成：原始数据、字段映射和有效标准数据独立保存，页面交互不再覆盖映射结果；指标、Agent 和图表共用标准数据。

无 API Key 可以应用映射并查看经营指标预览；AI 功能仍需在侧栏配置模型密钥。后续阶段将改造中文导航与连续对话、经营诊断与周报导出，当前尚未提供完整周报。

上游原始说明保存在 [UPSTREAM_README.md](UPSTREAM_README.md)，便于核对原项目功能和运行方式。

## 本地运行

在项目目录中使用 Python 3.12 虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

依赖版本固定与完整部署验收安排在阶段 D；当前虚拟环境的实测版本见 [阶段 A 验收](docs/stage-a-validation.md)。

## 导入与字段映射

1. 上传 CSV 或 Excel（读取第一张工作表）。CSV 支持 UTF-8/UTF-8 BOM 和 GB18030，订单号和商品号按文本读取以保留前导零；Excel 原文件中已作为数字丢失的前导零无法恢复。
2. 明确选择币种（CNY/GBP/USD/EUR）。项目模拟样例使用 CNY，UCI Online Retail 使用 GBP；系统不进行汇率转换。
3. 确认订单号、数量、单价、订单时间四个必填字段。商品编号和商品名称至少映射一个才能进行商品贡献分析；客户编号和地区可选。
4. 查看有效、排除记录及原因，再点击“应用电商字段映射”。更换文件内容或应用新映射会清空旧答案、工具结果和报告；每次映射从原始数据重新生成。
5. 展开“Commerce metrics preview”，选择周期查看指标、相邻周期对比、商品贡献和精确商品下钻。无密钥时底部的提示只针对 AI 功能。

金额按整数分汇总；负数量保留为冲销，负单价及无法精确到分的金额排除。无效日期、空订单号和非有限数值排除；重复明细保留并提示。订单数包含周期内的冲销订单，客单价为“净销售额／周期去重订单数”。详情见 [指标口径](knowledge/commerce_metrics.md)。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

包含 CSV/XLSX、映射与会话生命周期、金额和商品聚合、LangChain 业务工具以及 Streamlit AppTest 页面交互。AppTest 不启动常驻服务、不调用真实模型 API；真实 DeepSeek API 和完整工具调用链验收留待后续阶段单独报告。
