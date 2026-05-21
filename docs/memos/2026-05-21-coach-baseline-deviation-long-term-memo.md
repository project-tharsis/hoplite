# Hoplite 长期迭代 Memo：Coach Baseline + Match Deviation

日期：2026-05-21

## 1. 核心定位

Hoplite 不应该只是一个“基于 Arteta 哲学的赛后评分器”。

更长期的产品方向是：

```text
用结构化比赛数据建立主教练战术 baseline，
识别单场比赛相对历史模式的偏离，
再用 LLM 生成有证据、有边界的中文战术复盘。
```

系统重点回答的不是：

```text
这场比赛踢得好不好？
```

而是：

```text
这场比赛哪里不像这名教练平时的球队？
偏离发生在什么上下文？
这种偏离可能代表什么战术选择？
它对比赛结果有什么影响？
```

第一阶段仍然聚焦 Arteta / Arsenal。

但架构上应保持可扩展：未来可以支持 Guardiola、Klopp、Emery、Slot 等不同教练，也可以支持同一教练不同赛季的对比。

## 2. 产品原则

### 2.1 LLM 负责解释，不负责计算

LLM 不应该直接吃原始比赛数据，然后自由判断战术。

更稳妥的分工是：

```text
数据/规则/统计模型：发现事实
LLM：解释事实
```

也就是说，系统应先算出：

- 本场指标是多少；
- 历史 baseline 是多少；
- 相似上下文 baseline 是多少；
- 偏离幅度是多少；
- 置信度是多少；
- 有哪些替代解释。

然后再交给 LLM 写成中文复盘。

### 2.2 偏离比绝对描述更有价值

普通赛后报告会说：

```text
阿森纳本场更多从右路推进。
```

Hoplite 应该说：

```text
阿森纳本场右路推进占比显著高于 Arteta 近 30 场 baseline，
并且高于同类型对手/同比分状态下的 baseline。
```

产品差异化来自“相对这名教练历史模型的偏离”，不是泛泛描述比赛。

### 2.3 所有判断都必须有边界

每个战术判断都应区分：

- 事实；
- 推断；
- 可能原因；
- 替代解释；
- 置信度；
- 数据缺口。

尤其要避免把数据相关性直接写成教练意图。

## 3. 数据分层

### 3.1 基础比赛数据

包括：

- 比分；
- xG；
- 控球率；
- 射门；
- 射正；
- 传球数和成功率；
- 角球；
- 犯规；
- 黄牌/红牌；
- 进球时间；
- 换人时间；
- 阵容和首发。

这层数据可以支持基础赛后评价，但不足以支撑真正的战术 baseline。

如果只有这层数据，Hoplite 最多能做：

```text
表现评估 + 弱标签 + 简单历史校准
```

不能可靠判断：

- 推进方向；
- build-up 结构；
- rest-defence；
- 压迫触发；
- 球员站位；
- 空间占据。

### 3.2 Event data

这是战术 baseline 的最低可用数据层。

至少需要：

- event type；
- timestamp；
- team；
- player；
- x/y location；
- pass end location；
- carry end location；
- shot location；
- shot xG；
- possession id；
- pressure / duel / recovery；
- lineup / substitution；
- card context；
- match metadata。

可支持的指标包括：

- progressive pass；
- progressive carry；
- final third entry；
- box entry；
- left/center/right progression share；
- shot quality；
- open-play chance quality；
- counterpress regain；
- possession duration；
- tempo；
- set-piece share；
- turnover location；
- substitution game-state impact。

这是 MVP 应优先验证的数据层。

### 3.3 360 / tracking data

高阶空间战术需要 freeze-frame 或 tracking。

可支持：

- 3-2-5 / 2-3-5 结构识别；
- 左后卫是否内收；
- defensive line height；
- team width；
- team depth；
- player spacing；
- rest-defence 人数和站位；
- pressing shape；
- pressing trap；
- opponent block shape；
- overload-to-isolate。

没有这层数据时，不应强行输出精确空间结构判断。

如果只有 event data，报告应该明确说：

```text
该判断基于事件位置和传球方向推断，缺少 tracking data，因此置信度中等。
```

## 4. Competition Context Layer

比赛性质和重要程度必须作为一级上下文。

同一个战术行为，在不同比赛背景下含义可能完全相反。

例如：

```text
欧冠次回合，总比分领先两球后降速
```

可能是成熟的风险管理。

但：

```text
联赛争冠冲刺期，必须赢的比赛中提前降速
```

