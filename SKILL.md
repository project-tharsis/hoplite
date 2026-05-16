---
name: hoplite
description: "Hoplite v4 — Arsenal tactical analysis MCP skill. Python extracts raw data; LLM applies Arteta's 6 mental models for qualitative analysis."
version: 4.1.0
---

# Hoplite — Arsenal Tactical Analysis Engine 🔴⚪

Post-match analysis through Mikel Arteta's six mental models. Python extracts raw data; LLM applies decision framework; narrative → Feishu card + Knowledge Base.

**Architecture:**
```
Python tools (raw data extraction) → SKILL.md (Arteta decision framework) → Agent/LLM (qualitative analysis + narrative) → Feishu card
                                    ↕
                           Evolution Layer (knowledge.json → patterns.py → prompt injection)
```

**Separation of concerns:**
- `src/tools/extract.py` — pure stats, events, context. No judgment.
- `src/report.py` — data container. No scoring.
- `src/tools/analyze.py` — orchestrates extraction → assembly
- `src/tools/prompt.py` — injects raw data + Arteta framework + historical patterns as LLM prompt
- `src/evaluation/predictor.py` — directional pre-match plan prediction, KB-weighted when history available
- `src/evaluation/patterns.py` — computes historical patterns (similar matches, focus area effectiveness, model trends)
- `src/evaluation/knowledge.py` — local JSON knowledge base for match storage/retrieval
- `scripts/ingest_history.py` — batch fetch historical matches from API-Football, populate KB
- **SKILL.md (this file)** — the Arteta decision brain: 6 mental model framework, 3D assessment logic, writing rules
- **Agent (LLM)** — applies framework to data, produces signals + narrative

## Language

All user-facing output MUST be in Chinese (简体中文) with Elio's voice: short lines, conversational, Chinese + English terms blended without spaces (e.g. "rest-defence" not "rest defence"). No formal/academic tone.

## Triggers

User says any of:
- "analyze Arsenal latest match"
- "hoplite latest"  
- "Arsenal match report"
- "review Arsenal game"

## Workflow (5-step sequence)

### Step 1: Fetch Match Data
Run the `fetch_match_data` tool to get the latest Arsenal match with xG data:
```bash
source .venv/bin/activate && python -m src fetch_match_data
```
Output: Match JSON (fixture_id, teams, score, xG, events, etc.)

If config.yaml missing → tell user to copy config.example.yaml → config.yaml and add API tokens.

### Step 2: Analyze Match (extract raw data)
Pipe the match JSON into the `analyze_match` tool:
```bash
source .venv/bin/activate && echo '<match_json>' | python -m src analyze_match
```
Output: MatchReport JSON with stats, events, context, predicted_plan, set_pieces, sub_impact.

### Step 3: Build Narrative Prompt (inject Arteta framework)
Pipe the report JSON into the `build_narrative_prompt` tool:
```bash
source .venv/bin/activate && echo '{"report": <report_json>}' | python -m src build_narrative_prompt
```
Output: Prompt string with raw data + Arteta 6 mental model framework + 3D assessment logic.

### Step 4: LLM Evaluation + Narrative
**This is YOUR job.**

The prompt from Step 3 contains:
- Raw match data (stats, events, set pieces, subs, context)
- Predicted pre-match plan
- Arteta's 6 mental model assessment framework (what to look at, how to decide 🟢🟡🔴)
- 3-dimension assessment framework (L1→L2→L3 satisfaction, execution, adjustment)
- Writing style rules

**You must:**
1. Apply each mental model to the raw data → produce signal + evidence
2. Apply 3-dimension assessment → produce signals
3. Vote overall signal from 3 dimensions (≥2🟢→🟢, ≥2🔴→🔴, else🟡)
4. Write 300-400 word Chinese tactical narrative
5. Output as JSON: `{overall_signal, model_signals: {1-6}, dimension_signals: {execution, adjustment, satisfaction}, narrative}`

### Step 5: Build & Send Card
Pipe the report JSON + narrative into the `build_card` tool:
```bash
source .venv/bin/activate && echo '{"report": <report_json>, "narrative": "<narrative>"}' | python -m src build_card
```
Output: Card JSON file path. Send via `lark-cli` with your chat_id.

## Output Format

Feishu v4.0 interactive card with:
- Match header (score + overall signal emoji)
- 3-dimension summary line (执行🟢 调整🟡 满意🟢)
- 6 mental model summaries (signal + one-liner each)
- Tactical Narrative (LLM-generated, objective Chinese)
- 📄 完整复盘 button (doc link)

## Arteta's 6 Mental Models (Decision Brain)

**Note:** In v4, these models live HERE in SKILL.md — not in Python. Python extracts raw data; the LLM applies these models by reading the prompt from `build_narrative_prompt` (which injects the same framework). This section serves as the canonical reference.

