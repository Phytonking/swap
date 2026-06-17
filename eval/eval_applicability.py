#!/usr/bin/env python3
"""Applicability evals — per intent x model: is this model a safe substitute?

Runs the seed corpus through the real `swap` router against each candidate
model and scores every case deterministically (label / json_subset / json_f1 /
checks — no LLM judge, no API key needed). Produces the EVAL.md verdict table:
SAFE (>=0.90) / RISKY (>=0.75) / UNSAFE (<0.75) per intent x model.

Local candidates come from the live Ollama. A frontier baseline runs over the
same corpus when ANTHROPIC_API_KEY is set (Anthropic's OpenAI-compatible
endpoint), answering both halves of the applicability question:
  - local models:    which intents are safe to delegate, on which checkpoint?
  - frontier models: does the frontier pass the golds? (corpus sanity + the
                     quality bar local candidates are measured against)

  python3 eval/eval_applicability.py                      # doctor-picked default model
  python3 eval/eval_applicability.py --all-local          # every installed chat model
  python3 eval/eval_applicability.py --models ollama/qwen3:8b,ollama/gemma3:4b
  python3 eval/eval_applicability.py --intent extract -v
  python3 eval/eval_applicability.py --ci --threshold 0.9 # gate on configured routes
"""
import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common
from common import run_swap, load_cases, case_input, score, verdict, pctl

FRONTIER_BACKEND = {
    "kind": "openai",
    "base_url": "https://api.anthropic.com/v1",
    "api_key": "env(ANTHROPIC_API_KEY)",
}
FRONTIER_DEFAULT = "anthropic/claude-sonnet-4-6"


def setup_home(frontier_model):
    """Isolated $HOME so eval runs never touch the user's real ~/.swap."""
    home = tempfile.mkdtemp(prefix="swap-eval-app-")
    code, out, err, _ = run_swap(["doctor", "--ensure"], env_overrides={"HOME": home})
    status = out.strip().splitlines()[-1] if out.strip() else "STATUS: ?"
    cfg_path = os.path.join(home, ".swap", "config.json")
    cfg = {}
    if os.path.exists(cfg_path):
        with open(cfg_path) as f:
            cfg = json.load(f)
    if frontier_model:
        backend = frontier_model.split("/", 1)[0]
        cfg.setdefault("backends", {})[backend] = FRONTIER_BACKEND
        with open(cfg_path, "w") as f:
            json.dump(cfg, f, indent=2)
    return home, code, status, cfg


def installed_chat_models(cfg):
    """Ask the live Ollama which chat models exist (reuses the router's logic)."""
    sys.path.insert(0, os.path.join(common.REPO_ROOT, "skills", "swap"))
    import swap as router
    models = router.ollama_models(router.ollama_base_url()) or []
    return [f"ollama/{m}" for m in models if router._is_chat_model(m)]


def routed_model(cfg, intent):
    """Which model would swap actually use for this intent (no overrides)?"""
    icfg = cfg.get("intents", {}).get(intent, {})
    if icfg.get("model"):
        return icfg["model"]
    tier = icfg.get("tier") or "cheap"
    tiers = cfg.get("tiers", {})
    return tiers.get(tier) or tiers.get("cheap") or tiers.get("local") or tiers.get("fast")


def model_class(mech, judg, code_q):
    """Capability band from per-level quality (None = level not evaluated).

    reasoning  — safe for judgment calls AND mechanical work (high-thinking)
    workhorse  — safe for mechanical work only (low-level grunt work)
    code-only  — safe only for mechanical code drafting (coder checkpoints)
    unfit      — do not delegate
    """
    if mech is not None and mech >= 0.90 and judg is not None and judg >= 0.90:
        return "reasoning"
    if mech is not None and mech >= 0.90:
        return "workhorse"
    if code_q is not None and code_q >= 0.90:
        return "code-only"
    return "unfit"


