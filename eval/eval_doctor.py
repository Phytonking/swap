#!/usr/bin/env python3
"""Doctor evals — model autodetection + auto-prioritization.

Runs `swap.py doctor --ensure` against a mock Ollama server (every detection
scenario reproducible on any machine, no real Ollama needed) with an isolated
$HOME, then asserts on exit code, STATUS line, and the config doctor wrote.
Offline, deterministic, free.

  python3 eval/eval_doctor.py            # run all scenarios
  python3 eval/eval_doctor.py -k coder   # filter by name substring
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import run_swap

_MODELS = []          # current /api/tags payload served by the mock
DEAD_URL = "127.0.0.1:1"  # connection refused -> "ollama unreachable"


class MockOllama(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/tags":
            body = json.dumps({"models": [{"name": n} for n in _MODELS]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class Ctx:
    def __init__(self, base_url):
        self.base_url = base_url

    def doctor(self, models, home, extra_env=None):
        """Run doctor --ensure. models=None simulates no Ollama at all."""
        global _MODELS
        env = {
            "HOME": home,
            "OLLAMA_HOST": DEAD_URL if models is None else self.base_url,
            # detection must not be influenced by keys in the dev's real env
            "DEEPINFRA_API_KEY": "",
            "OPENAI_API_KEY": "",
        }
        env.update(extra_env or {})
        if models is not None:
            _MODELS = list(models)
        code, out, err, _ = run_swap(["doctor", "--ensure"], env_overrides=env, timeout=30)
        cfg = {}
        cfg_path = os.path.join(home, ".swap", "config.json")
        if os.path.exists(cfg_path):
            with open(cfg_path) as f:
                cfg = json.load(f)
        return code, out, err, cfg


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


SCENARIOS = []


def scenario(name):
    def deco(fn):
        SCENARIOS.append((name, fn))
        return fn
    return deco


# ------------------------------------------------------------ detection

@scenario("detect: no ollama -> NEEDS_BACKEND exit 4 + install hint")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(None, home)
    expect(code == 4, f"exit {code} != 4")
    expect("STATUS: NEEDS_BACKEND" in out, f"stdout: {out!r}")
    expect("NEXT:" in err and "ollama" in err.lower(), f"no actionable NEXT line: {err!r}")
    expect(not cfg.get("tiers"), f"tiers should stay empty, got {cfg.get('tiers')}")


@scenario("detect: ollama up, zero models -> NEEDS_MODEL exit 3 + pull hint")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor([], home)
    expect(code == 3, f"exit {code} != 3")
    expect("STATUS: NEEDS_MODEL" in out, f"stdout: {out!r}")
    expect("ollama pull" in err, f"NEXT should suggest a pull: {err!r}")


@scenario("detect: only embedding models -> NEEDS_MODEL (not a chat default)")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(
        ["nomic-embed-text:latest", "bge-m3:latest"], home)
    expect(code == 3, f"exit {code} != 3")
    expect("STATUS: NEEDS_MODEL" in out, f"stdout: {out!r}")


@scenario("detect: single chat model -> READY, all tiers point at it, shim installed")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(["qwen3:8b"], home)
    expect(code == 0, f"exit {code} != 0; stderr: {err!r}")
    expect("STATUS: READY" in out, f"stdout: {out!r}")
    for t in ("cheap", "fast", "local"):
        expect(cfg["tiers"].get(t) == "ollama/qwen3:8b",
               f"tier {t} = {cfg['tiers'].get(t)}")
    expect(cfg["backends"]["ollama"]["kind"] == "ollama", "ollama backend missing")
    expect(os.path.exists(os.path.join(home, ".swap", "bin", "swap")),
           "stable entrypoint not installed")


@scenario("detect: cloud key in env stays OFF by default (hint only)")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(None, home, extra_env={"DEEPINFRA_API_KEY": "x"})
    expect(code == 4, f"exit {code} != 4 — cloud must not silently enable")
    expect("DEEPINFRA_API_KEY" in err and "OFF by default" in err,
           f"should hint at the unused key: {err!r}")
    expect("deepinfra" not in json.dumps(cfg.get("backends", {})),
           "cloud backend must not be auto-configured")


# ------------------------------------------------------------ prioritization

@scenario("prioritize: qwen3 family beats a bigger llama")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(
        ["gemma3:4b-it-qat", "llama3.3:70b", "qwen3:8b"], home)
    expect(code == 0, f"exit {code}; stderr: {err!r}")
    expect(cfg["tiers"]["cheap"] == "ollama/qwen3:8b",
           f"default = {cfg['tiers']['cheap']}, want qwen3:8b")


@scenario("prioritize: biggest model wins within a family")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(["qwen3:8b", "qwen3:32b", "qwen3:14b"], home)
    expect(code == 0, f"exit {code}")
    expect(cfg["tiers"]["cheap"] == "ollama/qwen3:32b",
           f"default = {cfg['tiers']['cheap']}, want qwen3:32b")


@scenario("prioritize: qwen3.5 counts as qwen3 family")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(["gemma3:4b-it-qat", "qwen3.5:9b-q8_0"], home)
    expect(code == 0, f"exit {code}")
    expect(cfg["tiers"]["cheap"] == "ollama/qwen3.5:9b-q8_0",
           f"default = {cfg['tiers']['cheap']}, want qwen3.5:9b-q8_0")


@scenario("prioritize: embedding model never picked over a chat model")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(["nomic-embed-text:latest", "qwen3:8b"], home)
    expect(code == 0, f"exit {code}")
    expect(cfg["tiers"]["cheap"] == "ollama/qwen3:8b",
           f"default = {cfg['tiers']['cheap']}")


@scenario("prioritize: coder model is NOT the general default, but IS the code intent")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(["qwen3:32b", "qwen3-coder:14b"], home)
    expect(code == 0, f"exit {code}")
    expect(cfg["tiers"]["cheap"] == "ollama/qwen3:32b",
           f"general default = {cfg['tiers']['cheap']}, want qwen3:32b")
    expect(cfg["intents"]["code"].get("model") == "ollama/qwen3-coder:14b",
           f"code intent = {cfg['intents']['code'].get('model')}, want qwen3-coder:14b")


@scenario("prioritize: coder-only install still yields a working default")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(["deepseek-coder:6.7b"], home)
    expect(code == 0, f"exit {code}")
    expect(cfg["tiers"]["cheap"] == "ollama/deepseek-coder:6.7b",
           f"default = {cfg['tiers']['cheap']}")
    expect(cfg["intents"]["code"].get("model") == "ollama/deepseek-coder:6.7b",
           f"code intent = {cfg['intents']['code'].get('model')}")


@scenario("prioritize: no coder installed -> code intent has no model override")
def _(ctx, home):
    code, out, err, cfg = ctx.doctor(["qwen3:8b"], home)
    expect(code == 0, f"exit {code}")
    expect("model" not in cfg["intents"]["code"],
           f"code intent should fall back to tiers, got {cfg['intents']['code']}")


@scenario("idempotent: re-running doctor keeps existing tier choices sticky")
def _(ctx, home):
    code1, _, _, cfg1 = ctx.doctor(["qwen3:8b"], home)
    code2, out2, _, cfg2 = ctx.doctor(["qwen3:8b", "qwen3:32b"], home)
    expect(code1 == 0 and code2 == 0, f"exits {code1}/{code2}")
    expect("STATUS: READY" in out2, "second run should still be READY")
    expect(cfg2["tiers"] == cfg1["tiers"],
           f"tiers changed across runs: {cfg1['tiers']} -> {cfg2['tiers']}")


# ------------------------------------------------------------ runner

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-k", default="", help="only run scenarios whose name contains this")
    args = ap.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", 0), MockOllama)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    ctx = Ctx(f"http://127.0.0.1:{server.server_address[1]}")

    selected = [(n, fn) for n, fn in SCENARIOS if args.k in n]
    passed, failed = 0, []
    for name, fn in selected:
        home = tempfile.mkdtemp(prefix="swap-eval-doctor-")
        try:
            fn(ctx, home)
            passed += 1
            print(f"PASS  {name}")
        except AssertionError as e:
            failed.append((name, str(e)))
            print(f"FAIL  {name}\n      {e}")
        finally:
            shutil.rmtree(home, ignore_errors=True)
    server.shutdown()

    print(f"\ndoctor evals: {passed}/{len(selected)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
