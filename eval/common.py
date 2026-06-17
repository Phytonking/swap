"""Shared helpers for swap's eval suites. Python stdlib only, like the router.

Gold types (deterministic — no frontier or API key needed to score):
  label        exact label match (classify); reads {"label": ...} or bare text
  json_subset  every gold item must appear in the candidate JSON
  json_f1      precision/recall over gold items (penalizes hallucinated items)
  checks       composite contains_all / regex_all / forbid (summarize, code)
"""
import json
import os
import re
import subprocess
import sys
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SWAP_PY = os.path.join(REPO_ROOT, "skills", "swap", "swap.py")
EVAL_DIR = os.path.join(REPO_ROOT, "eval")


# ---------------------------------------------------------------- running swap

def run_swap(argv, stdin_text="", env_overrides=None, timeout=240):
    """Run swap.py in a subprocess. Returns (exit_code, stdout, stderr, latency_ms)."""
    env = dict(os.environ)
    env.update(env_overrides or {})
    t0 = time.time()
    try:
        proc = subprocess.run(
            [sys.executable, SWAP_PY] + argv,
            input=stdin_text, capture_output=True, text=True,
            timeout=timeout, env=env,
        )
        code, out, err = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired:
        code, out, err = -1, "", f"timeout after {timeout}s"
    return code, out, err, int((time.time() - t0) * 1000)


# ---------------------------------------------------------------- scorers

def _norm(v):
    return str(v).strip().lower()


def _parse_json(text):
    try:
        return json.loads(text.strip()), None
    except Exception as e:
        return None, f"invalid JSON: {e}"


def _as_list(data):
    """Tolerate a bare list, a single object, or one wrapper key holding a list."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
        return [data]
    return [data]


def _item_matches(gold_item, cand_item):
    """Every key in the gold item must be present and loosely equal in cand."""
    if not isinstance(gold_item, dict) or not isinstance(cand_item, dict):
        return _norm(gold_item) == _norm(cand_item)
    return all(k in cand_item and _norm(cand_item[k]) == _norm(v)
               for k, v in gold_item.items())


def score_label(gold_value, output):
    data, err = _parse_json(output)
    if err:
        got = _norm(output)  # tolerate a bare label outside JSON
    elif isinstance(data, dict):
        got = _norm(data.get("label", ""))
    else:
        got = _norm(data)
    want = _norm(gold_value)
    return (1.0 if got == want else 0.0), f"want={want!r} got={got!r}"


def score_json_subset(gold_value, output):
    data, err = _parse_json(output)
    if err:
        return 0.0, err
    cand = _as_list(data)
    gold = gold_value if isinstance(gold_value, list) else [gold_value]
    hit = sum(1 for g in gold if any(_item_matches(g, c) for c in cand))
    return hit / len(gold), f"{hit}/{len(gold)} gold items found"


def score_json_f1(gold_value, output):
    data, err = _parse_json(output)
    if err:
        return 0.0, err
    cand = _as_list(data)
    gold = gold_value if isinstance(gold_value, list) else [gold_value]
    tp = sum(1 for g in gold if any(_item_matches(g, c) for c in cand))
    ctp = sum(1 for c in cand if any(_item_matches(g, c) for g in gold))
    prec = ctp / len(cand) if cand else 0.0
    rec = tp / len(gold) if gold else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return f1, f"precision={prec:.2f} recall={rec:.2f}"


def score_checks(gold_value, output):
    low = output.lower()
    notes, passed, total = [], 0, 0
    for needle in gold_value.get("contains_all", []):
        total += 1
        if needle.lower() in low:
            passed += 1
        else:
            notes.append(f"missing {needle!r}")
    for pat in gold_value.get("regex_all", []):
        total += 1
        if re.search(pat, output, re.IGNORECASE | re.MULTILINE):
            passed += 1
        else:
            notes.append(f"no match /{pat}/")
    for needle in gold_value.get("forbid", []):
        if needle.lower() in low:
            return 0.0, f"forbidden {needle!r} present"
    if not total:
        return 0.0, "empty checks"
    return passed / total, "; ".join(notes) or "all checks passed"


SCORERS = {
    "label": score_label,
    "json_subset": score_json_subset,
    "json_f1": score_json_f1,
    "checks": score_checks,
}


def score(gold, output):
    return SCORERS[gold["type"]](gold["value"], output)


# ---------------------------------------------------------------- verdicts

def verdict(quality):
    if quality >= 0.90:
        return "SAFE"
    if quality >= 0.75:
        return "RISKY"
    return "UNSAFE"


def pctl(values, p):
    if not values:
        return 0
    s = sorted(values)
    i = min(len(s) - 1, max(0, int(round(p / 100.0 * (len(s) - 1)))))
    return s[i]


# ---------------------------------------------------------------- corpus

def load_cases(only_intent=None):
    cases = []
    cases_dir = os.path.join(EVAL_DIR, "cases")
    for root, _, files in os.walk(cases_dir):
        for fn in sorted(files):
            if not fn.endswith(".json"):
                continue
            with open(os.path.join(root, fn)) as f:
                c = json.load(f)
            if only_intent and c["intent"] != only_intent:
                continue
            cases.append(c)
    return sorted(cases, key=lambda c: (c["intent"], c["id"]))


def case_input(case):
    if not case.get("input"):
        return ""
    with open(os.path.join(EVAL_DIR, case["input"])) as f:
        return f.read()
