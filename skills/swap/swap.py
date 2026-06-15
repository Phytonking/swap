#!/usr/bin/env python3
"""swap — route mechanical agent sub-tasks to cheap local/cloud models.

Zero-dependency (Python stdlib only) so it runs on whatever Python is already
on the machine. Context comes on stdin; the instruction is the prompt arg.

  swap <intent> [--tier T] [-m MODEL] [--json] "<instruction>"   # context on stdin
  swap "<raw prompt>"                                            # no intent = raw
  swap doctor [--ensure]                                         # detect backends, write config
  swap report [--day|--week]                                     # cost / savings from trace

Intents: summarize | extract | classify | code
Config:  ~/.swap/config.json   Trace: ~/.swap/trace.jsonl
"""
import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~/.swap")
CONFIG_PATH = os.path.join(HOME, "config.json")
TRACE_PATH = os.path.join(HOME, "trace.jsonl")
BIN_PATH = os.path.join(HOME, "bin", "swap")

INTENTS = {
    "summarize": {
        "tier": "cheap",
        "format": "text",
        "system": "You are a precise summarizer. Given the content on stdin and the "
                  "user's instruction, produce a concise, factual summary. Preserve "
                  "key facts, names, numbers, file paths and line numbers. Do NOT "
                  "invent anything not present in the content.",
    },
    "extract": {
        "tier": "cheap",
        "format": "json",
        "system": "You extract structured data from the content on stdin per the "
                  "instruction. Output ONLY valid JSON — no prose, no markdown fences. "
                  "If nothing matches, output an empty array or object.",
    },
    "classify": {
        "tier": "cheap",
        "format": "json",
        "system": "You classify the content on stdin per the instruction. Output ONLY "
                  'a JSON object: {"label": <string>, "confidence": <0..1>}. No prose.',
    },
    "code": {
        "tier": "local",
        "format": "text",
        "system": "You are a focused coding assistant. Produce only the requested code "
                  "or unified diff with minimal explanation. Match the surrounding style.",
    },
}

# Reference (frontier) price used only to estimate savings. Sonnet-class $/Mtok.
REF_IN_PER_M = 3.0
REF_OUT_PER_M = 15.0

