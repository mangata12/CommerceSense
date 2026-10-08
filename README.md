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

当前已完成订单字段映射、数据质量摘要、确定性经营指标、Commerce Agent 工具调用、版本化规则 RAG 和经营周报。阶段 A/B/C 的功能及阶段 D 的本地自动验收、直接依赖固定和使用文档已完成；含交互和绘图修复共 64 项测试通过。真实 DeepSeek API 和浏览器实际渲染尚未验收，详见 [阶段 D 记录](docs/stage-d-validation.md) 和 [交互修复记录](docs/interaction-fix-validation.md)。

无 API Key 可以导入数据、加载模拟样例、查看完整经营概览并生成基础周报。模型仅用于分析助手、高级工具或可选 AI 解读，调用时再检查配置；支持当前会话密钥或启动环境变量，不由页面写入进程环境变量。云端部署仍未验收。

上游原始说明保存在 [UPSTREAM_README.md](UPSTREAM_README.md)，便于核对原项目功能和运行方式。

初次学习项目可阅读 [从零理解 CommerceSense：业务、源码、Agent 与面试](docs/project-walkthrough.md)，包含源码阅读顺序、逐段解释、简历表达边界和动手练习。运行 `.\.venv\Scripts\python.exe scripts/learn_project.py` 可用三条模拟订单走通数据、检索、真实 LangChain 工具执行及报告导出；模型响应预先模拟，无需密钥、不调用真实模型 API，输出保存在 `outputs/learning_demo/`。

## 本地运行

在项目目录中使用 Python 3.12 虚拟环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501 --browser.gatherUsageStats false
```

打开 `http://127.0.0.1:8501`，终端按 Ctrl+C 停止。`requirements.txt` 固定当前 Windows / CPython 3.12.14 验证过的直接依赖，不是所有传递依赖或跨平台的完整锁文件。详细启动、四个入口、导入格式与故障排查见 [本地使用指南](docs/local-use.md)。

项目的 `.streamlit/config.toml` 为本地开发开启轮询检测和保存后重跑，排除虚拟环境及数据、输出目录。已有旧服务需要重启一次才能读取该配置；仅刷新浏览器不保证清除后台导入模块。上线时可覆盖 `--server.runOnSave false`。更新后应核对实际服务的高级工具输入表单和局部刷新行为，不能只凭健康检查判断代码已更新。

实测范围见 [阶段 A](docs/stage-a-validation.md)、[阶段 B](docs/stage-b-validation.md)、[阶段 C](docs/stage-c-validation.md)、[阶段 D](docs/stage-d-validation.md)。

## 导入与字段映射

1. 上传 CSV 或 XLSX（读取第一张工作表）；旧版 XLS 请先另存为 XLSX。CSV 支持 UTF-8/UTF-8 BOM 和 GB18030，订单号和商品号按文本读取以保留前导零；Excel 原文件中已作为数字丢失的前导零无法恢复。
2. 明确选择币种（CNY/GBP/USD/EUR）。项目模拟样例使用 CNY，UCI Online Retail 使用 GBP；系统不进行汇率转换。
3. 确认订单号、数量、单价、订单时间四个必填字段。商品编号和商品名称至少映射一个才能进行商品贡献分析；客户编号和地区可选。
4. 查看有效、排除记录及原因，再点击“应用电商字段映射”。更换文件内容或应用新映射会清空旧答案、工具结果和报告；每次映射从原始数据重新生成。
5. 进入“经营概览”，选择当前和对比周期查看指标、商品贡献和精确商品下钻。整个过程无需 API Key。

金额按整数分汇总；负数量保留为冲销，负单价及无法精确到分的金额排除。无效日期、空订单号和非有限数值排除；重复明细保留并提示。订单数包含周期内的冲销订单，客单价为“净销售额／周期去重订单数”。详情见 [指标口径](knowledge/commerce_metrics.md)。

## 中文界面与连续问答

