#!/usr/bin/env python3
"""Run evaluator B on b-003 jobs using MIMO API."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

MIMO_BASE_URL = os.environ.get("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1")
MIMO_API_KEY = os.environ.get("MIMO_API_KEY", "")
MODEL = "mimo-v2.5-pro"


def call_llm(prompt: str, max_retries: int = 3) -> dict:
    """Call MIMO API with strict JSON output requirement."""
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

            # Parse JSON
            try:
                result = json.loads(content)
            except json.JSONDecodeError:
                # Try extracting JSON from markdown
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


def main():
    jobs_path = Path("data/self_iteration/runs/b-003/llm_jobs.jsonl")
    output_path = Path("data/self_iteration/runs/b-003/llm_results.jsonl")

    jobs = []
    with open(jobs_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                jobs.append(json.loads(line))

    # Check for existing results
    existing_results = {}
    if output_path.exists():
        with open(output_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    existing_results[r["match_id"]] = r

    print(f"Total jobs: {len(jobs)}")
    print(f"Existing results: {len(existing_results)}")

    with open(output_path, "a", encoding="utf-8") as f:
        for i, job in enumerate(jobs):
            match_id = job["match_id"]
            if match_id in existing_results:
                print(f"[{i+1}/{len(jobs)}] Skipping {match_id} (already done)")
                continue

            print(f"[{i+1}/{len(jobs)}] Evaluating {match_id}...", end=" ", flush=True)
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
                f.write(json.dumps(output_row, ensure_ascii=False) + "\n")
                f.flush()
                print("OK")
            except Exception as e:
                print(f"ERROR: {e}")
                # Write error row
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
                f.write(json.dumps(error_row, ensure_ascii=False) + "\n")
                f.flush()

            time.sleep(0.5)  # Rate limiting

    print(f"Done. Results written to {output_path}")


if __name__ == "__main__":
    main()