可能是调整不足或进攻持续性问题。

### 4.1 必须建模的比赛上下文

需要显式记录：

- 比赛类型：联赛 / 国内杯赛 / 欧战 / 友谊赛；
- 比赛阶段：赛季早期 / 中期 / 冲刺期 / 淘汰赛 / 决赛；
- 回合制状态：首回合 / 次回合 / 总比分领先 / 总比分落后；
- 联赛积分位置：争冠 / 欧冠资格 / 欧战资格 / 中游 / 保级；
- 对手积分位置：争冠对手 / 直接竞争对手 / 中游 / 保级队；
- 赛程压力：欧战前后 / 强敌前后 / 连续客场 / 短休；
- 轮换动机：主力全开 / 部分轮换 / 大幅轮换；
- 结果需求：必须赢 / 平局可接受 / 保持不败即可 / 保护总比分；
- 风险偏好预期：需要冒险 / 控制风险 / 保存体能。

### 4.2 Context-aware baseline

baseline 不应只有一个全局均值。

至少要分成：

```text
overall coach baseline
same opponent_quality baseline
same venue baseline
same competition_type baseline
same competition_pressure baseline
same game_state baseline
same time_window baseline
```

最终判断应尽量回答：

```text
这场是否偏离 Arteta 总体习惯？
是否偏离 Arteta 在同类比赛中的习惯？
是否偏离 Arteta 在同比分/同时间状态下的习惯？
```

## 5. Coach Baseline

Coach baseline 是 Hoplite 的核心资产。

它不是一句“Arteta 喜欢控球”，而是一组按上下文切分的行为分布。

### 5.1 Baseline 应包含的维度

Build-up:

- 门将参与出球；
- 中卫拉开；
- 6号位接球；
- 后场短传比例；
- 长传绕压比例；
- under pressure 出球选择。

Progression:

- 左/中/右推进占比；
- progressive pass；
- progressive carry；
- half-space receive；
- final third entry；
- box entry。

Final third:

- open-play chance creation；
- cutback；
- crossing；
- through ball；
- set-piece share；
- shot quality。

Pressing / transition:

- counterpress regain；
- turnover location；
- high regain；
- transition shot；
- defensive transition exposure。

Game management:

- 领先后节奏变化；
- 落后后纵向推进变化；
- 70分钟后风险偏好；
- 控球保护 vs 继续进攻；
- 换人时机；
- 换人类型；
- 换人后比赛状态变化。

### 5.2 Baseline 的输出形式

baseline 应输出机器可读结构，而不是自然语言总结。

例如：

```json
{
  "coach": "Arteta",
  "team": "Arsenal",
  "window": "last_30_matches",
  "context": {
    "competition_type": "league",
    "venue": "away",
    "opponent_quality": "mid_table",
    "game_state": "leading_after_70"
  },
  "metrics": {
    "right_side_progression_share": {
      "mean": 0.31,
      "std": 0.07,
      "p80": 0.39
    }
  }
}
```

## 6. Match Deviation

Match Deviation 是单场分析的核心入口。

它比较：

```text
本场比赛
vs
coach baseline
vs
相似上下文 baseline
```

### 6.1 Deviation 输出内容

每个 deviation 至少包含：

- metric；
- match value；
- baseline value；
- context baseline value；
- delta；
- percentile / z-score；
- confidence；
- time window；
- evidence events；
- possible interpretation；
- alternative explanation；
- data limitation。

### 6.2 Deviation 示例

```json
{
  "title": "右路推进显著增加",
  "metric": "right_side_progression_share",
  "match_value": 0.48,
  "baseline_mean": 0.31,
  "context_baseline_mean": 0.34,
  "delta_vs_context": 0.14,
  "confidence": "high",
  "time_window": "0-60",
  "possible_interpretation": "可能针对对手左侧压迫进行规避",
  "alternative_explanation": "也可能来自右路球员个人状态或左路人员轮换"
}
```

## 7. LLM Report Layer

LLM 的输入应是结构化发现，而不是原始事件流。

推荐输入：

```text
match summary
competition context
coach baseline
top deviations
weak labels
historical calibration
known blind spots
data limitations
```

报告输出必须包含：

- 总体判断；
- top deviations；
- 关键战术解释；
- evidence；
- confidence；
- alternative explanation；
- 改进方向；
- 一句话结论。

LLM 不应自由补充没有数据支持的战术细节。

## 8. 自迭代产物分层

自迭代不应直接修改核心 framework。