| 入口 | 功能 |
| --- | --- |
| 数据导入 | 上传、加载模拟样例（CNY）、币种与映射、数据质量详情 |
| 经营概览 | 指标卡、当前与对比周期选择、商品贡献和订单明细 |
| 分析助手 | 聊天记录、连续追问、工具参数及结构化结果、规则来源、失败重试 |
| 经营报告 | 无密钥生成基础周报，预览、固定图表、Markdown/CSV/ZIP 下载，可选 AI 解读 |

在侧栏折叠的“模型设置”中填写 API Key，或启动前设置 `DEEPSEEK_API_KEY`（其他服务使用各自环境变量）。会话中输入的密钥优先，页面不写入环境变量，不将密钥保存到仓库。

推荐对话：

1. “分析本期经营情况”——首次提问使用经营概览中的周期。
2. “继续按商品分析”——沿用周期，计算商品贡献；默认对比同等天数的相邻周期，也可在经营概览手动选择对比周期。
3. “改为 2026-09-02，查看该商品明细”——更新日期并沿用最近讨论的商品；贡献排名后的“该商品”默认是排名第一的商品，结果标明其精确标识。

完整日期支持 `YYYY-MM-DD`、`YYYY/MM/DD`、`YYYY年M月D日`。缺少日期的追问沿用上轮周期；修改经营概览的日期会更新助手默认周期。需要切换商品可明确指定 `id:SKU-001`，查看全部商品可说“查看全部商品”。同名多编号时使用精确商品标识。

页面展示回答、实际工具名称、填充默认条件后的有效输入参数、结构化结果及真实检索来源，不展示模型内部推理。调用失败时保留问题和已完成结果，可“重试上个问题”；“清空对话”不清空当前数据和页面日期。更换数据或应用映射会清理旧对话及条件。

主模型请求超时为 45 秒，最多重试 1 次；Agent 最多 6 轮工具调用，循环在轮次边界检查 120 秒运行限制。120 秒并非正在进行的网络请求的硬中断，单次响应可能包含多个工具调用。真实 API 的可用性、回答质量和服务端重试行为尚未验收。项目不会自动加载 `.env`；密钥通过侧栏当前会话或启动环境变量配置。

“高级工具”默认关闭，包含上游自然语言查询、自由绘图和数据处理。启用后会执行模型生成的 Python 代码，**不能视为安全沙箱**；仅用于可信的本地环境和可信数据。工具操作数据副本，处理结果下载后重新上传才能用于经营分析。

高级工具的需求输入和工具类型放在同一表单中，输入时不提交，点击“执行高级工具”后才执行；空输入直接提示补充。高级工具使用 Streamlit fragment，交互只更新该区域。其他页面发生完整重跑时，同一会话会复用未变化的数据校验、概览和明细预览；换文件、应用映射、切换币种或分析条件后重新计算。缓存不跨用户共享，每类视图只保留最近一组条件。

默认“自然语言查询”输出文字；其中明确的“画柱状图”“绘制折线图”等请求自动转到“自由绘图”，页面会注明实际使用的工具，也可直接选择自由绘图。绘图通过模型生成代码后执行并显示图片，不进入 Pandas Agent 的多轮循环；使用 Agg 后端在 Streamlit 工作线程生成 PNG。查询 Agent 使用 LangChain `tool-calling`，最多 4 轮；超限作为失败显示中文提示及实际工具输入／输出，问题保留供修改重试。生成代码、空图或执行失败会明确报错，不承诺所有自然语言绘图均成功。

侧栏与高级工具显示当前模型服务及名称，分析助手每条结果记录当时的模型配置。单独询问“你是什么模型”时，应用直接读取调用配置回答，无需调用 API；业务问题仍调用所选模型，并在提示词中提供当前配置。切换服务或模型名称后，旧的高级工具结果会清除。模型自称 Claude 不足以证明实际调用了 Claude，配置展示也不是对服务端内部实现的独立鉴定。性能复测与验证边界见 [交互修复记录](docs/interaction-fix-validation.md)。

