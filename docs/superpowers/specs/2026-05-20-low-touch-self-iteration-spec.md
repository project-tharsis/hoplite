# 低人工依赖 Arteta 自迭代规格

日期：2026-05-20
状态：可执行
受众：实现代理

## 1. 背景

历史 JSON 回填已经足够支撑第一轮自迭代。

当前已知状态：

- `data/knowledge.json` 共 111 条。
- 102 条已经有 `features`，且 `weak_label_version=v1.1`。
- 9 条仍是 legacy-only 重复条目，本轮自迭代忽略。
- 72 条 feature-backed 条目已有 strict v2 LLM evaluation。
- 30 条 feature-backed seed 条目还没有存储的 LLM evaluation source。
- 3 条有 `human_override`。
- feature-backed 条目的顶层 `opponent`、`result`、`score`、`competition`、`pre_match_context` 已补齐。
- `PatternComputer` 和 `CalibrationComputer` 已能读取 KB，不再有隐式 context 断点。

产品决策：

> 真值主要来自评估器B。人工 review 只作为小样本审计层，不再作为主要校准引擎。

本规格定义下一阶段低人工依赖的自迭代闭环。

## 2. 产品目标

构建一个可重复运行的闭环，使系统能够：

1. 为缺少评估器B结果的 feature-backed 比赛生成评估任务。
2. 将评估器B的 strict v2 输出写入 KB，并保留模型与运行元数据。
3. 在 feature-backed 语料上比较 deterministic WK v1.1 与评估器B。
4. 自动接受高置信一致样本。
5. 从重复的 WK-vs-B 分歧中挖掘候选校准规则。
6. 自动升级低风险 prompt-level blind spot。
7. 对会改变 deterministic weak label 的规则，只生成明确的 WK patch proposal。

目标不是让人逐场标注，而是让后续每一场比赛都能推动 Arteta skill 的校准。

## 3. 非目标

- 不迁移 JSON 到数据库。
- 不增加前端。
- 不 fine-tune 模型。
- 不在仓库内直接调用 LLM provider。
- 不把评估器B输出写成 `human_override`。
- 不允许评估器B静默改写 `weak_labels`。
- 不从挖掘规则自动编辑 `src/labels/weak_labeler.py`。
- 不把单个分歧当成新的 Arteta 原则。

## 4. 核心决策

使用三层标签：

```text
weak_labels      = deterministic WK 输出
evaluation       = 评估器B strict v2 pseudo-gold
human_override   = 明确人工修正
```

评估器B是自动化流程里的 operational truth source，但仍然存为 `evaluation`，不能伪装成 `human_override`。

原因：

- `human_override` 表示有人对这个标签负责。
- 评估器B提供可规模化的 pseudo-gold。
- WK 可以从重复的 B 模式中学习，但不能假装这些标签经过人工确认。

## 5. 实现顺序

按以下顺序实现：

1. 增加 evaluation metadata 支持。
2. 增加 `self_iterate.py make-jobs`，为缺失或过期的评估器B结果生成任务。
3. 增加 `self_iterate.py ingest-results`，写入 strict B 结果。
4. 增加 `self_iterate.py adjudicate`，比较 WK 与评估器B。
5. 增加 `self_iterate.py mine-rules`，挖掘重复分歧候选规则。
6. 将 known blind spots 从 Python 常量迁移到版本化 rubric JSON。
7. 增加 `self_iterate.py promote-blind-spots`，安全升级 prompt-level blind spot。
8. 在 102 条 feature-backed 条目上跑完整闭环并提交 artifact。

在 102 条 feature-backed 条目都拥有评估器B标签前，不要开始规则挖掘。

## 6. 目标流程

### 6.1 一次性补齐语料评估

```bash
python scripts/self_iterate.py make-jobs \
  --kb data/knowledge.json \
  --reports-root data/backfill/runs \
  --only missing-evaluation \
  --evaluator-id B \
  --run-id b-001 \
  --output data/self_iteration/runs/b-001
```

预期行为：