# OpenAI-compatible cloud backends. All speak /chat/completions, so each is a
# config entry, not new code — useful as cheap candidates AND as the eval
# reference/judge (e.g. Gemini's free tier). base_url + the env var holding key.
CLOUD_PRESETS = {
    "gemini":     ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY"),
    "openai":     ("https://api.openai.com/v1", "OPENAI_API_KEY"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY"),
    "groq":       ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
    "deepinfra":  ("https://api.deepinfra.com/v1/openai", "DEEPINFRA_API_KEY"),
    "together":   ("https://api.together.xyz/v1", "TOGETHER_API_KEY"),
    "fireworks":  ("https://api.fireworks.ai/inference/v1", "FIREWORKS_API_KEY"),
    "mistral":    ("https://api.mistral.ai/v1", "MISTRAL_API_KEY"),
}


# ---------------------------------------------------------------- config

def default_config():
    return {
        "backends": {},          # filled by doctor; cloud stays blank by default
        "tiers": {},             # cheap/fast/local -> "backend/model"
        "intents": {k: {"tier": v["tier"], "format": v["format"]} for k, v in INTENTS.items()},
        "reference": None,       # frontier oracle, used only by eval; blank by default
    }


def load_config():
    if not os.path.exists(CONFIG_PATH):
        return None
    try:
        with open(CONFIG_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def save_config(cfg):
    os.makedirs(HOME, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    # config may hold raw API keys -> keep it private (like ~/.aws/credentials).
    try:
        os.chmod(HOME, 0o700)
        os.chmod(CONFIG_PATH, 0o600)
    except OSError:
        pass


def backend_key_missing(cfg, backend_name):
    """True if this backend needs a key (openai-kind) and none resolves yet."""
    b = cfg.get("backends", {}).get(backend_name, {})
    if b.get("kind") != "openai":
        return False
    return not _resolve_env(b.get("api_key", ""))


def needs_key_signal(backend_name, key_env=None):
    """Structured, machine-readable line the agent acts on: ask the user for a
    key for THIS backend, then store it. Printed to stderr; never the key."""
    env = key_env
    if not env and backend_name in CLOUD_PRESETS:
        env = CLOUD_PRESETS[backend_name][1]
    msg = {
        "status": "NEEDS_KEY",
        "backend": backend_name,
        "env": env,
        "prompt": (f"swap needs an API key for '{backend_name}'. Ask the user for "
                   f"their {backend_name} API key, then have them run:  "
                   f"swap set-key {backend_name}   (paste key when prompted). "
                   f"Do not ask the user to paste the key into the chat."),
    }
    print("NEED_KEY: " + json.dumps(msg), file=sys.stderr)


# ---------------------------------------------------------------- http

def _post_json(url, payload, headers=None, timeout=300):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _get_json(url, timeout=5):
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


# ---------------------------------------------------------------- backends

def ollama_base_url():
    """Honor Ollama's own OLLAMA_HOST convention; default to localhost."""
    host = os.environ.get("OLLAMA_HOST", "").strip() or "http://localhost:11434"
    if "://" not in host:
        host = "http://" + host
    return host.rstrip("/")


def ollama_models(base_url):
    """Return list of installed ollama model names, or None if unreachable."""
    try:
        data = _get_json(base_url.rstrip("/") + "/api/tags", timeout=4)
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return None


def ollama_ctx_map(base_url):
    """{model_name: context_length} for models that advertise one. Best-effort."""
    out = {}
    try:
        data = _get_json(base_url.rstrip("/") + "/api/tags", timeout=4)
    except Exception:
        return out
    for m in data.get("models", []):
        ctx = (m.get("details") or {}).get("context_length")
        if isinstance(ctx, int) and ctx > 0:
            out[m["name"]] = ctx
    return out


def call_model(cfg, model_ref, system, user):
    """model_ref = 'backend/model'. Returns (text, in_tok, out_tok)."""
    backend_name, _, model = model_ref.partition("/")
    backend = cfg["backends"].get(backend_name)
    if not backend:
        raise SwapError(f"backend '{backend_name}' not configured (model_ref={model_ref})")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]

    # Mechanical sub-tasks want repeatable output, not creativity.
    if backend["kind"] == "ollama":
        url = backend["base_url"].rstrip("/") + "/api/chat"
        payload = {"model": model, "messages": messages, "stream": False, "think": False,
                   "options": {"temperature": 0}}
        try:
            data = _post_json(url, payload)
        except urllib.error.URLError as e:
            raise SwapError(f"ollama unreachable at {url}: {e}")
        text = data.get("message", {}).get("content", "")
    elif backend["kind"] == "openai":
        url = backend["base_url"].rstrip("/") + "/chat/completions"
        key = _resolve_env(backend.get("api_key", ""))
        if not key:
            raise SwapError(f"backend '{backend_name}' has no API key set")
        payload = {"model": model, "messages": messages, "stream": False, "temperature": 0}
        try:
            data = _post_json(url, payload, headers={"Authorization": f"Bearer {key}"})
        except urllib.error.URLError as e:
            raise SwapError(f"cloud backend unreachable at {url}: {e}")
        text = data["choices"][0]["message"]["content"]
    else:
        raise SwapError(f"unknown backend kind: {backend['kind']}")

    text = strip_think(text)
    return text, est_tok(system + user), est_tok(text)


def _resolve_env(val):
    m = re.match(r"env\((\w+)\)", val or "")
    if m:
        return os.environ.get(m.group(1), "")
    return val


# ---------------------------------------------------------------- helpers

class SwapError(Exception):
    pass


def est_tok(s):
    return max(1, len(s) // 4)


# Reserve headroom for the instruction + the model's own output.
CTX_RESERVE_TOK = 1500
DEFAULT_CTX_TOK = 8192          # assume an 8k window when the model won't say


def model_ctx_tokens(cfg, model_ref):
    backend_name, _, model = model_ref.partition("/")
    backend = cfg.get("backends", {}).get(backend_name, {})
    ctx = (backend.get("models") or {}).get(model)
    return ctx if isinstance(ctx, int) and ctx > 0 else DEFAULT_CTX_TOK


def clip_to_budget(text, budget_chars):
    """Middle-truncate oversize context, keeping head + tail (the signal in a
    log usually lives at both ends). Returns (clipped, was_clipped)."""
    if len(text) <= budget_chars or budget_chars <= 0:
        return text, False
    head = budget_chars * 3 // 5
    tail = budget_chars - head
    omitted = len(text) - head - tail
    marker = f"\n\n... [swap omitted {omitted} chars of context] ...\n\n"
    return text[:head] + marker + text[-tail:], True


def strip_think(text):
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL).strip()


def strip_fences(text):
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n", "", t)
        t = re.sub(r"\n```$", "", t)
    return t.strip()


def _scan_json_blob(text):
    """Return the first balanced {...} or [...] span, ignoring brackets in
    strings. Cheap models often wrap JSON in prose ('Here is the JSON: [...]');
    this rescues the payload without a model round-trip."""
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        return None
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def coerce_json(text):
    """(canonical_json_str, ok). Tolerate fences and surrounding prose."""
    t = strip_fences(text)
    try:
        return json.dumps(json.loads(t)), True
    except Exception:
        pass
    blob = _scan_json_blob(t)
    if blob is not None:
        try:
            return json.dumps(json.loads(blob)), True
        except Exception:
            pass
    return t, False


def trace(intent, model_ref, in_tok, out_tok, latency_ms):
    saved = in_tok / 1e6 * REF_IN_PER_M + out_tok / 1e6 * REF_OUT_PER_M
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "intent": intent,
        "model": model_ref,
        "in_tok": in_tok,
        "out_tok": out_tok,
        "latency_ms": latency_ms,
        "est_cost_usd": 0.0,
        "est_saved_vs_ref_usd": round(saved, 6),
    }
    os.makedirs(HOME, exist_ok=True)
    line = json.dumps(row) + "\n"
    with open(TRACE_PATH, "a") as f:
        try:                                  # serialize parallel agent fan-out
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        except Exception:
            pass                              # non-POSIX: best-effort append
        f.write(line)


def resolve_model(cfg, intent, tier_override, model_override):
    """Priority: -m flag > --tier flag > intent-level model > intent tier > cheap."""
    if model_override:
        return model_override
    icfg = cfg.get("intents", {}).get(intent or "", {})
    if not tier_override and icfg.get("model"):
        return icfg["model"]
    tier = tier_override or icfg.get("tier") or "cheap"
    model = cfg.get("tiers", {}).get(tier)
    if not model:
        # fall back to any configured tier
        for t in ("cheap", "local", "fast"):
            if cfg.get("tiers", {}).get(t):
                return cfg["tiers"][t]
        raise SwapError("no model configured — run `swap doctor --ensure`")
    return model


# ---------------------------------------------------------------- doctor

def install_shim():
    """Copy this script to ~/.swap/bin/swap so harnesses call a stable path."""
    os.makedirs(os.path.dirname(BIN_PATH), exist_ok=True)
    src = os.path.abspath(__file__)
    try:
        with open(src) as a, open(BIN_PATH, "w") as b:
            b.write(a.read())
        os.chmod(BIN_PATH, 0o755)
    except Exception:
        pass


# Auto-prioritization: family preference first, then parameter size (bigger
# is better among the cheap models the user chose to pull), then name for
# determinism. Embedding/rerank checkpoints are never usable as chat defaults,
# and coder checkpoints are reserved for the `code` intent unless they are the
# only chat model available.
FAMILY_PRIORITY = ("qwen3", "qwen", "llama3", "llama", "mistral", "deepseek", "gemma", "phi")
NON_CHAT_PATTERNS = ("embed", "rerank", "bge-", "minilm", "clip")
CODER_PATTERNS = ("coder", "code")


def _is_chat_model(name):
    n = name.lower()
    return not any(p in n for p in NON_CHAT_PATTERNS)


def _is_coder_model(name):
    n = name.lower()
    return any(p in n for p in CODER_PATTERNS)


def _param_size_b(name):
    m = re.search(r"(\d+(?:\.\d+)?)b(?![a-z0-9])", name.lower())
    return float(m.group(1)) if m else 0.0


def _family_rank(name):
    n = name.lower()
    for i, fam in enumerate(FAMILY_PRIORITY):
        if fam in n:
            return i
    return len(FAMILY_PRIORITY)


def _rank_models(models):
    return sorted(models, key=lambda m: (_family_rank(m), -_param_size_b(m), m))


def pick_default_model(models):
    """General default: best-ranked chat model, preferring non-coder checkpoints."""
    chat = [m for m in models if _is_chat_model(m)]
    if not chat:
        return None
    general = [m for m in chat if not _is_coder_model(m)] or chat
    return _rank_models(general)[0]


def pick_code_model(models):
    """`code` intent: best-ranked coder checkpoint, or None to use the default."""
    coders = [m for m in models if _is_chat_model(m) and _is_coder_model(m)]
    return _rank_models(coders)[0] if coders else None


def cmd_doctor(args):
    ensure = args.ensure
    cfg = load_config() or default_config()

    ollama_base = ollama_base_url()
    models = ollama_models(ollama_base)

    lines = []
    status = "READY"
    nxt = None

    if models is None:
        status = "NEEDS_BACKEND"
        lines.append(f"Ollama: not reachable at {ollama_base}")
        nxt = ("No local model and no cloud backend configured. To set up local "
               "inference: `brew install ollama && ollama serve & ollama pull qwen3:8b` "
               "(or pull qwen3:32b if you have the VRAM).")
    else:
        ctx_map = ollama_ctx_map(ollama_base)
        cfg["backends"]["ollama"] = {"kind": "ollama", "base_url": ollama_base,
                                     "models": ctx_map}
        lines.append(f"Ollama: reachable, {len(models)} model(s): {', '.join(models) or '(none)'}")
        default = pick_default_model(models)
        if not default:
            status = "NEEDS_MODEL"
            nxt = ("Ollama is running but has no usable chat model. "
                   "Run: `ollama pull qwen3:8b`")
        else:
            ref = f"ollama/{default}"
            cfg.setdefault("tiers", {})
            for t in ("cheap", "fast", "local"):
                cfg["tiers"].setdefault(t, ref)
            lines.append(f"Default model -> {ref}")
            coder = pick_code_model(models)
            if coder:
                code_cfg = cfg.setdefault("intents", {}).setdefault(
                    "code", {"tier": "local", "format": "text"})
                code_cfg.setdefault("model", f"ollama/{coder}")
                lines.append(f"Code intent -> {code_cfg['model']}")

    # Cloud stays blank by default. Hint (one command) if a known key is in env.
    for name, (_, env_key) in CLOUD_PRESETS.items():
        if os.environ.get(env_key):
            lines.append(f"Found {env_key} — cloud OFF by default; enable with: "
                         f"`swap add-backend {name} --model <model>` "
                         f"(add --reference to use it as the eval judge).")

    if ensure:
        save_config(cfg)
        install_shim()
        lines.append(f"Config written: {CONFIG_PATH}")
        lines.append(f"Stable entrypoint: {BIN_PATH}")

    print("\n".join(lines), file=sys.stderr)
    if nxt:
        print("\nNEXT: " + nxt, file=sys.stderr)
    print(f"STATUS: {status}")
    return {"READY": 0, "NEEDS_MODEL": 3, "NEEDS_BACKEND": 4}[status]


# ---------------------------------------------------------------- add-backend

def cmd_add_backend(args):
    cfg = load_config() or default_config()
    name = args.name
    base_url = args.base_url
    key_env = args.key_env
    if name in CLOUD_PRESETS:
        preset_url, preset_env = CLOUD_PRESETS[name]
        base_url = base_url or preset_url
        key_env = key_env or preset_env
    if not base_url:
        print(json.dumps({"error": f"unknown backend '{name}': pass --base-url "
                          f"and --key-env, or use one of {list(CLOUD_PRESETS)}"}),
              file=sys.stderr)
        return 2
    key_env = key_env or (name.upper() + "_API_KEY")

    cfg.setdefault("backends", {})[name] = {
        "kind": "openai", "base_url": base_url, "api_key": f"env({key_env})",
    }
    lines = [f"Backend '{name}' -> {base_url} (key from ${key_env})"]
    if not os.environ.get(key_env):
        lines.append(f"WARNING: ${key_env} is not set in this environment yet.")
    if args.model:
        ref = f"{name}/{args.model}"
        tier = args.tier or "fast"
        cfg.setdefault("tiers", {})[tier] = ref
        lines.append(f"Tier '{tier}' -> {ref}")
        if args.reference:
            cfg["reference"] = {"model": ref, "api_key": f"env({key_env})"}
            lines.append(f"Eval reference/judge -> {ref}")
    elif args.reference:
        lines.append("--reference needs --model (which model judges).")

    save_config(cfg)
    print("\n".join(lines), file=sys.stderr)
    # If the key can't be resolved yet, tell the agent to collect it.
    if not _resolve_env(f"env({key_env})"):
        needs_key_signal(name, key_env)
        print("STATUS: NEEDS_KEY")
        return 5
    print("STATUS: OK")
    return 0


# ---------------------------------------------------------------- set-key

def cmd_set_key(args):
    """Store an API key for a backend so swap uses it automatically from now on.
    Key comes from stdin (piped) or a hidden prompt — never from argv, never
    echoed, never traced."""
    cfg = load_config() or default_config()
    name = args.backend
    cfg.setdefault("backends", {})
    if name not in cfg["backends"]:
        if name in CLOUD_PRESETS:
            url, _ = CLOUD_PRESETS[name]
            cfg["backends"][name] = {"kind": "openai", "base_url": url, "api_key": ""}
        else:
            print(json.dumps({"error": f"no backend '{name}'. Run "
                              f"`swap add-backend {name} --model <model>` first, "
                              f"or use a preset: {list(CLOUD_PRESETS)}"}),
                  file=sys.stderr)
            return 2

    if sys.stdin.isatty():
        import getpass
        key = getpass.getpass(f"Paste API key for '{name}' (hidden): ").strip()
    else:
        key = sys.stdin.read().strip()
    if not key:
        print(json.dumps({"error": "no key provided on stdin"}), file=sys.stderr)
        return 2

    cfg["backends"][name]["api_key"] = key   # stored literal; file chmod 600
    save_config(cfg)
    masked = key[:3] + "…" + key[-2:] if len(key) > 6 else "…"
    print(f"Stored key for '{name}' ({masked}) in {CONFIG_PATH} (mode 600). "
          f"swap will use it automatically.", file=sys.stderr)
    print("STATUS: OK")
    return 0


# ---------------------------------------------------------------- report

def cmd_report(args):
    if not os.path.exists(TRACE_PATH):
        print("No calls logged yet.", file=sys.stderr)
        return 0
    rows = []
    with open(TRACE_PATH) as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    if not rows:
        print("No calls logged yet.", file=sys.stderr)
        return 0
    total_saved = sum(r.get("est_saved_vs_ref_usd", 0) for r in rows)
    by_intent = {}
    for r in rows:
        i = r.get("intent", "?")
        d = by_intent.setdefault(i, {"n": 0, "saved": 0.0})
        d["n"] += 1
        d["saved"] += r.get("est_saved_vs_ref_usd", 0)
    print(f"swap report — {len(rows)} call(s)")
    print(f"{'intent':<12}{'calls':>7}{'saved vs frontier':>22}")
    for i, d in sorted(by_intent.items(), key=lambda kv: -kv[1]["saved"]):
        print(f"{i:<12}{d['n']:>7}{('$%.4f' % d['saved']):>22}")
    print(f"{'TOTAL':<12}{len(rows):>7}{('$%.4f' % total_saved):>22}")
    print(f"\nYou saved ~${total_saved:.4f} routing to cheap models instead of the frontier.")
    return 0


# ---------------------------------------------------------------- run intent

def cmd_run(args):
    cfg = load_config()
    if cfg is None:
        print("swap is not set up yet. Run: swap doctor --ensure", file=sys.stderr)
        return 4

    intent = args.intent
    spec = INTENTS.get(intent)
    system = spec["system"] if spec else "You are a helpful, concise assistant."
    fmt = (spec["format"] if spec else "text")
    if args.json:
        fmt = "json"

    stdin_data = "" if sys.stdin.isatty() else sys.stdin.read()

    try:
        model_ref = resolve_model(cfg, intent, args.tier, args.model)
    except SwapError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1

    # If this route is a cloud backend whose key isn't set, ask for it (don't fail).
    backend_name = model_ref.partition("/")[0]
    if backend_key_missing(cfg, backend_name):
        key_env = (cfg["backends"][backend_name].get("api_key", "") or "")
        m = re.match(r"env\((\w+)\)", key_env)
        needs_key_signal(backend_name, m.group(1) if m else None)
        print("STATUS: NEEDS_KEY", file=sys.stderr)
        return 5

    # Fit the context to the model's window so a 2000-line log can't blow it.
    budget_chars = (model_ctx_tokens(cfg, model_ref) - CTX_RESERVE_TOK) * 4
    stdin_data, clipped = clip_to_budget(stdin_data, budget_chars)
    if clipped:
        print(f"swap: context exceeded {model_ref} window — middle-truncated to fit.",
              file=sys.stderr)

    user = args.instruction
    if stdin_data.strip():
        user = f"{args.instruction}\n\n--- CONTENT ---\n{stdin_data}"

    try:
        t0 = time.time()
        text, in_tok, out_tok = call_model(cfg, model_ref, system, user)
        if fmt == "json":
            clean, ok = coerce_json(text)
            if not ok:                        # one stricter retry before giving up
                strict = system + ("\n\nReturn ONLY valid JSON. No prose, no "
                                   "explanation, no markdown fences.")
                text2, i2, o2 = call_model(cfg, model_ref, strict, user)
                clean2, ok2 = coerce_json(text2)
                if ok2:
                    clean, out_tok = clean2, o2
            text = clean
        latency_ms = int((time.time() - t0) * 1000)
    except SwapError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        return 1

    trace(intent or "raw", model_ref, in_tok, out_tok, latency_ms)
    print(text)
    return 0


# ---------------------------------------------------------------- cli

def main():
    p = argparse.ArgumentParser(prog="swap", add_help=True)
    sub = p.add_subparsers(dest="cmd")

    pd = sub.add_parser("doctor")
    pd.add_argument("--ensure", action="store_true")

    pr = sub.add_parser("report")
    pr.add_argument("--day", action="store_true")
    pr.add_argument("--week", action="store_true")

    pa = sub.add_parser("add-backend")
    pa.add_argument("name", help="preset (gemini/openrouter/groq/...) or custom name")
    pa.add_argument("-m", "--model", help="model id; also assigns it to a tier")
    pa.add_argument("--tier", choices=["cheap", "fast", "local"], default="fast")
    pa.add_argument("--reference", action="store_true",
                    help="also use this model as the eval reference/judge")
    pa.add_argument("--base-url", help="override (required for non-preset names)")
    pa.add_argument("--key-env", help="env var holding the API key")

    pk = sub.add_parser("set-key")
    pk.add_argument("backend", help="backend name to store a key for (e.g. gemini)")

    # intents + raw all flow through the run handler
    for name in list(INTENTS.keys()) + ["raw"]:
        pi = sub.add_parser(name)
        pi.add_argument("instruction")
        pi.add_argument("--tier", choices=["cheap", "fast", "local"])
        pi.add_argument("-m", "--model")
        pi.add_argument("--json", action="store_true")

    args = p.parse_args()

    if args.cmd == "doctor":
        sys.exit(cmd_doctor(args))
    if args.cmd == "add-backend":
        sys.exit(cmd_add_backend(args))
    if args.cmd == "set-key":
        sys.exit(cmd_set_key(args))
    if args.cmd == "report":
        sys.exit(cmd_report(args))
    if args.cmd in INTENTS or args.cmd == "raw":
        args.intent = None if args.cmd == "raw" else args.cmd
        sys.exit(cmd_run(args))

    p.print_help()
    sys.exit(0)


if __name__ == "__main__":
    main()
