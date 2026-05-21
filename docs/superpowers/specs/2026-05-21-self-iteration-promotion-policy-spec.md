# Self-Iteration Promotion Policy v1 规格

日期：2026-05-21
状态：待实现
受众：实现代理

## 1. 背景

当前系统已经能完成：

- feature backfill
- weak label replay
- evaluator B 批量评估
- ingest quality gate
- WK/B adjudication
- run-to-run comparison
- predicate mining / replay

但还缺一层自动决策：

```text
一次实验跑完后，系统应该自动判断：
promote / rollback / rerun / collect_more_data / reject_quality / human_review_required
```

现在这一步主要靠人工解释。

这意味着系统已经能“观察”和“试错”，但还不能稳定“保留有效变化、拒绝无效变化”。

本 spec 的目标是补上自迭代闭环中的 promotion / rollback policy。

## 2. 产品目标

新增一个实验决策层，使系统能够：

1. 读取既有 run artifact。
2. 基于 clean-subset comparison 和 quality gate 自动给出实验结论。
3. 把有效实验标记为 `promote`。
4. 把回退实验标记为 `rollback`。
5. 把污染或疑似污染实验标记为 `reject_quality` 或 `rerun`.
6. 把样本不足实验标记为 `collect_more_data`。
7. 产出可提交、可审计的 `experiment_decision.json`。

本阶段不要求自动修改 prompt registry 或 weak labeler。

先让系统能稳定“做判断”。

## 3. 非目标

- 不调用 evaluator B。
- 不拉取 API-Football 数据。
- 不修改 `data/knowledge.json`。
- 不修改 `weak_labeler.py`。
- 不修改 prompt 文案。
- 不自动 promote blind spot registry。
- 不覆盖 human review。
- 不使用 b-002 作为正向 baseline。

## 4. 输入文件

新增命令读取：

```text
baseline adjudication_report.json
candidate adjudication_report.json
comparison_report.json
ingest_report.json
```

可选读取：

```text
candidate mining/replay summary
feature_enrichment_summary.json
```

典型用法：

```bash
python scripts/self_iterate.py decide-experiment \
  --baseline-run-id b-003 \
  --candidate-run-id b-004 \
  --baseline-adjudication data/self_iteration/runs/b-003/adjudication_report.json \
  --candidate-adjudication data/self_iteration/runs/b-004/adjudication_report.json \
  --comparison data/self_iteration/runs/b-004/comparison_report.json \
  --ingest-report data/self_iteration/runs/b-004/ingest_report.json \
  --output data/self_iteration/runs/b-004/experiment_decision.json
```

## 5. 输出结构

```json
{
  "policy_version": "self_iteration_promotion_v1",
  "baseline_run_id": "b-003",
  "candidate_run_id": "b-004",
  "decision": "promote | rollback | rerun | collect_more_data | reject_quality | human_review_required | no_action",
  "effective": false,
  "primary_basis": "clean_subset",
  "metrics": {
    "baseline": {},
    "candidate": {},
    "delta": {},
    "criteria_met": 0,
    "criteria_total": 5,
    "same_denominator": true
  },
  "quality": {
    "total_results": 102,
    "applied": 93,
    "errors": 9,
    "quarantine_rate": 0.0882
  },
  "gates": {
    "min_compared": {"passed": true, "value": 93, "threshold": 90},
    "quality": {"passed": true, "value": 0.0882, "threshold": 0.15},
    "effectiveness": {"passed": false, "criteria_met": 1, "threshold": 3},
    "generous_drift": {"passed": false, "delta": 6, "threshold": 5}
  },
  "reasons": [],
  "recommended_actions": []
}
```

## 6. 决策规则

按优先级判断。

### 6.1 collect_more_data

当有效 comparison 样本不足：

```text
candidate.compared < 90
```

输出：

```text
decision = collect_more_data
```

原因：

```text
有效样本低于门槛，不能判断实验效果。
```

### 6.2 reject_quality

当评估质量明显污染：

任一条件满足：

```text
quarantine_rate >= 0.20
```

或：

```text
overall_delta < 0
dimension_delta < 0
model_delta < 0
wk_too_generous_delta >= 10
```

第二条用于捕捉 b-002 这类质量污染：所有 agreement 同时下降，且 `wk_too_generous` 大幅暴涨。