- 写出 `data/self_iteration/runs/b-001/llm_jobs.jsonl`。
- 只包含 feature-backed 且缺少评估器B evaluation 的条目。
- 以当前语料计算，应产生 30 个 job。
- 不修改 KB。

评估器B的实际执行发生在仓库外部。

#### 6.1.1 Report 查找策略

`make-jobs` 必须用确定性策略查找 report，不能任意选择一个同名文件。

对每条 feature-backed entry，按以下优先级查找：

1. `entry["backfill"]["report_path"]` 指向的文件存在时，直接使用。
2. 如果有 `entry["backfill"]["run_id"]`，查找 `reports-root/<run_id>/reports/<fixture_id>.json`，再查找 `reports-root/<run_id>/reports/<match_id>.json`。
3. fallback 广度搜索：
   - `reports-root/*/reports/<fixture_id>.json`
   - `reports-root/*/reports/<match_id>.json`
4. fallback 搜索命中多个候选时，按完整路径字符串排序后取最后一个，并在 job row 的 `report_candidates` 中记录全部候选。

找不到 report 时：

- 不生成该 match 的 job。
- 在 `make_jobs_report.json` 中记录：

```json
{
  "match_id": "1208154",
  "ok": false,
  "error": {
    "code": "REPORT_NOT_FOUND",
    "message": "No report found via backfill.report_path, backfill.run_id, or reports-root search."
  }
}
```

#### 6.1.2 Prompt 来源优先级

`make-jobs` 必须明确 prompt 从哪里来，避免 WK/version drift。

对每条 job，按以下优先级取 prompt：

1. 如果当前 output 目录已存在同 `match_id` 的 self-iteration job，复用该 job 的 `prompt`、`prompt_hash` 和 `prompt_source`，保证幂等。
2. 如果 `entry["backfill"]["run_id"]` 对应 run 目录中存在 `llm_jobs.jsonl`，且能按 `match_id` 或 `fixture_id` 找到同一场比赛，复用该历史 prompt。
3. 如果 report 所在 run 目录中存在 `llm_jobs.jsonl`，同样按 `match_id` 或 `fixture_id` 查找并复用历史 prompt。
4. 最后才用 `prepare_evaluation(report, output_format="json")` 重新生成 prompt。

每条 job 必须写 `prompt_source`：

```text
self_iteration_existing
backfill_llm_job
prepare_evaluation_regenerated
```

如果使用 `prepare_evaluation_regenerated`，但重新生成的 `weak_labels` 与 KB 中已存 `entry["weak_labels"]` 不一致：

- 不覆盖 KB。
- 仍可生成 job。
- 在 job row 写 `wk_drift_detected=true`。
- 在 `make_jobs_report.json` 中记录 drift details。

`prompt_hash` 必须对最终写入 job 的完整 prompt 字符串计算。

### 6.2 写入评估器B结果

```bash
python scripts/self_iterate.py ingest-results \
  --kb data/knowledge.json \
  --run data/self_iteration/runs/b-001 \
  --input data/self_iteration/runs/b-001/llm_results.jsonl \
  --write
```

预期行为：

- 使用 strict v2 schema 校验每条结果。
- 通过现有保存路径写入有效结果。
- 保留已有 `features`、`weak_labels` 和版本字段。
- 写出 `ingest_report.json`。
- 写出 `knowledge.before.json` 与 `knowledge.after.json` 快照。
- 对格式错误的 row 拒绝写入，不能出现半条数据 mutation。

### 6.3 裁判 WK 与评估器B

```bash
python scripts/self_iterate.py adjudicate \
  --kb data/knowledge.json \
  --run-id b-001 \
  --output data/self_iteration/runs/b-001/adjudication_report.json
```

预期行为：

- 对全部 102 条 feature-backed 条目比较 WK v1.1 与评估器B。
- 在以下层级报告一致与分歧：
  - overall signal
  - 3 个 dimension signal
  - 6 个 model signal
