"""Stdlib smoke tests for the swap router — no Ollama, no network, no keys.

Covers the pure logic that the eval suite can't reach in CI: model
auto-prioritization, JSON repair, context clipping, context-window lookup.
Run: python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "skills", "swap"))
import swap  # noqa: E402


class TestPrioritization(unittest.TestCase):
    def test_family_preference_over_size(self):
        # qwen3 family beats a bigger non-qwen model as the general default
        self.assertEqual(
            swap.pick_default_model(["gemma3:4b", "llama3.3:70b", "qwen3:8b"]),
            "qwen3:8b")

    def test_biggest_within_family(self):
        self.assertEqual(
            swap.pick_default_model(["qwen3:8b", "qwen3:32b", "qwen3:14b"]),
            "qwen3:32b")

    def test_embedding_models_never_default(self):
        self.assertEqual(
            swap.pick_default_model(["nomic-embed-text:latest", "qwen3:8b"]),
            "qwen3:8b")

    def test_coder_excluded_from_general_default(self):
        self.assertEqual(
            swap.pick_default_model(["qwen3:32b", "qwen3-coder:14b"]), "qwen3:32b")

    def test_coder_chosen_for_code(self):
        self.assertEqual(
            swap.pick_code_model(["qwen3:32b", "qwen3-coder:14b"]), "qwen3-coder:14b")

    def test_no_coder_returns_none(self):
        self.assertIsNone(swap.pick_code_model(["qwen3:8b"]))

    def test_empty_returns_none(self):
        self.assertIsNone(swap.pick_default_model([]))

    def test_param_size_parsing(self):
        self.assertEqual(swap._param_size_b("qwen3:32b"), 32.0)
        self.assertEqual(swap._param_size_b("qwen3.5:9b-q8_0"), 9.0)
        self.assertEqual(swap._param_size_b("model-with-no-size"), 0.0)


class TestJsonRepair(unittest.TestCase):
    def test_clean_json(self):
        out, ok = swap.coerce_json('{"label": "real"}')
        self.assertTrue(ok)

    def test_fenced_json(self):
        out, ok = swap.coerce_json('```json\n{"label": "flaky"}\n```')
        self.assertTrue(ok)
        self.assertIn("flaky", out)

    def test_prose_wrapped_json(self):
        out, ok = swap.coerce_json('Here is the JSON: [{"file": "a.ts"}] hope it helps')
        self.assertTrue(ok)

    def test_brackets_inside_strings(self):
        out, ok = swap.coerce_json('noise {"a": "has ] and } inside", "b": [1,2]} tail')
        self.assertTrue(ok)
        import json
        self.assertEqual(json.loads(out), {"a": "has ] and } inside", "b": [1, 2]})

    def test_unparseable(self):
        _, ok = swap.coerce_json("I cannot answer that.")
        self.assertFalse(ok)


class TestContextClip(unittest.TestCase):
    def test_clips_and_keeps_head_and_tail(self):
        big = "HEAD" + ("x" * 10000) + "TAIL"
        out, clipped = swap.clip_to_budget(big, 1000)
        self.assertTrue(clipped)
        self.assertTrue(out.startswith("HEAD"))
        self.assertTrue(out.endswith("TAIL"))
        self.assertIn("omitted", out)
        self.assertLess(len(out), len(big))

    def test_no_clip_when_under_budget(self):
        out, clipped = swap.clip_to_budget("tiny", 1000)
        self.assertFalse(clipped)
        self.assertEqual(out, "tiny")

    def test_model_ctx_lookup_and_fallback(self):
        cfg = {"backends": {"ollama": {"kind": "ollama",
                                       "models": {"qwen3.5:9b": 262144}}}}
        self.assertEqual(swap.model_ctx_tokens(cfg, "ollama/qwen3.5:9b"), 262144)
        self.assertEqual(swap.model_ctx_tokens(cfg, "ollama/unknown"),
                         swap.DEFAULT_CTX_TOK)


class TestTextHelpers(unittest.TestCase):
    def test_strip_think(self):
        self.assertEqual(swap.strip_think("<think>reasoning</think>answer"), "answer")

    def test_strip_fences(self):
        self.assertEqual(swap.strip_fences("```python\ncode\n```"), "code")


if __name__ == "__main__":
    unittest.main()
