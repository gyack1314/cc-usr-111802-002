# 城市街区指标分析

项目保存城市街区的来源版次，按资料取得时间比较指标并给出区域规则判断。evidence 保存来源与有效时间，metrics 计算同口径偏离，context 解释当前区域规则，analysis 按各自适用时间配对潮位、雨量、排水工况与街区阈值并形成积水与避险窗口，report 保存每个已知时间的报告快照并给出需要复议的街区及触发变化。

分析不会把两份预报的峰值直接相加：只有同一天都有适用资料的街区才会计算，缺资料或时间窗不重合的日期会写明原因，相关街区判为“无法判断”，不会当作安全。新报告不会覆盖旧结论，`difference` 会同时给出变化前后的依据。

样本是合成数据。Python 3.11 以上，在项目根目录执行：

    python -m unittest discover -s tests -v
    python -m compileall -q climate_analysis tests
    python -m climate_analysis.cli inspect data/drainage-scenario.json
    python -m climate_analysis.cli inspect data/example.json

`data/drainage-scenario.json` 是含潮位、雨量、排水调整与街区阈值的三期样本，展示避险窗口、无法判断街区以及排水能力更新后需要复议的街区。`data/example.json` 是早期的观测/参照样本，只用于偏离与规则解释。

Dockerfile 可在 Linux 容器运行：docker build -t climate-analysis-002 .；docker run --rm climate-analysis-002。