- 按 context 分桶：
  - `opponent_quality`
  - `venue`
  - `competition_stage`
  - `result`
  - xG present/missing
- 不修改 KB。

### 6.4 挖掘候选规则

```bash
python scripts/self_iterate.py mine-rules \
  --adjudication data/self_iteration/runs/b-001/adjudication_report.json \
  --output data/self_iteration/runs/b-001/rule_candidates.json
```

预期行为：

- 只使用重复出现的 WK-vs-B 分歧。
- 输出候选规则，包含 support、precision、false-positive risk、examples、proposed action。
- 不修改代码或 KB。

### 6.5 升级 prompt-level blind spot

```bash
python scripts/self_iterate.py promote-blind-spots \
  --candidates data/self_iteration/runs/b-001/rule_candidates.json \
  --output rubrics/arteta_blind_spots.json \
  --write
```

预期行为：

- 只升级 `proposed_action="prompt_blind_spot"` 的候选。
- 不升级需要改变 WK 输出的候选。
- 更新版本化 JSON rubric 文件，不再改 Python 常量。
- `CalibrationComputer` 后续 prompt 会渲染已升级的 blind spot。

## 7. 必需数据结构

### 7.1 LLM Job Row

`llm_jobs.jsonl` 每行必须使用以下结构：

```json
{
  "job_schema_version": "self_iteration_job_v1",
  "match_id": "1208154",
  "fixture_id": "1208154",
  "evaluator_id": "B",
  "run_id": "b-001",
  "prompt_source": "backfill_llm_job",
  "prompt_hash": "sha256:...",
  "prompt": "...",
  "features": {},
  "weak_labels": {},
  "report_path": "data/backfill/runs/seed-002/reports/1208154.json",
  "report_candidates": [],
  "versions": {
    "features_version": "v1",
    "weak_label_version": "v1.1",
    "rubric_version": "arteta_v1",
    "prompt_builder_version": "v1"
  },
  "expected_output_schema": "strict_v2_evaluation"
}
```

`prompt_hash` 必须由完整 prompt 字符串计算得到。

说明：

- 这是 self-iteration job schema，不是 historical backfill 的 `llm_jobs.jsonl` schema。
- 两者文件名相同，但目录不同：self-iteration 只写入 `data/self_iteration/runs/...`。
- `job_schema_version` 用于避免未来维护者把 backfill job 和 self-iteration job 混用。

### 7.2 LLM Result Row

`llm_results.jsonl` 每行必须使用以下结构：

```json
{
  "job_schema_version": "self_iteration_job_v1",
  "match_id": "1208154",
  "evaluator_id": "B",
  "run_id": "b-001",
  "prompt_hash": "sha256:...",
  "model": "evaluator-b-model",
  "created_at": "2026-05-20T00:00:00Z",
  "evaluation": {
    "overall_signal": "🟢",
    "model_signals": {
      "1": "🟢",
      "2": "🟢",
      "3": "🟢",
      "4": "🟢",
      "5": "🟡",
      "6": "🟡"
    },
    "dimension_signals": {
      "execution": "🟢",
      "adjustment": "🟡",
      "satisfaction": "🟢"
    },
    "evidence": {
      "1": ["..."],
      "2": ["..."],
      "3": ["..."],
      "4": ["..."],
      "5": ["..."],
      "6": ["..."]
    },
    "confidence": {
      "1": "high",
      "2": "high",
      "3": "high",
      "4": "medium",
      "5": "medium",
      "6": "medium"
    },
    "missing_or_weak_evidence": [],
    "weak_label_disagreements": [],
    "narrative": "中文复盘正文..."
  }
}
```

缺少 strict v2 字段的 row 必须拒绝。

### 7.3 Evaluation Metadata 持久化

修改 `src/tools/save_evaluation.py`，允许调用方传入 `evaluation_metadata`。

metadata 写入 `entry["evaluation"]["metadata"]`：

