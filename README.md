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

已导入 DataSense 上游代码基线，当前版本保留原有 Streamlit 页面、LangChain DataFrame Agent、图表能力和测试辅助脚本。后续改造从电商订单数据接入开始。

当前已完成订单字段映射、数据质量摘要、确定性经营指标、Commerce Agent 工具调用和指标口径 RAG。AI 功能需要在页面中配置对应模型 API Key。

上游原始说明保存在 [UPSTREAM_README.md](UPSTREAM_README.md)，便于核对原项目功能和运行方式。
