# Hoplite — Arsenal Tactical Analysis Engine

Post-match analysis through Mikel Arteta's tactical principles. Data pipeline → 6 mental model analysis → Feishu card reports.

**Architecture:**
```
Pre-match context → Predictor (Arteta mental models) → 6 Model Evaluators → 3D Assessment → Narrative → Card + Knowledge Base
```

---

## Tool Calls (sequential)

### Step 1: Fetch Match Data
Run: `python -m src fetch_match_data --team Arsenal --status FINISHED --limit 1`
Input: none (config from config.yaml)
Output: Match JSON with xG when available

### Step 2: Analyze Match
Run: `python -m src analyze_match < match.json`
Input: Match JSON from Step 1
Output: MatchReport JSON + search_queries list

### Step 3: Execute Search Queries
For each query in search_queries:
  Use Brave Search MCP tool to find post-match tactical analysis
  Collect results as search_context

### Step 4: Build Narrative Prompt
Run: `python -m src build_narrative_prompt < report.json`
Input: MatchReport JSON + search_context
Output: Prompt text for LLM

### Step 5: LLM Narrative Synthesis
Read the prompt from Step 4. Generate a tactical narrative (300-400 words) **in objective third-person Chinese**:

Style requirements:
- Short lines, conversational, Elio voice
- Chinese + English terms without spaces (e.g. "rest-defence", "xG")
- Analyze WHY things happened, not just WHAT
- Reference Arteta's tactical principles contextually, not cosplaying him
- End with a one-sentence verdict

### Step 6: Build & Send Card
Run: `python -m src build_card < report.json` (with narrative)
Then: `lark-cli im +messages-send --card` from output path
Target: same channel user invoked from

---

## Output Format

Feishu v3.0 interactive card with:
- Match header (score + overall signal emoji)
- 3-dimension summary line (执行🟢 调整🟡 满意🟢)
- 4 mental model summaries (signal + one-liner)
- Tactical Narrative (LLM-generated, objective Chinese)
- Full report doc link

---

## Agent Responsibilities
- You orchestrate the tool sequence (this is not automated in Python)
- You execute Brave searches (MCP brave_brave_web_search)
- You write the tactical narrative (this is YOUR job, not a tool's job)
- You send the card (lark-cli)

---

## Arteta's 6 Mental Models (Built-in Decision Brain)

The analysis framework is built on Arteta's six core mental models:

1. **文化是战术的操作系统 (Culture as OS)** — Standards, energy, accountability precede tactics
2. **控制比赛发生在哪里 (Where Game is Played)** — Control zones, rhythm, emotion, not just possession
3. **防守也是进攻身份 (Defence as Attacking Identity)** — Defending enables attacking; players must love defending
4. **边际收益要专家化 (Marginal Gains Expertized)** — Specialize set pieces, transitions, every department
5. **加能力但不要丢身份 (Add Capability, Keep Identity)** — Keep traditions, add new weapons
6. **人需要清晰度不只压力 (Role Clarity > Pressure)** — Context, protection, clear roles for every player

Each model outputs 🟢🟡🔴 qualitative signal with evidence.

---

## Three-Dimension Assessment

Replaces old 0-10 scoring:
- ① **赛前决策执行度** — Did the team execute the pre-match plan? (vs predicted plan)
- ② **赛中调整合理性** — Were adjustments timely and correct? (subs, formation, tactical shifts)
- ③ **比赛结果满意度** — Given context, was result satisfactory? (opponent quality, stage, injuries)

Overall signal: simple 🟢🟡🔴 voting across three dimensions.

---

## Self-Iterating Knowledge Base

After each analysis, a match entry is saved to `/tmp/hoplite/data/knowledge.json` containing:
- Pre-match context + predicted plan
- Actual execution signals (all 6 models + 3 dimensions)
- Future predictions reference historical patterns via `KnowledgeBase.find_similar_context()`

---

## Requirements

- football-data.org API token (free tier)
- API-Football key (free tier, 100 req/day)
- lark-cli 1.0.23+ with bot identity configured
- Python 3.11+, requests, pandas in venv

## Data Sources

- football-data.org: fixtures, results, standings
- Understat: xG data
- API-Football: events, lineups, stats
- Brave Search: post-match tactical analysis