```json
{
  "source": "llm",
  "metadata": {
    "evaluator_id": "B",
    "run_id": "b-001",
    "model": "evaluator-b-model",
    "prompt_hash": "sha256:...",
    "created_at": "2026-05-20T00:00:00Z",
    "features_version": "v1",
    "weak_label_version": "v1.1",
    "rubric_version": "arteta_v1",
    "prompt_builder_version": "v1",
    "job_schema_version": "self_iteration_job_v1"
  }
}
```

兼容规则：

- 不传 `evaluation_metadata` 的旧调用必须继续可用。
- 既有 `evaluation.source == "llm"` 保持不变。
- metadata 不能传入 `validate_llm_result()`。
- metadata 不能降低 strict validation。
- metadata 中的版本字段用于 stale evaluation 判断；如果未来 `features_version`、`weak_label_version`、`rubric_version` 或 `prompt_builder_version` 变化，`make-jobs --only stale-evaluation` 可以重新生成评估任务。

## 8. 裁判语义

创建：

```text
src/evaluation/adjudication.py
```

### 8.1 Signal 标准化

比较前必须统一 model key：

```text
culture_as_os                  -> "1"
where_game_is_played           -> "2"
defence_as_attacking_identity  -> "3"
marginal_gains                 -> "4"
add_capability_keep_identity   -> "5"
role_clarity                   -> "6"
```

adjudication 输出必须始终使用数字 model key。

### 8.2 Row 分类

每条 feature-backed row 必须得到以下状态之一：

```text
agreement_high_confidence
agreement_low_confidence
wk_too_harsh
wk_too_generous
model_level_disagreement
dimension_level_disagreement
missing_evaluator_b
invalid_evaluator_b
needs_second_pass
```

分类规则：

- `agreement_high_confidence`：overall、dimensions、models 全部一致，且评估器B所有 confidence 都是 high 或 medium。
- `agreement_low_confidence`：signals 一致，但评估器B至少一个 confidence 是 low。
- `wk_too_harsh`：WK overall 低于评估器B overall。
- `wk_too_generous`：WK overall 高于评估器B overall。
- `model_level_disagreement`：overall 与 dimensions 一致，但至少一个 model signal 不同。
- `dimension_level_disagreement`：overall 一致，但至少一个 dimension signal 不同。
- `missing_evaluator_b`：feature-backed 条目没有评估器B evaluation。
- `invalid_evaluator_b`：evaluation 存在，但 strict v2 校验失败。
- `needs_second_pass`：评估器B证据弱、confidence low，或没有解释 weak-label disagreement。

信号排序：

```text
🔴 < 🟡 < 🟢
```

### 8.3 xG 判定

`xg_present` 必须按 feature 字段定义：

```text
xg_present := features["xg_for"] is not None AND features["xg_against"] is not None
```

原因：`xg_delta` 需要双方 xG 都存在才可靠。

### 8.4 Adjudication Report 结构

```json
{
  "run_id": "b-001",
  "summary": {
    "total_entries": 111,
    "feature_backed": 102,
    "compared": 102,
    "missing_evaluator_b": 0,
    "overall_agreement_rate": 0.0,
    "dimension_agreement_rate": 0.0,
    "model_agreement_rate": 0.0
  },
  "status_counts": {
    "agreement_high_confidence": 0,
    "wk_too_harsh": 0,
    "wk_too_generous": 0
  },
  "context_breakdowns": [],
  "rows": [
    {
      "match_id": "1208154",
      "context": {
        "opponent_quality": "top6",
        "venue": "home",
        "competition_stage": "league_early",
        "result": "W",
        "xg_present": true
      },
      "status": "wk_too_harsh",
      "wk": {},
      "b": {},
      "differences": [],
      "features": {}
    }
  ]
}
```

## 9. 规则挖掘语义

创建：

```text
src/evaluation/rule_mining.py
```

这不是学习模型。它只是从重复分歧中确定性抽取候选规则。

### 9.1 Candidate Feature View

对每条 adjudicated row，派生以下 boolean/numeric 字段：

