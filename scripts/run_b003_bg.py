#!/usr/bin/env python3
"""Run evaluator B on b-003 jobs using MIMO API — background batch runner."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

MIMO_BASE_URL = os.environ.get("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
MODEL = "mimo-v2.5-pro"
BATCH_SIZE = 5  # Small batches to avoid timeout


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
                timeout=180,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]

            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                if "```json" in content:
                    json_part = content.split("```json")[1].split("```")[0].strip()
                    result = json.loads(json_part)
                elif "```" in content:
                    json_part = content.split("```")[1].split("```")[0].strip()
                    result = json.loads(json_part)
                else:
                    raise
            return result
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)
    raise RuntimeError("Max retries exceeded")


def process_batch(batch_num: int, jobs: list[dict], output_dir: Path):
    output_path = output_dir / f"batch_{batch_num:02d}_results.jsonl"
    print(f"[Batch {batch_num}] Starting {len(jobs)} jobs -> {output_path}")

    for i, job in enumerate(jobs):
        match_id = job["match_id"]
        print(f"[Batch {batch_num}] [{i+1}/{len(jobs)}] {match_id}...", flush=True)
        try:
            result = call_llm(job["prompt"])
            output_row = {
                "job_schema_version": "self_iteration_job_v1",
                "match_id": match_id,
                "evaluator_id": job["evaluator_id"],
                "run_id": job["run_id"],
                "prompt_hash": job["prompt_hash"],
                "model": MODEL,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "evaluation": result,
            }
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(output_row, ensure_ascii=False) + "\n")
            print(f"[Batch {batch_num}] [{i+1}/{len(jobs)}] {match_id} OK")
        except Exception as e:
            print(f"[Batch {batch_num}] [{i+1}/{len(jobs)}] {match_id} ERROR: {e}")
            error_row = {
                "job_schema_version": "self_iteration_job_v1",
                "match_id": match_id,
                "evaluator_id": job["evaluator_id"],
                "run_id": job["run_id"],
                "prompt_hash": job["prompt_hash"],
                "model": MODEL,
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "error": str(e),
            }
            with open(output_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(error_row, ensure_ascii=False) + "\n")
        time.sleep(0.5)

    print(f"[Batch {batch_num}] Done")


def main():
    jobs_path = Path("data/self_iteration/runs/b-003/llm_jobs.jsonl")
    output_dir = Path("data/self_iteration/runs/b-003")

    jobs = []
    with open(jobs_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                jobs.append(json.loads(line))

    # Check existing
    existing = set()
    for f in output_dir.glob("batch_*_results.jsonl"):
        with open(f, encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    r = json.loads(line)
                    existing.add(r.get("match_id"))

    remaining = [j for j in jobs if j["match_id"] not in existing]
    print(f"Total: {len(jobs)}, Existing: {len(existing)}, Remaining: {len(remaining)}")

    if not remaining:
        print("All done!")
        return

    # Process in small batches
    for batch_start in range(0, len(remaining), BATCH_SIZE):
        batch_jobs = remaining[batch_start:batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        process_batch(batch_num, batch_jobs, output_dir)

    print("All batches complete")


if __name__ == "__main__":
    main()
