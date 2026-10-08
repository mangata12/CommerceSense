# 阶段 D：本地验收与 GitHub 收尾

日期：2026-10-08；基线提交：`dede5df`；环境：Windows、CPython 3.12.14、项目 `.venv`。本记录只列实际执行结果，云端部署不在本阶段内。

## 实现与文件

- `requirements.txt`：将直接依赖区间固定为当前已验证版本；不宣称完整传递依赖锁定或跨平台复现。
- `commerce_data.py`、`commerce_ui.py`：明确支持 CSV/XLSX，旧 XLS 给出另存为 XLSX 的提示。当前没有 `xlrd`，不再让页面接受一个未支持的格式。
- `tests/test_release.py`：新增真实 CSV/XLSX 读取→中文映射→质量检查→诊断→CSV 报告的完整对账；验证 XLS 格式边界。
- `tests/test_commerce_ui.py`：确认当前和对比日期控件均为范围选择器。
- `scripts/export_demo_report.py`：无需模型导出公开模拟数据报告，生成文件仅放在被忽略的 `outputs/`。
- `scripts/verify_deepseek.py`：可选真实 API 工具问答验收，使用公开模拟数据，未配置密钥时明确 skipped；不输出密钥。
- `README.md`、`docs/local-use.md`、`docs/report-example.md`、本记录：补齐启动、数据格式、四个界面入口、报告核对和限制。

## 自动验收结果

| 检查 | 实际结果 |
| --- | --- |
| 全部 `unittest` 测试 | **50 项通过**，本次 14.832 秒；时间不是产品性能指标 |
| `compileall` | 应用、业务模块、高级工具、scripts、tests 编译通过 |
| `pip check` | `No broken requirements found` |
| 固定依赖匹配 | `pip install --dry-run --no-index -r requirements.txt` 通过，依赖已在环境安装；不是全新环境安装测试 |
| 规则校准／验证 | 测试实际执行 16 条校准和 8 条独立验证查询，均通过；阈值 0.13，未宣称通用成功率 |
| 无密钥基础报告 | 实际导出 Markdown、CSV、PNG、ZIP；当前 4490 分、对比 8870 分、变化 -4380 分 |
| 真实 DeepSeek | `status=skipped`；没有检测到进程密钥、项目 `.env` 或 secrets 配置，未调用 API |

核心测试覆盖 CSV 的 UTF-8/GB18030 与 XLSX 文本编号、中文映射、重复交互、重新映射、换文件清空状态、金额精度、非有限数值、冲销、重复明细、结束日全天、空周期、零基期、客户缺失、同名不同编号和完整商品变化对账。

新增整链用例同时读 CSV 与 XLSX：5 条有效、1 条无效日期排除、1 条重复保留；当前 190 分、对比 50 分、变化 140 分；编号 `0003`、商品 `01/02` 和数量 `0.125` 在订单证据 CSV 中保留。

LangChain 使用真实 `create_tool_calling_agent` 与 `AgentExecutor`，仅模型传输层模拟。已检查三个连续问题保留历史、修改日期／商品条件、真实工具有效参数和结果、内部推理不导出、超时保留完成结果、工具失败、轮次限制及规则真实来源。模拟链不等价于真实 DeepSeek 验收。

Streamlit AppTest 实际运行与重跑页面，检查无密钥四入口、映射、日期变化、错误重试、清空对话、报告生成、五个下载按钮、页面／CSV 金额一致、可选 AI 失败仍能下载、改变周期清除旧报告。AppTest 的 bare-mode `missing ScriptRunContext` 提示不代表测试失败。

## 临时服务检查

运行命令：

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8511 --server.headless true --browser.gatherUsageStats false
```

实际启动于本机 127.0.0.1:8511；`/_stcore/health` 返回 `ok`，首页返回 HTTP 200 和 HTML 入口。已按 Ctrl+C 停止，随后 socket 连接检查确认 **8511 端口关闭**。没有留下常驻服务。

浏览器自动化工具两次初始化均返回 `trusted Node process exited unexpectedly; kernel reset`，未成功打开目标页面。本次**未验证浏览器实际渲染、人工点击或浏览器下载内容**；HTTP 入口与 AppTest 检查不能代替此项。

## 复现命令

```powershell
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m pip install --dry-run --no-index -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q app.py commerce_data.py commerce_metrics.py commerce_agent.py commerce_conversation.py commerce_session.py commerce_ui.py commerce_diagnosis.py commerce_report.py report_charts.py report_ui.py rag_knowledge.py model_config.py advanced_tools.py scripts tests
.\.venv\Scripts\python.exe scripts/export_demo_report.py
.\.venv\Scripts\python.exe scripts/verify_deepseek.py
```

## 待完成与边界

- 可用真实 DeepSeek 配置下的工具问答、多轮质量、错误与重试表现；当前脚本的单轮检查通过也不能代替多轮质量验收。
- 浏览器工具恢复后的实际渲染、点击和下载检查。
- 从空虚拟环境联网安装、Linux／云服务器部署和中文字体验收。
- 大数据性能、内存占用和多会话并发，本轮只做功能与边界检查。
- 数据指标不等同支付宝实际入账、不自动换汇、不证明变化原因；高级工具仍有模型生成代码执行能力。

推送前检查仅提交指定代码、测试和文档；密钥、虚拟环境、原始上传数据和生成报告继续被排除。GitHub 提交以本阶段完成后的 main 提交及最终远端核对为准。