```json
{
  "result": "W|D|L",
  "opponent_quality": "lower|mid_table|top6|european_elite",
  "venue": "home|away",
  "competition_stage": "league_early|league_late|cup|knockout",
  "xg_present": true,
  "dominant_xg": true,
  "dominant_shots": true,
  "dominant_control": true,
  "poor_control": false,
  "clean_sheet": true,
  "goals_conceded": 0,
  "cards_pressure": false,
  "late_subs": false,
  "sub_impact": true,
  "set_piece_edge": true,
  "missing_features": ["pressing", "pressing_recoveries", "transition"]
}
```

建议派生规则：

- `dominant_xg`：`xg_delta >= 0.75`
- `dominant_shots`：`shot_delta >= 5`
- `dominant_control`：以下至少两个成立：`xg_delta >= 0.75`、`shot_delta >= 5`、`possession_delta >= 8`、`corner_delta >= 4`
- `poor_control`：以下至少两个成立：`xg_delta <= -0.5`、`shot_delta <= -4`、`possession_delta <= -8`、`corner_delta <= -3`
- `clean_sheet`：`goals_conceded == 0`
- `cards_pressure`：`yellow_cards_for >= 2` 或 `red_cards_for > 0`
- `late_subs`：最早换人在 75 分钟后，或未领先状态下最晚换人在 85 分钟后
- `sub_impact`：`goals_after_arsenal_subs > 0` 或 `goals_by_substitutes > 0`
- `set_piece_edge`：`set_piece_goals_for > set_piece_goals_against` 或 `corner_delta >= 4`

缺失数据处理：

- 派生规则所需字段缺失或为 `null` 时，该单项条件视为 false。
- 缺失字段不能被当作满足条件。
- `dominant_control` 和 `poor_control` 只统计实际可计算且满足阈值的条件。
- 每条 candidate feature view 必须包含 `missing_features`，列出派生时缺失的字段。
- 规则挖掘不能把“字段缺失”本身当成战术规律，除非 candidate target 明确是 `missing_data_behavior`。

### 9.2 Candidate Rule 结构

```json
{
  "id": "wk_too_harsh_top6_home_win_low_possession",
  "target": "overall_signal",
  "predicate": {
    "result": "W",
    "opponent_quality": ["top6", "european_elite"],
    "dominant_control": true
  },
  "wk_pattern": "🟡",
  "b_pattern": "🟢",
  "direction": "upgrade",
  "support": 4,
  "precision_vs_b": 0.8,
  "false_positive_count": 1,
  "examples": ["1208154"],
  "counterexamples": [],
  "proposed_action": "prompt_blind_spot",
  "risk": "medium",
  "rationale": "评估器B多次把强队胜利中的强控制表现升级为绿色，而WK因为控球率持平仍给黄色。"
}
```

### 9.3 晋级门槛

候选规则必须保守生成。

`proposed_action="prompt_blind_spot"` 的最低门槛：

- `support >= 3`
- `precision_vs_b >= 0.70`
- `false_positive_count <= 2`
- examples 至少覆盖 2 个不同对手或 2 项不同赛事
- 不与已有 known blind spot 冲突

`proposed_action="wk_patch_proposal"` 的最低门槛：

- `support >= 5`
- `precision_vs_b >= 0.80`
- `false_positive_count <= 1`
- 至少一个匹配 row 有 `human_override`，或存在 second-pass evaluator agreement
- candidate 有 deterministic feature predicate
- candidate 包含一组不能变化的 regression match list

未过门槛的 candidate 必须保留在 `rejected_candidates`，并写明原因。

## 10. Known Blind Spots Registry

将 blind spots 从 Python 常量迁移到：

```text
rubrics/arteta_blind_spots.json
```

初始内容：

```json
{
  "version": "v1",
  "blind_spots": [
    {
      "id": "dominant_stats_loss",
      "description": "WK can overrate matches where Arsenal dominates shots/xG/possession but loses.",
      "guardrail": "Do not let shot/xG/possession dominance override result satisfaction. A loss to lower/mid_table opposition cannot be overall green.",
      "source": "human_review",
      "weak_label_version": "v1.1",
      "status": "active"
    }
  ]
}
```