### 模型1: 文化是战术的操作系统 (Culture as OS)
**Philosophy:** Standards, energy, accountability precede tactics.
**Data points:** Yellow card timing vs match state, fouls, pressing intensity, focus before/after half-time.
- 🟢: Good discipline, fouls under control, pressing active
- 🟡: 1-2 yellows, manageable
- 🔴: Red card, poor-timing yellows, fouls out of control
**Key:** 89th minute tactical yellow when leading 7-0 ≠ 2nd minute reckless yellow at 0-0.

### 模型2: 控制比赛发生在哪里 (Where the Game is Played)
**Philosophy:** Control isn't just possession — it's zones, rhythm, emotion.
**Data points:** Possession %, shots, xG, pass accuracy, corners.
- 🟢: Possession ≥55%, shot dominance, high xG
- 🟡: Close data, some passive periods
- 🔴: Possession ≤45%, fewer shots, trapped in defensive third

### 模型3: 防守也是进攻身份 (Defence as Attacking Identity)
**Philosophy:** Defence creates the platform for attack. Players must LOVE defending.
**Data points:** Goals conceded, opponent shots on target, clean sheet, counter-attack goals.
- 🟢: Clean sheet or ≤1 conceded, ≤3 opponent shots on target
- 🟡: 1-2 conceded, attack unaffected
- 🔴: 3+ conceded, defensive collapse

### 模型4: 边际收益要专家化 (Marginal Gains Expertized)
**Philosophy:** Set pieces and transitions can't be run by part-timers.
**Data points:** Set piece goals/conceded, corner conversion, penalties.
- 🟢: ≥2 set piece goals, 0 set piece conceded
- 🟡: Mixed effectiveness
- 🔴: ≥2 set piece conceded, toothless attack

### 模型5: 加能力，但不要丢身份 (Add Capability, Keep Identity)
**Philosophy:** Keep traditions, add new weapons.
**Data points:** Pass accuracy, possession style, goal diversity (multiple scorers = system).
- 🟢: Traditional strengths + new elements both working
- 🟡: One working, one not
- 🔴: Traditional strengths lost

### 模型6: 人需要清晰度，不只是压力 (Role Clarity > Pressure)
**Philosophy:** Subs must know how to contribute. Every player needs role clarity.
**Data points:** Sub impact (scored/assisted?), timing, integration.
- 🟢: Subs produced goals, timing reasonable (45-75 min)
- 🟡: Neutral impact, or match decided
- 🔴: Subs too late (80'+ losing), ineffective

## Three-Dimension Assessment

Replaces old 0-10 scoring. The LLM applies this from the prompt:

- ① **赛前决策执行度** — Compare predicted_plan vs actual stats/events.
- ② **赛中调整合理性** — Check sub timing and impact.
- ③ **比赛结果满意度** — L1(base)→L2(goal diff)→L3(context) modifier system.
  - L1: Win top→🟢, win weak→🟡, lose weak→🔴
  - L2: Win by ≥3→🟢, away win by ≥2→🟢, lose by ≥4→🔴
  - L3: Knockout away win→🟢

Overall signal: vote across 3 dimensions (≥2🟢→🟢, ≥2🔴→🔴, else🟡).

## Evolution Layer

Hoplite's decision brain self-improves through a three-tier evolution layer:

- **Data** (`data/knowledge.json`) — Every match saves context + plan + signals
- **Patterns** (`src/evaluation/patterns.py`) — Queries similar matches, computes signal distributions
- **Injection** (`src/tools/prompt.py` + `predictor.py`) — Historical patterns injected into LLM prompt

Batch-ingest historical matches (2022-2024, ~150 matches) via:
```bash
python scripts/ingest_history.py --season 2024 --league 39
```

## Requirements

- `config.yaml` with API tokens (copy from `config.example.yaml`)
- Python 3.11+ (create `.venv/`: `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`)
- `lark-cli` for Feishu card delivery (optional)
- `jq` available on PATH (for card sending)

## Data Sources

- API-Football — match events, lineups, stats (free tier)
- football-data.org — fixtures, results, standings (free tier)
- Understat — xG data

API-Football free tier is season-lagged (~1 year behind). See `references/data-source-limits.md`.

## Agent Responsibilities

- You orchestrate the 5-step tool sequence (not automated in Python)
- You apply the 6 mental models from this file to raw data from Step 3's prompt
- You apply the 3-dimension assessment framework
- You produce signals (overall + per-model + per-dimension)
- You write the tactical narrative (300-400 words, Chinese, Elio voice)
- You output final JSON with signals + narrative
- Python tools only do data: fetch, extract, prompt building, card JSON
