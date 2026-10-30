"""Run every eval case at scores 1, 5 and 10 and check the results automatically.

Usage:
    python evals/run_evals.py                          # DeepSeek only (default)
    python evals/run_evals.py --providers deepseek,anthropic,openai
    python evals/run_evals.py --cases vague_help --scores 10
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from coach.config import band_for, load_config, target_for  # noqa: E402
from coach.engine import Coach, run_headless  # noqa: E402
from coach.lint import lint  # noqa: E402
from coach.logger import log_session  # noqa: E402
from coach.providers import CoachError, get_provider  # noqa: E402

SUCCESS_CRITERIA = re.compile(
    r"success criteria|criteria|success (means|looks like)|what (a )?good .{0,20}looks like|"
    r"(a|the) (great|good|successful|strong) (answer|response|result|output|reply|plan|letter|speech)",
    re.IGNORECASE)
MISSING_INFO = re.compile(
    r"^#+ .*(missing|information is missing)|"
    r"\b(if|when|where)\b[^.\n]{0,160}\b(missing|not (\w+ )?(provided|given|included|available|specified|reported|stated)|"
    r"isn't (provided|given|available)|unclear|unknown|insufficient|lacking|ambiguous|out of scope|outside (the )?scope)\b",
    re.IGNORECASE | re.MULTILINE)


def answer_from_case(case):
    def answer_fn(question):
        answer = case["answers"].get(str(question["category"]), "I don't know").strip()
        if answer.lower() == "skip":
            return "skipped", ""
        if answer.lower() == "i don't know":
            return "unknown", ""
        return "answered", answer
    return answer_fn


def run_one(provider_name, case, score):
    coach = Coach(get_provider(provider_name))
    started = time.time()
    record = {"provider": provider_name, "case": case["id"], "score": score, "target": case["target"]}
    try:
        qa, result = run_headless(coach, case["rough_prompt"], score, case["target"], answer_from_case(case))
        record.update(ok=True, qa=qa, result=result, error=None)
    except CoachError as exc:
        record.update(ok=False, qa=[], result=None, error=str(exc))
    record.update(seconds=round(time.time() - started, 1), usage=coach.usage_totals(),
                  validation_retries=sum(1 for c in coach.calls if not c["ok"]),
                  model=coach.provider.model)
    return record


def check(record, case):
    """Return a dict of check name -> (passed, detail)."""
    checks = {}
    band = band_for(record["score"])
    if not record["ok"]:
        checks["json_valid"] = (False, record["error"])
        return checks
    checks["json_valid"] = (True, f"{record['validation_retries']} validation retries")
    n = len(record["qa"])
    low = band["min_questions"] if (case["vague"] or record["score"] == 1) else 0
    checks["question_count"] = (low <= n <= band["max_questions"],
                                f"{n} asked (allowed {low}-{band['max_questions']})")
    found = lint(record["result"]["final_prompt"], target_for(case["target"])["reasoning"])
    banned = found["caps"] + found["pressure"] + found["step_by_step"]
    checks["no_banned_patterns"] = (not banned, ", ".join(banned) or "none")
    if record["score"] == 10:
        text = record["result"]["final_prompt"]
        sc = SUCCESS_CRITERIA.search(text)
        mi = MISSING_INFO.search(text)
        checks["has_success_criteria"] = (bool(sc), sc.group(0) if sc else "not found")
        checks["has_missing_info_rule"] = (bool(mi), mi.group(0)[:80] if mi else "not found")
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--providers", default="deepseek")
    parser.add_argument("--cases", default="", help="comma-separated case ids (default: all)")
    parser.add_argument("--scores", default="1,5,10")
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    cases = [json.loads(line) for line in (ROOT / "evals" / "cases.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in cases if c["id"] in wanted]
    scores = [int(s) for s in args.scores.split(",")]
    config = load_config()

    providers = []
    for name in args.providers.split(","):
        key_env = config["providers"][name]["api_key_env"]
        if os.getenv(key_env, "").strip():
            providers.append(name)
        else:
            print(f"Skipping {name}: {key_env} is not set in .env")
    if not providers:
        sys.exit("No provider with an API key to run.")

    jobs = [(p, c, s) for p in providers for c in cases for s in scores]
    print(f"Running {len(jobs)} sessions ({len(cases)} cases x scores {scores} x {providers})...\n")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        records = list(pool.map(lambda job: run_one(*job), jobs))

    by_case = {c["id"]: c for c in cases}
    results_path = ROOT / "evals" / "results.jsonl"
    results_path.write_text("", encoding="utf-8")
    total = failed = 0
    rows = []
    for r in records:
        r["checks"] = {k: {"pass": v[0], "detail": v[1]} for k, v in check(r, by_case[r["case"]]).items()}
        log_session({**r, "source": "eval"}, results_path)
        for name, c in r["checks"].items():
            total += 1
            failed += not c["pass"]
        rows.append(r)

    # Score 10 must be longer than score 5 for the same case and provider.
    length_rows = []
    for p in providers:
        for c in cases:
            got = {r["score"]: r for r in rows if r["provider"] == p and r["case"] == c["id"] and r["ok"]}
            if 5 in got and 10 in got:
                l5, l10 = (len(got[s]["result"]["final_prompt"]) for s in (5, 10))
                ok = l10 > l5
                total += 1
                failed += not ok
                length_rows.append((p, c["id"], l5, l10, ok))

    print(f"{'provider':9} {'case':20} {'sc':>2} {'qs':>3} {'chars':>6} {'in_tok':>7} {'out_tok':>7} "
          f"{'secs':>5}  checks")
    for r in sorted(rows, key=lambda r: (r["provider"], r["case"], r["score"])):
        chars = len(r["result"]["final_prompt"]) if r["ok"] else 0
        marks = " ".join(f"{'OK ' if c['pass'] else 'FAIL '}{k}" + ("" if c["pass"] else f" [{c['detail']}]")
                         for k, c in r["checks"].items())
        print(f"{r['provider']:9} {r['case']:20} {r['score']:>2} {len(r['qa']):>3} {chars:>6} "
              f"{r['usage']['input_tokens']:>7} {r['usage']['output_tokens']:>7} {r['seconds']:>5}  {marks}")
    if length_rows:
        print("\nScore 10 longer than score 5:")
        for p, cid, l5, l10, ok in length_rows:
            print(f"  {'OK  ' if ok else 'FAIL'} {p:9} {cid:20} {l5:>6} -> {l10:>6} chars")
    in_tok = sum(r["usage"]["input_tokens"] for r in rows)
    out_tok = sum(r["usage"]["output_tokens"] for r in rows)
    print(f"\n{total - failed}/{total} checks passed. Tokens: {in_tok:,} in / {out_tok:,} out. "
          f"Details: {results_path.relative_to(ROOT)}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