## 经营诊断与周报

1. 在经营概览选择当前周期和对比周期，两个周期均包含结束日全天；修改当前周期后，对比周期重新默认到相邻同等天数。
2. 在经营报告点击“生成基础经营周报”，无需配置密钥。页面、固定图表和导出文件共用一个诊断结果。
3. 核对指标对比、前 10 名商品变化及排名之外的数量和金额。商品变化先计算全部商品再排名，完整商品变化之和必须等于总净销售额变化。
4. 重点商品证据选择变化绝对值最大的前 3 个商品，包含它们在两个周期的完整有效明细；页面预览前 200 条、Markdown 预览前 20 条，CSV 不按对话工具的 100 条限制截断。
5. 下载 Markdown、指标对比 CSV、全部商品贡献 CSV、完整订单证据 CSV，或包含所有内容及图表的 ZIP 包。CSV 为 UTF-8 BOM，金额列固定两位小数并保留整数分字段，订单／商品编号须按文本导入 Excel。
6. 如需额外文字解读，可单独点击“添加 AI 解读（可选）”。该部分标注为模型生成，不改变已计算的指标、表格和图表；调用失败不影响基础报告下载。

ZIP 目录：

```text
report.md
metrics_comparison.csv
product_contribution.csv
order_evidence.csv
daily_net_sales.csv
manifest.json
charts/net_sales_trend.png
charts/product_change.png
```

Manifest 记录周期、币种、质量计数、完整商品数、变化对账及规则元数据。报告说明空周期、零基期、缺少客户／商品字段和其他限制。日期、数据或映射变化后，旧报告不会继续作为当前结果提供下载。

公开模拟样例的 [报告核对示例](docs/report-example.md) 包含完整商品变化和对应订单，可用下列命令生成本地报告包；输出在被 Git 忽略的 `outputs/demo_report/`：

```powershell
.\.venv\Scripts\python.exe scripts/export_demo_report.py
```

## 版本化规则与检索

指标口径文件按 13 条独立规则拆分，每条包含规则编号、指标标识、标题和版本。检索返回实际命中的原文、来源行号及分数；未达到 TF-IDF 相关性阈值时明确返回“未找到规则”。报告按固定代码绑定规则解释，不通过文档运行或修改公式。

当前阈值为 0.13，依据固定查询样本校准：16 条校准样本、8 条独立验证样本均通过本次检查。该结果只代表这些样本，不是所有业务查询的准确率承诺。原始分数和语料摘要见 [校准记录](docs/rule-calibration.json)，增改规则后应重新校准：

```powershell
.\.venv\Scripts\python.exe scripts/calibrate_rules.py --output docs/rule-calibration.json
```

本地图表优先使用微软雅黑、黑体等中文字体；云服务器需安装可用 CJK 字体（如 Noto Sans CJK），当前阶段未验证 Linux 字体环境。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

包含 CSV/XLSX、映射与会话生命周期、金额和商品聚合、LangChain 工具调用链、连续对话和 Streamlit AppTest 页面交互。模型测试使用确定性模拟传输层，LangChain 编排、工具、指标和检索均实际执行；AppTest 不启动常驻服务、不调用真实模型 API。

真实 DeepSeek 验收脚本仅使用仓库公开模拟数据，可能产生 API 费用；未设置 `DEEPSEEK_API_KEY` 时打印 `status=skipped`，不能算验收成功：

```powershell
.\.venv\Scripts\python.exe scripts/verify_deepseek.py
```

阶段 D 验收时未配置密钥，真实 API 验收待完成；当时的临时服务健康检查和首页 HTTP 响应通过，验证后已停止。后续体验用本地服务不属于该临时验收服务。浏览器自动化工具初始化失败，实际浏览器渲染未验收。