def saved_per_call(home):
    """Mean est_saved_vs_ref_usd per (intent, model) from the eval-home trace."""
    path = os.path.join(home, ".swap", "trace.jsonl")
    sums = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                k = (r.get("intent"), r.get("model"))
                d = sums.setdefault(k, [0.0, 0])
                d[0] += r.get("est_saved_vs_ref_usd", 0.0)
                d[1] += 1
    return {k: v[0] / v[1] for k, v in sums.items() if v[1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="",
                    help="comma-separated backend/model refs to evaluate")
    ap.add_argument("--all-local", action="store_true",
                    help="evaluate every installed Ollama chat model")
    ap.add_argument("--intent", default=None, help="run a single intent")
    ap.add_argument("--no-frontier", action="store_true",
                    help="skip the frontier baseline even if a key is set")
    ap.add_argument("--frontier-model", default=FRONTIER_DEFAULT)
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--timeout", type=int, default=240, help="per-call timeout (s)")
    ap.add_argument("--ci", action="store_true",
                    help="exit 1 if a configured route scores below --threshold")
    ap.add_argument("--threshold", type=float, default=0.90)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    frontier = None
    if not args.no_frontier:
        if os.environ.get("ANTHROPIC_API_KEY"):
            frontier = args.frontier_model
        else:
            print("frontier baseline: skipped (no ANTHROPIC_API_KEY in env)\n",
                  file=sys.stderr)

    home, code, status, cfg = setup_home(frontier)
    env = {"HOME": home}
    if code != 0 and not frontier:
        print(f"doctor not READY ({status}) and no frontier configured — nothing to "
              f"evaluate. Start Ollama or set ANTHROPIC_API_KEY.", file=sys.stderr)
        return 2

    candidates = [m for m in args.models.split(",") if m.strip()]
    if args.all_local:
        candidates += [m for m in installed_chat_models(cfg) if m not in candidates]
    if not candidates and code == 0:
        candidates = [routed_model(cfg, args.intent or "summarize")]
    if frontier:
        candidates.append(frontier)
    candidates = [c for c in candidates if c]
    if not candidates:
        print("no candidate models to evaluate", file=sys.stderr)
        return 2

    cases = load_cases(args.intent)
    if not cases:
        print(f"no cases found for intent {args.intent!r}", file=sys.stderr)
        return 2

    print(f"corpus: {len(cases)} case(s)   candidates: {', '.join(candidates)}")
    print(f"eval home: {home}\n")

    rows = []
    for model in candidates:  # model-major: avoid reloading checkpoints per case
        if not args.no_warmup:
            run_swap(["raw", "Reply with the single word: ok", "-m", model],
                     env_overrides=env, timeout=args.timeout)
        for case in cases:
            argv = [case["intent"], case["instruction"], "-m", model]
            code, out, err, ms = run_swap(argv, stdin_text=case_input(case),
                                          env_overrides=env, timeout=args.timeout)
            if code != 0:
                q, note = 0.0, f"swap exited {code}: {err.strip()[:160]}"
            else:
                q, note = score(case["gold"], out)
            rows.append({
                "intent": case["intent"], "model": model, "case": case["id"],
                "level": case.get("level", "mechanical"),
                "quality": round(q, 3), "mode": "deterministic",
                "gold_type": case["gold"]["type"], "note": note,
                "cand_latency_ms": ms, "exit": code,
                "output_head": out.strip()[:200],
            })
            mark = "ok " if q >= 0.9 else ("~  " if q >= 0.75 else "MISS")
            print(f"  [{mark}] {case['intent']:<10} {case['id']:<22} "
                  f"{model:<28} q={q:.2f}  {ms/1000:.1f}s"
                  + (f"  ({note})" if args.verbose or q < 0.9 else ""))

    # ---------------------------------------------------------- aggregate
    saved = saved_per_call(home)
    agg = {}
    for r in rows:
        agg.setdefault((r["intent"], r["model"]), []).append(r)

    out_dir = os.path.join(common.EVAL_DIR, "results",
                           time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "results.jsonl"), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    header = (f"\n{'intent':<11}{'model':<34}{'quality':>8}{'saved/call':>12}"
              f"{'p50':>8}{'p95':>8}  {'verdict':<8}{'n':>3}")
    lines = [header, "-" * len(header)]
    gate_failures = []
    for (intent, model), rs in sorted(agg.items()):
        qs = [r["quality"] for r in rs]
        ls = [r["cand_latency_ms"] for r in rs]
        quality = sum(qs) / len(qs)
        v = verdict(quality)
        routed = routed_model(cfg, intent) == model
        s = saved.get((intent, model))
        is_frontier = frontier and model == frontier
        s_str = "-" if is_frontier or s is None else f"${s:.4f}"
        lines.append(f"{intent:<11}{model + (' *' if routed else ''):<34}"
                     f"{quality:>8.2f}{s_str:>12}"
                     f"{pctl(ls, 50) / 1000:>7.1f}s{pctl(ls, 95) / 1000:>7.1f}s"
                     f"  {v:<8}{len(rs):>3}")
        if args.ci and routed and quality < args.threshold:
            gate_failures.append(f"{intent} on {model}: {quality:.2f} < {args.threshold}")

    table = "\n".join(lines)
    print(table)
    print("\n* = the model swap's config would actually route this intent to")

    # ------------------------------------------------- capability classes
    # The classification that matters for routing policy: which models are
    # high-thinking (reasoning) vs low-level work (workhorse) vs code-only.
    by_model = {}
    for r in rows:
        d = by_model.setdefault(r["model"], {"mechanical": [], "judgment": [], "code": []})
        d[r["level"]].append(r["quality"])
        if r["intent"] == "code":
            d["code"].append(r["quality"])

    def mean(xs):
        return sum(xs) / len(xs) if xs else None

    def fmt(x):
        return "-" if x is None else f"{x:.2f}"

    chdr = (f"\n{'model':<34}{'mechanical':>11}{'judgment':>10}  class")
    clines = [chdr, "-" * 66]
    classes = {}
    for m in candidates:
        if m not in by_model:
            continue
        d = by_model[m]
        mech, judg, code_q = mean(d["mechanical"]), mean(d["judgment"]), mean(d["code"])
        classes[m] = model_class(mech, judg, code_q)
        clines.append(f"{m:<34}{fmt(mech):>11}{fmt(judg):>10}  {classes[m]}")
    ctable = "\n".join(clines)
    print(ctable)

    guidance = ["\ndelegation guidance (>=0.90 per level on this machine):"]
    for level, need in (("mechanical", ("reasoning", "workhorse")),
                        ("judgment", ("reasoning",))):
        ok = [m for m in candidates if classes.get(m) in need]
        ok_str = ", ".join(ok) if ok else "(none — keep on the frontier agent)"
        guidance.append(f"  {level:<11}-> {ok_str}")
    code_ok = [m for m in candidates
               if (mean(by_model.get(m, {}).get("code", [])) or 0) >= 0.90]
    guidance.append(f"  {'code':<11}-> "
                    + (", ".join(code_ok) if code_ok
                       else "(none — keep on the frontier agent)"))
    print("\n".join(guidance))

    with open(os.path.join(out_dir, "summary.txt"), "w") as f:
        f.write(table + "\n" + ctable + "\n" + "\n".join(guidance) + "\n")
    print(f"results: {out_dir}")

    if gate_failures:
        print("\nCI GATE FAILED:\n  " + "\n  ".join(gate_failures), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
