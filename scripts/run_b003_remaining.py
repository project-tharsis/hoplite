#!/usr/bin/env python3
"""Run remaining b-003 evaluations (jobs without results)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

MIMO_BASE_URL = os.environ.get("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
MODEL = "mimo-v2.5-pro"
RUN_DIR = Path("data/self_iteration/runs/b-003")


def call_llm(prompt: str, max_retries: int = 3) -> dict:
    headers = {
        "Authorization": f"Bearer {MIMO_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "You are a football tactical analyst. Respond ONLY with valid JSON matching the requested schema. Do not include markdown code blocks or any text outside the JSON."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 4000,
    }
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                f"{MIMO_BASE_URL}/chat/completions",
                headers=headers,
                json=payload,
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                if "```json" in content:
                    return json.loads(content.split("```json")[1].split("```")[0].strip())
                elif "```" in content:
                    return json.loads(content.split("```")[1].split("```")[0].strip())
                raise
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Max retries exceeded")


def main():
    # Load all jobs
    jobs = {}
    with open(RUN_DIR / "llm_jobs.jsonl", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                j = json.loads(line)
                jobs[j["match_id"]] = j

    # Load all valid results
    results = {}
    for p in sorted(RUN_DIR.glob("batch_*_results.jsonl")):
        with open(p, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    mid = r.get("match_id", "")
                    if mid and "evaluation" in r and "error" not in r:
                        results[mid] = r

    lr = RUN_DIR / "llm_results.jsonl"
    if lr.exists():
        with open(lr, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    mid = r.get("match_id", "")
                    if mid and "evaluation" in r and "error" not in r:
                        results[mid] = r

    missing_ids = sorted(set(jobs.keys()) - set(results.keys()))
    print(f"Total jobs: {len(jobs)}")
    print(f"Already done: {len(results)}")
    print(f"Remaining: {len(missing_ids)}")

    if not missing_ids:
        print("Nothing to do.")
        return

    output_path = RUN_DIR / "batch_07_results.jsonl"
    with open(output_path, "w", encoding="utf-8") as f:
        for i, mid in enumerate(missing_ids):
            job = jobs[mid]
            print(f"[{i+1}/{len(missing_ids)}] {mid}...", end=" ", flush=True)
            try:
                result = call_llm(job["prompt"])
                row = {
                    "job_schema_version": "self_iteration_job_v1",
                    "match_id": mid,
                    "evaluator_id": job["evaluator_id"],
                    "run_id": job["run_id"],
                    "prompt_hash": job["prompt_hash"],
                    "model": MODEL,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "evaluation": result,
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print("OK")
            except Exception as e:
                print(f"ERROR: {e}")
                row = {
                    "job_schema_version": "self_iteration_job_v1",
                    "match_id": mid,
                    "evaluator_id": job["evaluator_id"],
                    "run_id": job["run_id"],
                    "prompt_hash": job["prompt_hash"],
                    "model": MODEL,
                    "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "error": str(e),
                }
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
            time.sleep(0.5)

    print(f"Done. Results written to {output_path}")


if __name__ == "__main__":
    main()
