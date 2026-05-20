#!/usr/bin/env python3
"""Parallel runner for remaining b-003 evaluations."""
from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

MIMO_BASE_URL = os.environ.get("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
MODEL = "mimo-v2.5-pro"
RUN_DIR = Path("data/self_iteration/runs/b-003")


def call_llm(prompt: str, max_retries: int = 3) -> dict:
    headers = {"Authorization": f"Bearer {MIMO_API_KEY}", "Content-Type": "application/json"}
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
            resp = requests.post(f"{MIMO_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=180)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
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


def process_job(job: dict) -> dict:
    mid = job["match_id"]
    try:
        result = call_llm(job["prompt"])
        return {"match_id": mid, "status": "ok", "evaluation": result, "evaluator_id": job["evaluator_id"], "run_id": job["run_id"], "prompt_hash": job["prompt_hash"]}
    except Exception as e:
        return {"match_id": mid, "status": "error", "error": str(e), "evaluator_id": job["evaluator_id"], "run_id": job["run_id"], "prompt_hash": job["prompt_hash"]}


def main():
    with open("/tmp/b003_missing.json") as f:
        missing_ids = json.load(f)

    # Load jobs
    jobs = {}
    with open(RUN_DIR / "llm_jobs.jsonl") as f:
        for line in f:
            if line.strip():
                j = json.loads(line)
                jobs[j["match_id"]] = j

    missing_jobs = [jobs[mid] for mid in missing_ids if mid in jobs]
    print(f"Running {len(missing_jobs)} jobs with 4 workers...")

    output_path = RUN_DIR / "batch_08_results.jsonl"
    done = 0
    errors = 0

    with open(output_path, "w", encoding="utf-8") as f:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(process_job, job): job["match_id"] for job in missing_jobs}
            for future in as_completed(futures):
                mid = futures[future]
                try:
                    result = future.result()
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    if result["status"] == "ok":
                        row = {
                            "job_schema_version": "self_iteration_job_v1",
                            "match_id": mid,
                            "evaluator_id": result["evaluator_id"],
                            "run_id": result["run_id"],
                            "prompt_hash": result["prompt_hash"],
                            "model": MODEL,
                            "created_at": now,
                            "evaluation": result["evaluation"],
                        }
                        done += 1
                        print(f"[{done + errors}/{len(missing_jobs)}] {mid} OK", flush=True)
                    else:
                        row = {
                            "job_schema_version": "self_iteration_job_v1",
                            "match_id": mid,
                            "evaluator_id": result["evaluator_id"],
                            "run_id": result["run_id"],
                            "prompt_hash": result["prompt_hash"],
                            "model": MODEL,
                            "created_at": now,
                            "error": result["error"],
                        }
                        errors += 1
                        print(f"[{done + errors}/{len(missing_jobs)}] {mid} ERROR: {result['error'][:80]}", flush=True)
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                except Exception as e:
                    errors += 1
                    print(f"[{done + errors}/{len(missing_jobs)}] {mid} EXCEPTION: {e}", flush=True)

    print(f"Done: {done} ok, {errors} errors -> {output_path}")


if __name__ == "__main__":
    main()
