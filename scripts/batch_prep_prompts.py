#!/usr/bin/env python3
"""Batch prep: fetch data + analyze + build prompt for all pre-2026 matches.
Output: JSONL file with one prompt per line for MIMO subagent evaluation.
"""
import json, sys, os, time, requests, yaml, subprocess
from pathlib import Path

PROJECT = Path(os.environ.get('HOPLITE_DIR', '/home/shuohw/hoplite'))
VENV_PYTHON = str(PROJECT / '.venv' / 'bin' / 'python')
sys.path.insert(0, str(PROJECT))

with open(PROJECT / 'config.yaml') as f:
    config = yaml.safe_load(f)

key = config['data_sources']['api_football']['key']
ARSENAL_ID = 42
s = requests.Session()
s.headers['x-apisports-key'] = key

# Load KB, filter pre-2026 unevaluated
with open(PROJECT / 'data' / 'knowledge.json') as f:
    kb = json.load(f)
entries = kb if isinstance(kb, list) else kb.get('entries', [])

pre_2026 = [e for e in entries if e.get('timestamp', '') < '2026-01-01' and e.get('timestamp', '')]
pre_2026.sort(key=lambda x: x.get('timestamp', ''))

# Also include the empty-timestamp Southampton match
for e in entries:
    if not e.get('timestamp', '') and e.get('match_id') == '1208400':
        pre_2026.insert(0, e)

print(f"Preparing {len(pre_2026)} pre-2026 matches...", file=sys.stderr)

prompts = []
errors = []

for i, e in enumerate(pre_2026):
    fid = e['match_id']
    opponent = e.get('opponent', '?')
    ts = e.get('timestamp', '2025-05-25')[:10] if e.get('timestamp') else '2025-05-25'
    
    try:
        # Fetch full match data from API-Football
        r = s.get(f"https://v3.football.api-sports.io/fixtures", params={"id": int(fid)})
        r.raise_for_status()
        fx_data = r.json()['response'][0]
        fx = fx_data['fixture']
        teams = fx_data['teams']
        score = fx_data.get('score', {}).get('fulltime', {})
        
        # Events
        r = s.get(f"https://v3.football.api-sports.io/fixtures/events", params={"fixture": int(fid)})
        r.raise_for_status()
        events_raw = r.json()['response']
        
        # Lineups
        r = s.get(f"https://v3.football.api-sports.io/fixtures/lineups", params={"fixture": int(fid)})
        r.raise_for_status()
        lineups_raw = r.json()['response']
        
        # Stats
        r = s.get(f"https://v3.football.api-sports.io/fixtures/statistics", params={"fixture": int(fid)})
        r.raise_for_status()
        stats_raw = r.json()['response']
        
        arsenal_is_home = teams['home']['id'] == ARSENAL_ID
        
        # Build match JSON
        home_team = teams['home']['name']
        away_team = teams['away']['name']
        home_score = score.get('home', 0) or 0
        away_score = score.get('away', 0) or 0
        
        result = "W" if (arsenal_is_home and home_score > away_score) or (not arsenal_is_home and away_score > home_score) else \
                 ("L" if (arsenal_is_home and home_score < away_score) or (not arsenal_is_home and away_score < home_score) else "D")
        
        # Parse events
        events = []
        for ev in events_raw:
            t = ev.get('time', {})
            is_arsenal_ev = ev['team']['id'] == ARSENAL_ID
            team = 'home' if (is_arsenal_ev and arsenal_is_home) or (not is_arsenal_ev and not arsenal_is_home) else 'away'
            detail = ev.get('detail', '')
            comments = ev.get('comments', '') or ''
            events.append({
                'minute': t.get('elapsed', 0),
                'type': ev.get('type', '').lower(),
                'team': team,
                'player': ev.get('player', {}).get('name', ''),
                'detail': f"{detail} {comments}".strip(),
            })
        
        # Parse formations
        home_formation = away_formation = None
        for lu in lineups_raw:
            if lu['team']['id'] == ARSENAL_ID:
                if arsenal_is_home: home_formation = lu.get('formation')
                else: away_formation = lu.get('formation')
            else:
                if arsenal_is_home: away_formation = lu.get('formation')
                else: home_formation = lu.get('formation')
        
        # Parse stats (raw API format - extract.py has fallback)
        home_stats = away_stats = None
        if stats_raw:
            for team_stats in stats_raw:
                tid = team_stats['team']['id']
                sd = {s['type']: s.get('value') for s in team_stats.get('statistics', [])}
                if tid == ARSENAL_ID:
                    if arsenal_is_home: home_stats = sd
                    else: away_stats = sd
                else:
                    if arsenal_is_home: away_stats = sd
                    else: home_stats = sd
        
        match_json = {
            'fixture_id': fx['id'],
            'date': fx['date'],
            'competition': e.get('competition', 'Premier League'),
            'home_team': home_team, 'away_team': away_team,
            'home_score': home_score, 'away_score': away_score,
            'home_xg': None, 'away_xg': None,
            'home_formation': home_formation, 'away_formation': away_formation,
            'events': events, 'home_lineup': [], 'away_lineup': [],
            'result': result, 'arsenal_is_home': arsenal_is_home,
            'home_stats': home_stats, 'away_stats': away_stats,
        }
        
        # Run analyze_match
        r = subprocess.run(
            [VENV_PYTHON, '-m', 'src', 'analyze_match'],
            input=json.dumps(match_json), capture_output=True, text=True, timeout=30,
            cwd=str(PROJECT), env={**os.environ, 'PYTHONPATH': str(PROJECT)}
        )
        analyze_result = json.loads(r.stdout)
        
        # Run build_narrative_prompt with skip_history
        r = subprocess.run(
            [VENV_PYTHON, '-m', 'src', 'build_narrative_prompt'],
            input=json.dumps({"report": analyze_result["report"], "skip_history": True}),
            capture_output=True, text=True, timeout=30,
            cwd=str(PROJECT), env={**os.environ, 'PYTHONPATH': str(PROJECT)}
        )
        prompt = r.stdout
        
        # Build eval input for subagent
        eval_input = {
            "match_id": str(fid),
            "timestamp": ts,
            "opponent": opponent,
            "competition": e.get('competition', '?'),
            "report": analyze_result["report"],
            "prompt": prompt,
        }
        prompts.append(eval_input)
        
        print(f"  [{i+1}/{len(pre_2026)}] ✅ {ts} {opponent}", file=sys.stderr)
        time.sleep(0.3)  # Rate limit
        
    except Exception as ex:
        print(f"  [{i+1}/{len(pre_2026)}] ❌ {ts} {opponent}: {ex}", file=sys.stderr)
        errors.append({"match_id": fid, "opponent": opponent, "error": str(ex)})

# Save prompts
output_path = PROJECT / 'data' / 'batch_prompts_pre2026.jsonl'
with open(output_path, 'w') as f:
    for p in prompts:
        f.write(json.dumps(p, ensure_ascii=False) + '\n')

print(f"\nDone: {len(prompts)} prompts saved to {output_path}", file=sys.stderr)
if errors:
    print(f"Errors: {len(errors)}", file=sys.stderr)
    for err in errors:
        print(f"  ❌ {err['opponent']}: {err['error']}", file=sys.stderr)
