# Hoplite v3 — Arteta Decision Brain

## Goal
Arteta 6 心智模型内置为分析框架。去打分 → 三维度定性判定（🟢🟡🔴）。
叙事客观第三人称中文。知识库自迭代（本地 JSON）。

## Architecture Diff

```
v2:  6 hardcoded lenses (score 0-10) →  artifact-perspective (voice only) → narrative
v3:  Arteta 6 mental models (evaluator) → 3-dimension assessment (🟢🟡🔴) → objective narrative → knowledge base
```

---

## Phase A: Evaluation Framework (新文件)

### Task A.1 — Mental Model Evaluators
**File:** `src/evaluation/mental_models.py`

6 个 evaluator 类，每个映射一个 Arteta 心智模型：
- `CultureEvaluator` — 模型1: 标准/能量/责任
- `ControlEvaluator` — 模型2: 比赛区域控制
- `DefenceIdentityEvaluator` — 模型3: 防守→进攻转化
- `MarginalGainsEvaluator` — 模型4: 定位球/转换等边际部门
- `IdentityEvolutionEvaluator` — 模型5: 叠加能力而不丢身份
- `RoleClarityEvaluator` — 模型6: 角色清晰度

每个 evaluator:
- `evaluate(match: Match, context: dict) -> MentalModelResult`
- `MentalModelResult` = {model_name, model_number, signal: 🟢🟡🔴, summary, evidence, insights}
- 不打分，做定性判断 + 证据引用

### Task A.2 — Three-Dimension Assessment
**File:** `src/evaluation/dimensions.py`

- `PreMatchExecutionDimension` — 赛前决策执行度
- `InMatchAdjustmentDimension` — 赛中调整合理性
- `ResultSatisfactionDimension` — 结果满意度

每个 dimension 输出: signal (🟢🟡🔴), verdict (短句), reasoning, evidence

### Task A.3 — Pre-Match Predictor
**File:** `src/evaluation/predictor.py`

基于赛前 context + Arteta 心智模型 → 方向性预测：
- 不预测"4-3-3高位压迫"，而是预测"优先控制中路""强侧 overload"
- `predict(match_context: dict) -> PredictedPlan`
- `PredictedPlan` = {focus_areas: [...], likely_approach, key_battles, expected_subs}

### Task A.4 — Knowledge Base
**File:** `src/evaluation/knowledge.py`

本地 JSON 持久化 (`/tmp/hoplite/data/knowledge.json`):
- `save_entry(match_id, pre_context, predicted_plan, actual_evaluation, outcome)`
- `query_patterns(query_type, filters) -> list` — 历史模式查询
- 用于未来预测时引用历史

---

## Phase B: Report + Tools (重构)

### Task B.1 — New MatchReport
**File:** `src/report.py` (重写)

```python
@dataclass
class MatchReport:
    match: Match
    mental_model_results: list[MentalModelResult]
    execution: DimensionResult       # ① 赛前决策执行度
    adjustment: DimensionResult      # ② 赛中调整合理性  
    satisfaction: DimensionResult    # ③ 结果满意度
    predicted_plan: PredictedPlan    # 赛前预测
    
    @property
    def overall_signal(self) -> str:  # 三信号投票
```

移除: `overall_score`, `one_line_summary`, `ReportOrchestrator`, 6 lens references

### Task B.2 — New analyze tool
**File:** `src/tools/analyze.py` (重写)

新流程:
1. 从 match data 提取 pre-match context
2. 调用 predictor.predict() → 方向性预测
3. 运行 6 个 mental model evaluator
4. 运行 3 个 dimension assessment
5. 输出 MatchReport JSON
6. 写 knowledge base

### Task B.3 — New prompt builder
**File:** `src/tools/prompt.py` (重写)

新 prompt 风格:
- 中文叙事
- 客观第三人称（非"我们"非"我"）
- 基于 6 心智模型评估 + 3 维度信号
- Elio 语气: 短句分行，中英文不加空格
- 结尾: 一句话判决

---

## Phase C: Card + SKILL.md

### Task C.1 — New Card Builder
**File:** `src/output/feishu_card.py` (重写)

新 card 布局:
```
Header: 🟢 Arsenal 1-0 West Ham
Body:
  综合: 执行🟢 调整🟡 满意🟢
  ---
  6 模型摘要（3 句话）
  📄 完整复盘: [doc link]
```
不保留 6-lens 打分 table。换 mental model 信号 + 简短文本。

### Task C.2 — Update SKILL.md
**File:** `SKILL.md`

- 嵌入 Arteta 6 心智模型定义（从 arteta-perspective 提取核心）
- 新 workflow: fetch → predict → evaluate → narrative → card → knowledge
- 移除"load arteta-perspective skill"指令
- 叙事要求: 中文、客观、第三人称
- Card 只放摘要，完整叙事放飞书文档

---

## Phase D: Cleanup + Test

### Task D.1 — Remove old analysis files
删除: `src/analysis/set_pieces.py`, `goals.py`, `build_up.py`, `pressing.py`, `rest_defence.py`, `overload.py`, `search_lens.py`

### Task D.2 — Integration test
用现有测试数据跑全链路，确保新架构产出正确。

---

## Dependencies
- Phase A → no deps (全新文件)
- Phase B → depends on Phase A (需要 evaluation/ 模块)
- Phase C → depends on Phase B (需要新 report/tools)
- Phase D → depends on Phase C
