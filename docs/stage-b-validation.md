# 阶段 B：中文界面与连续对话验收

日期：2026-10-08。基线：`63fc8fd`。范围为阶段 B；规则检索阈值、完整经营诊断、周报和部署仍待后续阶段。

## 实现与文件

- `app.py` 改为简洁启动入口；`commerce_ui.py` 承载数据导入、经营概览、分析助手、经营报告四个中文入口。数据质量详情放在导入页，高级工具默认关闭；报告页明确显示阶段 C 待完成。
- `advanced_tools.py` 保留 DataSense 上游的自然语言查询、绘图和数据处理辅助实现。工具操作数据副本，数据处理提示不再要求写入固定的 `output.csv`，由页面提供下载。
- `model_config.py` 统一解析会话／环境密钥、创建模型及脱敏错误。侧栏设置折叠，仅实际调用模型时验证配置；请求超时 45 秒、最多重试 1 次。
- `commerce_conversation.py` 解析明确的日期和精确商品标识，维护周期、对比周期、商品条件，并将历史回答及实际工具记录传入下一轮。支持工具缺少条件时从当前对话条件补全。
- `commerce_agent.py` 使用已安装 LangChain 0.3.30 的 `create_tool_calling_agent`／`AgentExecutor`，移除旧版回退。最多 6 轮工具调用，轮次边界检查运行时间限制。回调只记录工具输入／输出和状态，不导出 action log 或模型内部推理。
- `commerce_session.py` 增加对话清理与重试状态清理；更换数据、重新映射清空旧对话和分析条件。手动清空对话保留数据和页面日期。
- 新增模拟模型传输层、对话与模型配置测试，扩展页面和数据生命周期测试，更新 README。

新增文件：`commerce_ui.py`、`commerce_conversation.py`、`model_config.py`、`advanced_tools.py`、`tests/fake_chat_model.py`、`tests/test_commerce_conversation.py`、`tests/test_model_config.py`、`docs/stage-b-validation.md`。

修改文件：`app.py`、`commerce_agent.py`、`commerce_session.py`、`tests/test_commerce_ui.py`、`tests/test_commerce_lifecycle.py`、`README.md`。

## 验证范围

最终结果：35 项测试全部通过，Python 编译检查及高级工具模块导入检查通过。未调用真实模型 API。

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app.py commerce_ui.py commerce_agent.py commerce_conversation.py commerce_session.py model_config.py advanced_tools.py tests
```

自动验证包含：

1. 真实 LangChain 执行器运行三轮对话：本期指标 → 商品贡献 → 指定新日期查看该商品。模拟模型省略工具日期／商品参数，实际工具仍沿用或更新正确条件；历史消息和订单证据传入下一轮。
2. 当前问题完整日期优先于冲突模型参数，页面周期修改更新默认周期，商品保持或明确取消筛选。
3. 模型在完成指标工具后模拟超时，已完成结果保留，错误脱敏；工具错误及轮次限制明确显示；规则来源确实来自实际知识库检索。
4. 中文四入口、模拟样例一键加载、无密钥经营概览、关闭的高级工具、数据质量详情和报告占位。
5. AppTest 执行聊天提交、缺密钥失败、配置后重试、模型超时后再次重试、清空对话及页面周期保留。
6. 四种服务的真实 SDK 构造函数接受显式密钥、超时和有限重试参数（不请求服务）；会话密钥优先且不写入进程环境变量。
7. 阶段 A 的 CSV/XLSX、前导零、金额、冲销、映射及商品聚合回归用例。

## 验收界限

- 模型测试使用确定性模拟传输层，LangChain 编排、工具调用、指标和规则检索是真实实现。该测试证明接口及条件传递正确，不证明真实 DeepSeek 会作出相同的工具选择或回答。
- 未调用真实 DeepSeek／其他模型 API，未做真实浏览器人工检查；没有启动常驻服务。真实 API 验收留到阶段 D，测试时只有 AppTest 的非服务进程。
- 完整日期解析支持 `YYYY-MM-DD`、`YYYY/MM/DD` 和 `YYYY年M月D日`；未覆盖“上周”“最近几天”等所有自然语言时间表达的解析质量。回答始终显示周期，工具详情可核对实际执行范围。
- 贡献排名后的“该商品”默认对应最近贡献表首项；不明确的多个商品由模型澄清，真实模型的澄清质量未验收。页面订单下钻筛选独立于聊天商品条件，并明确提示。
- TF-IDF 仍使用阶段 A 的检索方式。来源来自实际检索，但无关查询拒绝阈值尚未校准，留在阶段 C。
- 高级工具执行生成代码，不是安全沙箱；当前阶段保留上游能力，不宣称完成代码隔离验收。
- 120 秒 Agent 限制在轮次边界检查，不硬中断正在进行的 SDK 请求；单次模型响应可以请求多个工具。直接依赖版本固定与部署仍在阶段 D。

实测版本：Python 3.12.14、Streamlit 1.64.0、LangChain 0.3.30、langchain-core 0.3.86、langchain-openai 0.3.35、langchain-anthropic 0.3.22、langchain-google-genai 2.1.12。
