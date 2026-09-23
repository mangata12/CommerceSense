# Upstream notes

- Upstream repository: https://github.com/Saishhhhhh/DataSense.git
- Origin repository: https://github.com/mangata12/CommerceSense.git
- Local remotes are configured as `upstream` and `origin`.

上游源码已通过 `git fetch upstream` 获取，并以 `upstream/main` 为来源导入本仓库。上游原始说明保存在 `UPSTREAM_README.md`，许可证保存在 `LICENSE`。

CommerceSense 在上游 LangChain DataFrame Agent 之外增加了 `commerce_data.py`、`commerce_metrics.py` 和 `commerce_agent.py`，用于电商字段标准化、确定性经营计算和业务工具调用。
