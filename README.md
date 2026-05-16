# Hoplite ⚔️🔴⚪

Arsenal post-match tactical analysis engine. Extracts raw match data, then analyzes through Mikel Arteta's six mental models via LLM.

## Architecture

```
Python tools (data extraction) → SKILL.md (decision framework) → LLM (analysis + narrative) → Feishu card
```

| Layer | What | Won't |
|---|---|---|
| `src/tools/extract.py` | Stats, events, context from match JSON | Judgment, scoring |
| `src/tools/analyze.py` | Orchestrates extraction → assembly | Evaluation |
| `src/tools/prompt.py` | Formats raw data + Arteta framework for LLM | Decision logic |
| `SKILL.md` | Arteta 6 mental models + 3D assessment framework | Raw data processing |
| LLM | Qualitative analysis + Chinese narrative | — |

## Arteta's 6 Mental Models

1. **Culture as OS** — Standards, energy, accountability precede tactics
2. **Where Game is Played** — Control zones, rhythm, emotion
3. **Defence as Attacking Identity** — Defending enables attacking
4. **Marginal Gains Expertized** — Specialize every department
5. **Add Capability, Keep Identity** — Evolve without losing tradition
6. **Role Clarity > Pressure** — Context, protection, clear roles

## Evolution Layer

Self-iterating through historical match patterns:

- `knowledge.json` — stores per-match context + predicted plan + outcomes
- `patterns.py` — computes historical patterns for similar match contexts
- `predictor.py` — weights pre-match predictions using historical effectiveness
- `prompt.py` — injects historical pattern references into LLM prompt

## Quick Start

```bash
git clone https://github.com/project-tharsis/hoplite.git
cd hoplite
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp config.example.yaml config.yaml  # add API keys

# Step 1: Fetch latest Arsenal match data
python -m src fetch_match_data > match.json

# Step 2: Analyze (if fetch succeeded)
python -m src analyze_match < match.json
```

## Data Sources

- [API-Football](https://api-football.com) — events, lineups, stats (free tier)
- [football-data.org](https://football-data.org) — fixtures, results (free tier)

## License

MIT