修改 `src/evaluation/calibration.py`：

- 加载 `rubrics/arteta_blind_spots.json`。
- `build_hints()` 只包含 `status == "active"` 的 blind spot。
- 如果文件缺失或非法，回退到当前内置的 `dominant_stats_loss`。
- `KNOWN_BLIND_SPOTS` 只保留为 fallback。

## 11. Script Contract

创建：

```text
scripts/self_iterate.py
```

支持模式：

```text
make-jobs
ingest-results
adjudicate
mine-rules
promote-blind-spots
```

`make-jobs --only` 支持：

```text
missing-evaluation
stale-evaluation
missing-or-stale-evaluation
```

`stale-evaluation` 的判断依据是 `evaluation.metadata` 中的 version 字段与当前 job 生成版本不一致。

全局规则：

- 每个模式都必须写审计 JSON report。
- mutation 模式必须要求 `--write`。
- mutation 模式必须写 before/after snapshot。
- 非 mutation 模式绝不能修改 KB 或 rubric 文件。
- 同输入重复运行必须幂等。
- 必须保留 KB entry 中未知字段。

## 12. Artifact 可见性

当前 `.gitignore` 忽略 `data/*`，但允许 `data/backfill`。自迭代 artifact 也需要能提交到远程供 review。

修改 `.gitignore`，允许：

```text
!data/self_iteration
!data/self_iteration/**
```

继续排除完整 KB 快照：

```text
data/self_iteration/**/knowledge.before.json
data/self_iteration/**/knowledge.after.json
```

需要提交的 artifact：

- `llm_jobs.jsonl`
- `ingest_report.json`
- `adjudication_report.json`
- `rule_candidates.json`

不要提交：

- `knowledge.before.json`
- `knowledge.after.json`
- provider secrets
- 包含非项目元数据的 LLM provider raw response

如果 `llm_results.jsonl` 只包含 strict v2 evaluation JSON 且没有 secrets，可以提交用于复现。

## 13. 测试要求

增加聚焦测试，不要只依赖 E2E。

### 13.1 Save Evaluation Metadata

文件：

```text
tests/tools/test_save_evaluation_metadata.py
```

必测：

- `save_evaluation` 接受 `evaluation_metadata`。
- metadata 持久化到 `evaluation.metadata`。
- metadata 包含 `features_version`、`weak_label_version`、`rubric_version`、`prompt_builder_version`、`job_schema_version`。
- strict validation 仍然拒绝缺少 `evidence`、`confidence`、`missing_or_weak_evidence`、`weak_label_disagreements` 的结果。
- 不传 metadata 的旧调用仍然通过。

### 13.2 Adjudication

文件：

```text
tests/evaluation/test_adjudication.py
```

必测：

- WK semantic model keys 标准化为数字 key。
- WK 为 🟡、评估器B为 🟢 时识别为 `wk_too_harsh`。
- WK 为 🟢、评估器B为 🔴 时识别为 `wk_too_generous`。
- 只有一个 model 不一致时识别为 `model_level_disagreement`。
- feature-backed 但缺少评估器B时输出 `missing_evaluator_b`。
- 评估器B confidence low 且缺少分歧解释时输出 `needs_second_pass`。
- `xg_present` 只有在 `xg_for` 和 `xg_against` 都非 `None` 时为 true。

### 13.3 Rule Mining

文件：

```text
tests/evaluation/test_rule_mining.py
```

必测：

- feature view 能派生 `dominant_control`。
- feature view 能派生 `poor_control`。
- 重复 WK-too-harsh row 能产生 upgrade candidate。
- 单个分歧会被 reject。
- precision 不达标的 candidate 会被 reject。
- WK patch proposal 的门槛高于 prompt blind spot。
- 缺失字段不会让派生 boolean 变成 true。
- candidate feature view 包含 `missing_features`。

### 13.4 Blind Spot Registry

文件：