输出：

```text
decision = reject_quality
```

原因：

```text
评估输出疑似污染，不应用于 promote 或规则蒸馏。
```

### 6.3 rollback

当样本足够、质量未严重污染，但实验相对 baseline 回退：

任一条件满足：

```text
criteria_met < 3
effective == false
overall_delta < 0 and dimension_delta < 0
wk_too_generous_delta > 5 and overall_delta <= 0
```

输出：

```text
decision = rollback
```

原因：

```text
实验未达到 promote 门槛，应回滚或降权。
```

### 6.4 promote

必须全部满足：

```text
candidate.compared >= 90
quarantine_rate < 0.15
same_denominator == true
criteria_met >= 3
effective == true
overall_delta >= 0
dimension_delta >= 0
model_delta >= 0
```

同时：

```text
wk_too_generous_delta <= 5
```

例外：

如果 `criteria_met == criteria_total` 且三项 agreement delta 全部显著为正，可以允许 `wk_too_generous_delta > 5`，但必须在 reasons 中标为 caution。

这个例外用于 b-003：它整体改善非常强，但 `wk_too_generous` 增加，需要记录风险而不是直接拒绝。

输出：

```text
decision = promote
```

### 6.5 human_review_required

当指标接近 promote，但存在风险：

```text
criteria_met >= 3
effective == true
wk_too_generous_delta > 5
```

且不满足 promote 例外条件。

输出：

```text
decision = human_review_required
```

### 6.6 no_action

当无明显提升、无严重污染、也不值得回滚时：

```text
decision = no_action
```

## 7. Primary Basis 选择

优先使用 `comparison_report.clean_subset`。

原因：

- run-to-run 的 denominator 经常不同。
- quarantine 会造成 b-003 / b-004 compared 不一致。
- clean subset 是当前最稳定的 apples-to-apples 对比。

如果没有 clean subset：

- 只有在 `same_denominator == true` 时使用 top-level comparison。
- 否则返回 `collect_more_data` 或 `human_review_required`。

## 8. 既有 runs 回放预期

### 8.1 b-003

输入：

```text
baseline = b-001
candidate = b-003
comparison = data/self_iteration/runs/b-003/comparison_report.json
ingest = data/self_iteration/runs/b-003/ingest_report.json
```

预期：

```text
decision = promote
effective = true
primary_basis = clean_subset
```

允许 caution：

```text
wk_too_generous increased
```

### 8.2 b-004

输入：

```text
baseline = b-003
candidate = b-004
comparison = data/self_iteration/runs/b-004/comparison_report.json
ingest = data/self_iteration/runs/b-004/ingest_report.json
```

预期：

```text
decision = rollback
effective = false
```

原因：

```text
b-004 vs b-003 是 regression，criteria 1/5。
```

### 8.3 b-002

输入：

```text
baseline = b-001
candidate = b-002
comparison = data/self_iteration/runs/b-002/comparison_report.json
ingest = data/self_iteration/runs/b-002/ingest_report.json
```

预期：

```text
decision = reject_quality
```

原因：

```text
overall / dimension / model agreement 全部下降，wk_too_generous 暴涨。
```

## 9. 测试要求

新增测试：

1. `TestExperimentDecisionPromote`
   - b-003-like comparison -> `promote`
2. `TestExperimentDecisionRollback`
   - b-004-like comparison -> `rollback`
3. `TestExperimentDecisionRejectQuality`
   - b-002-like comparison -> `reject_quality`
4. `TestExperimentDecisionCollectMoreData`
   - compared < 90 -> `collect_more_data`
5. `TestExperimentDecisionHumanReview`
   - effective but generous drift high and no full criteria -> `human_review_required`
6. CLI test
   - `decide-experiment` writes `experiment_decision.json`

完整测试：

```bash
uv run --with pytest --with pytest-mock --with pyyaml --with requests --with pandas pytest
```

## 10. Done Definition

完成必须满足：

- 新增 `decide-experiment` CLI。
- 产出 `experiment_decision.json`。
- b-003 decision = `promote`。
- b-004 decision = `rollback`。
- b-002 decision = `reject_quality`。
- 不修改 KB。
- 不调用外部 API。
- 全量测试通过。

