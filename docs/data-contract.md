# 城市街区数据约定

observation、reference、rule 三种记录分别表示观测、参照和区域规则，供单期偏离与规则解释使用。tide、rainfall、drainage、threshold 四种记录用于积水和避险窗口分析。metric、region、unit 共同表示可比口径，来源版次与取得时间独立保留。

## 时间

- 每条记录带 `valid_from`，可选 `valid_to`，均为闭区间。只写日期时表示自然日；带时刻时按所覆盖的日期参与配对。
- 积水与避险窗口一律按自然日配对。潮位、雨量、排水工况、街区阈值必须在同一天都有适用记录，否则该日不进入计算，并写入该街区的 `unable` 原因。
- 潮位与雨量时间窗不重合的日期不会被相加或补齐；整个时间窗都不重合时，街区直接判为“无法判断”。
- 窗口终点只取资料真正覆盖到的最后一天；次日资料缺失时窗口标记为终点未定，不外推。

## 正文

| kind | 必需字段 |
| --- | --- |
| tide | height_m（米） |
| rainfall | depth_mm（累计毫米，需有 valid_to，按日折算）或 amount_mm（日毫米） |
| drainage | capacity_mm_per_day |
| threshold | threshold_mm，以及 tide_base_m + tide_block_m（潮位顶托衰减）或 tide_threshold_m（潮位独立触发）；可选 action |

- 同一街区同一指标的所有记录必须使用同一个 unit，否则判为“无法判断”。
- 同一街区同一资料在同一天有多份适用记录时，取对避险最不利的一份（雨量、潮位取最大，排水能力取最小，阈值取最小），并在该日 `note` 中留痕。
- 不做跨 metric 的换算或外推；无法配对时只说明原因。

## 判定

日积水量 = 日雨量 − 潮位顶托后的有效排水能力，排水能力按潮位在 `tide_base_m` 到 `tide_block_m` 之间线性衰减。积水量达到 `threshold_mm`，或潮位达到 `tide_threshold_m`，即触发该街区的 `action`。连续触发日合并为一个避险窗口。

## 报告与复议

每个 known_at 的报告是一个不可变的快照，含 `fingerprint` 与各街区判断。`difference` 逐街区列出 `review`：状态、避险窗口、无法判断原因、依据来源或资料覆盖发生变化时都需要复议，并同时给出变化前后两次报告的依据（窗口、缺口、来源哈希、fingerprint）。旧结论不会被覆盖；`previously_unable` 保留上一次无法判断的街区和原因。
