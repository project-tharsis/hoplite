# Hoplite Evolution Layer — 开发计划

## Goal
进化层三层架构落地：数据层(knowledge.json) → 模式层(patterns.py) → 注入层(SKILL.md+prompt)。

## Principle
6 心智模型框架不动。进化发生在：predictor 参考历史模式做加权，agent 评估时收到类似场景的统计参考。

## Phase F1: patterns.py — 模式计算
**File:** `src/evaluation/patterns.py` (NEW, ~80 行)

```python
class PatternComputer:
    def __init__(self, kb_path):
        self.kb = KnowledgeBase(kb_path)
    
    def similar_matches(self, context: dict, limit: int = 5) -> dict:
        """查询类似场景的历史比赛，返回汇总统计"""
        # 从 KB 查 opponent_quality + venue + competition_stage 匹配的场次
        # 返回: count, wins, avg_possession, avg_xg, avg_shots, 等
    
    def focus_area_effectiveness(self, focus_area: str, context: dict) -> dict:
        """某个战术重点在类似场景下的历史效果"""
        # 返回: count, win_rate, avg_execution_signal
    
    def player_pattern(self, player: str, situation: str) -> dict:
        """特定球员/场景的历史表现"""
```

## Phase F2: predictor.py 查 patterns 加权
**File:** `src/evaluation/predictor.py` (MODIFY, +10 行)

predict() 新增可选参数 `kb: KnowledgeBase = None`。
传入时：先用 find_similar_context() 查历史，对 focus_areas 做加权——历史上效果好的方向加重推荐。

## Phase F3: prompt.py 注入历史模式
**File:** `src/tools/prompt.py` (MODIFY, +30 行)

新增 `inject_historical_patterns(report_json, kb_path)` 函数：
- 从 context 查 similar_matches
- 生成 "历史模式参考" markdown 块
- 插入到 prompt 中（在 Arteta 框架之前）

## Phase F4: 历史数据批量采集
**File:** `scripts/ingest_history.py` (NEW, ~60 行)

逐赛季 fetch Arsenal fixtures → 逐场 fetch events+lineups → extract → predict → save to KB。
跳过 LLM 评估（历史比赛不需要信号，只存 context+plan+stats）。

采集量：3 赛季 × ~50 场 = ~150 场，300 次 API 调用，分 3 天完成。

## Phase F5: 集成测试
用已有 PSV 7-1 数据 + 新增历史模式 → 跑全链路，验证 patterns 正确注入 prompt。

## Dependencies
F1 + F4 并行 → F2 (依赖 F1) → F3 (依赖 F1+F2) → F5