产物应分层沉淀：

```text
single-match evaluation
→ adjudication report
→ blind spots registry
→ experiment decision
→ accepted baseline
→ framework proposal
→ framework update
```

### 8.1 短周期产物

短周期可以更新：

- blind spots；
- prompt guardrails；
- calibration hints；
- experiment decisions；
- baseline registry。

### 8.2 中周期产物

中周期可以产出：

- WK rule candidates；
- deviation detector candidates；
- feature gap report；
- context weighting proposal。

### 8.3 长周期产物

长期稳定后才考虑更新：

- Arteta framework；
- model definitions；
- rubric wording；
- coach-specific tactical ontology。

也就是说：

```text
arteta_framework.md 不是一线自迭代对象。
它只接收多轮 promoted evidence 证明过的稳定结论。
```

## 9. 数据源策略

### 9.1 原型阶段

优先使用：

- StatsBomb Open Data；
- Public Wyscout dataset；
- 少量手工标注样本。

目标不是覆盖当前 Arsenal，而是验证：

- 指标体系；
- baseline 计算；
- deviation detector；
- LLM report 约束。

### 9.2 产品阶段

正式产品需要 StatsBomb / Wyscout / Opta 级别 event data。

最低要求是能获得：

- pass/carry/shot location；
- xG；
- possession sequence；
- pressure/recovery；
- lineup/substitution；
- match metadata。

### 9.3 高阶阶段

空间战术需要：

- StatsBomb 360；
- SkillCorner；
- tracking / freeze-frame 数据。

这部分不应成为 MVP 阻塞项。

## 10. 阶段路线

### Phase 1：当前系统收口

目标：

- 明确当前生产 prompt 使用哪些自迭代产物；
- 不让 rollback 实验污染生产 prompt；
- 固化 accepted baseline；
- 明确 blind spots、rubric、features、prompt 的版本关系。

成功标准：

- 新比赛复盘使用的配置可追踪；
- prompt 不混入失败实验内容；
- 实验产物和生产配置分离。

### Phase 2：Event Data MVP

目标：

- 引入 event-level 数据；
- 建立 20-30 个核心战术指标；
- 生成 Arteta baseline；
- 输出 top deviations。

成功标准：

- 能回答“这场哪里偏离 Arteta baseline”；
- 每个 deviation 有数据证据；
- LLM 不再从 box score 猜战术。

### Phase 3：Context-aware Deviation

目标：

- 引入 competition context；
- 按比赛性质、积分压力、比分状态分层 baseline；
- 避免把主动风险管理误判成保守。

成功标准：

- 同一战术行为在不同比赛性质下能给出不同解释；
- 报告明确引用比赛重要程度和结果需求。

### Phase 4：Self-Iteration Loop

目标：

- 新比赛持续入库；
- 定期生成 WK / B / human 分歧；
- promote 有统计改善的 blind spots 或 prompt guardrails；
- reject 质量污染或回退实验。

成功标准：

- 每次 baseline 更新都有 artifact；
- 可解释为什么 promote 或 rollback；
- 不发生静默漂移。

### Phase 5：Spatial Tactical Model

目标：

- 接入 360 / tracking；
- 分析阵型、宽度、纵深、rest-defence、压迫结构。

成功标准：

- 从事件偏离升级到空间结构偏离；
- 能解释 Arteta 的 build-up shape、pressing shape 和 defensive rest structure。

## 11. MVP 成功标准

MVP 不要求“完全理解足球”。

MVP 只要求稳定完成：

```text
Arteta historical baseline
+ single-match deviation detection
+ evidence-based Chinese tactical report
```

具体标准：

- 能稳定建立 Arteta baseline；
- 能识别单场 top 5-10 个关键偏离；
- 每个判断都有 evidence；
- 输出 confidence；
- 输出 alternative explanation；
- 缺少数据时明确降置信度；
- 同一场比赛重复生成结果基本一致；
- 人工战术读者认为主要结论成立。

## 12. 长期判断

这条路线的关键不在 prompt。

关键在：

```text
数据粒度
baseline 建模
context 分层
deviation detection
实验治理
```

LLM 是表达层。

Hoplite 的长期资产应该是：

- coach baseline；
- tactical metric library；
- context-aware deviation detector；
- validated blind spots；
- evaluation history；
- framework proposals。

一句话：

```text
Hoplite 应该从“赛后评分器”升级为
Coach Baseline + Match Deviation + Evidence-based LLM Report。
```
