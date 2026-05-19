# Design Decision Record: Calibration Rule Extraction & WK Patch v1

## 问题

人工 review 发现了 WK 系统性错误（dominant stats + L ≠ 🟢），但当前没有机制把这条经验提炼成可复用的规则。human_override 只是样本存在 KB 里，replay 和 calibration 都不消费它。目标：把第一次人工 review 的三个锚点变成 WK 修正规则 + CalibrationComputer 盲区提示 + replay 可比较。

## 竞品扫描

无直接竞品。这是 calibration 系统自改进的元层——把人工反馈编码为规则。NLP 里有 active learning / rule refinement，但足球分析领域没有成熟方案。我们的独特空白：**不是"更多训练数据"，是"从 review diff 提取规则修正"。**

## 方案对比

| 维度 | 方案 A: Satisfaction Guard | 方案 B: Full Result-Aware Rewrite | 不做 |
|---|---|---|---|
| 复杂度 | 低 — 只改 satisfaction 维度计算逻辑 | 高 — 重写 overall signal 计算，加入 result×quality 矩阵 | 零 |
| 维护成本 | 低 — 规则显式、可测试 | 中 — 矩阵维护 | 零 |
| 覆盖问题 | 精准覆盖 dominant-stats+L 盲区 | 覆盖所有 result 场景但过度设计 | 盲区持续 |
| 引入回归风险 | 低 — 只改一个维度 + 3 个 guardrail 规则 | 高 — 可能误伤正常场景 | 零 |
| 可解释性 | 高 — 规则 = 人类可读 | 中 | 无 |

## 决策

选 **方案 A**。理由：
1. 3 条 human review 的锚点全部指向同一个模式：dominant stats + L + low-quality opponent → WK over-optimistic
2. 不需要重写整个评分系统，只需在 satisfaction 维度加 result-aware guard，在 CalibrationComputer 加盲区提示
3. 33 条测试文件，改动量最小化 → 回归风险可控
4. 留下扩产空间：如果 future review 发现新模式，再加新规则

## 接口契约

### Phase 1: WK satisfaction guard
```
Input: MatchFeatures (已有)
Modify: WeakLabeler._model_5_identity (不改)
Modify: WeakLabeler.label() 的 satisfaction 维度派生逻辑
规则:
  IF result == "L":
    IF opponent_quality in ("lower", "mid_table"):
      satisfaction = RED  # 覆盖多数投票
    ELSE (top6 / european_elite / knockout):
      satisfaction = max(satisfaction_vote, YELLOW)  # 不低于🟡
```

### Phase 2: Human override → replay
```
New: replay_history.py --compare-human
Output: 每场的 {match_id, WK_signal, LLM_signal, human_signal, disagreements: [{model, WK, LLM, human}]}
Read-only, never mutates KB
```

### Phase 3: CalibrationComputer blind spots
```
New: CalibrationComputer.KNOWN_BLIND_SPOTS = [...]
CalibrationComputer.build_hints() 输出新增 known_blind_spots 字段
PromptBuilder 渲染盲区提示到 calibration section
```

### Phase 4: Replay 30 seed
```
replay_history.py --kb data/knowledge.json --mode weak-label-only
dry-run: 输出 diff（WK changes），不写 KB
重点验证: 1531572 WK 🔴, 其他胜场不被误伤
```

### Phase 5: 扩展到 70+ validation
```
backfill_history.py --mode validate-rest
先 dry-run 看 comparison 报告
批准后 --write
```

## 数据流

```
human_override in KB
        ↓
Phase 2: replay --compare-human reads human_override
        ↓                         
Phase 3: CalibrationComputer.known_blind_spots ← hardcoded from Phase 1 pattern analysis
        ↓
PromptBuilder renders blind spots to prompt
        ↓
LLM sees: "⚠️ Known WK blind spot: dominant stats + loss ≠ 🟢"
```

## 错误处理

- WK guard 规则冲突：新规则与现有多数投票冲突 → 显式 override，规则优先于投票
- missing opponent_quality：satisfaction guard 降级为 YELLOW
- replay 找不到 human_override：skip，不报错
- 新 WK 规则误伤胜场：Phase 4 dry-run 全覆盖 30 场，任何意外变化 → 暂停，回看规则

## 风险与假设

- 假设 1：当前 3 条 human review 的 pattern (dominant+L) 是最大盲区。如果后续 review 发现更大盲区，需要加新规则 → 低风险，架构支持增量
- 假设 2：satisfaction guard 不会误伤 top6 负场。验证：top6 L 仍可🟡 → 通过 Phase 4 验证
- 假设 3：opponent_quality 在所有 seed 条目中已正确（context override fix 已闭环）→ 已验证
- 风险：satisfaction RED 可能通过 overall signal 投票把 overall 变成 🔴（≥2 RED dims）。期望行为：输弱敌确实应该 🔴 → 这不是 bug 是 feature

## 进入 Plan 的前置条件

- [x] 用户确认 DDR（待确认）
- [x] 所有假设已被记录
- [x] 接口契约已明确
- [x] 5 个 phase 边界清晰