```text
tests/evaluation/test_blind_spots_registry.py
```

必测：

- `CalibrationComputer.build_hints()` 从 JSON 加载 active blind spots。
- inactive blind spots 不会被渲染。
- registry 缺失时回退到 `dominant_stats_loss`。
- prompt 仍包含 `known_blind_spots`。

### 13.5 Script E2E

文件：

```text
tests/e2e/test_self_iteration.py
```

必测：

1. `make-jobs` 只输出缺少评估器B的 row。
2. `make-jobs` 优先使用 `entry.backfill.report_path` 查找 report。
3. `make-jobs` 能从 backfill `llm_jobs.jsonl` 复用 prompt，并写 `prompt_source="backfill_llm_job"`。
4. `make-jobs` 找不到 report 时跳过该 row，并在 report 中写 `REPORT_NOT_FOUND`。
5. `make-jobs` 输出 `job_schema_version="self_iteration_job_v1"`。
6. `ingest-results` dry-run 不修改 KB。
7. `ingest-results --write` 修改 KB 并写 snapshot。
8. `adjudicate` 比较所有 feature-backed row。
9. `mine-rules` 写出 candidate 与 rejected-candidate section。
10. `promote-blind-spots --write` 更新 `rubrics/arteta_blind_spots.json`。
11. 重复运行 `promote-blind-spots --write` 不会重复添加 blind spot。
12. `.gitignore` 允许 `data/self_iteration` report，但继续忽略 KB snapshot。

## 14. 验收标准

实现完成必须满足：

- 全部测试通过。
- `rubrics/arteta_blind_spots.json` 存在，并包含 `dominant_stats_loss`。
- `CalibrationComputer` 使用 registry，并能安全 fallback。
- `save_evaluation` 持久化 evaluator metadata。
- evaluator metadata 包含 pipeline/version 字段，可用于 stale evaluation 判断。
- `self_iterate.py make-jobs` 为当前 KB 精确生成缺失的评估器B任务。
- `self_iterate.py make-jobs` 有确定性 report 查找策略和 prompt 来源优先级。
- `self_iterate.py ingest-results --write` 能写入 strict v2 B 输出。
- `self_iterate.py adjudicate` 生成语料级 agreement metrics。
- `self_iterate.py adjudicate` 明确定义并测试 `xg_present`。
- `self_iterate.py mine-rules` 生成 rule candidates，且不修改代码。
- `self_iterate.py mine-rules` 对缺失 feature 使用保守 false 语义。
- `self_iterate.py promote-blind-spots` 能安全更新 prompt-level blind spots。
- `.gitignore` 允许 self-iteration review artifacts，同时排除完整 KB snapshot。
- 当前 102 条 feature-backed 语料有可复现的自迭代 run：

```text
data/self_iteration/runs/b-001/
```

## 15. 实施后的运行策略

每一场新的阿森纳比赛：

1. 运行 `prepare_evaluation` 生成 features、WK、prompt。
2. 在仓库外用该 prompt 运行评估器B。
3. 通过 `self_iterate.py ingest-results --write` 写入评估器B输出。
4. 运行 `self_iterate.py adjudicate`。
5. 运行 `self_iterate.py mine-rules`。
6. 自动升级通过门槛的 prompt-level blind spot。
7. 只有通过更高门槛的 candidate 才生成 WK patch spec。

人工工作只保留在：

- 抽检少量评估器B输出。
- 审批 WK patch spec。
- review 会重新定义 Arteta 模型边界的高风险 candidate。

## 16. 为什么这能降低人工依赖

这个闭环不再要求人工逐场标注训练样本。

新的机制是：

- 评估器B标注所有 feature-backed 比赛。
- WK/B 一致样本成为自动训练信号。
- WK/B 分歧样本成为候选证据。
- 重复模式升级成 prompt guardrail。
- 只有 deterministic WK 规则变化需要人工审批。

这样可以让 skill 持续自迭代，同时保留 pseudo-gold 与 explicit human truth 的边界。
