"""Offline transport checks; these fixtures are not live demo evidence."""

from types import SimpleNamespace
import importlib.util
import unittest
from unittest.mock import patch

HAS_CORE = importlib.util.find_spec("openai") is not None
if HAS_CORE:
    from harness_improvement.llm_backend import JsonLLMBackend


@unittest.skipUnless(HAS_CORE, "requires requirements-core.txt")
class HostedBackendTests(unittest.TestCase):
    def test_hosted_rejects_insecure_or_credentialed_endpoint(self):
        for endpoint in [
            "http://example.test/v1",
            "https://user:key" + "@" + "example.test/v1",
            "https://example.test/v1?key=secret",
        ]:
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                JsonLLMBackend(
                    backend="hosted-chat",
                    model="model",
                    api_key="test",
                    base_url=endpoint,
                )

    def test_hosted_requires_real_key(self):
        for key in ["", "EMPTY"]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                JsonLLMBackend(
                    backend="hosted-chat",
                    model="model",
                    api_key=key,
                    base_url="https://example.test/v1",
                )

    @patch("harness_improvement.llm_backend.OpenAI")
    def test_hosted_omits_vllm_fields_and_records_usage_without_fake_cost(
        self, client_type
    ):
        response = SimpleNamespace(
            id="test-response",
            model="served-model",
            usage=SimpleNamespace(
                model_dump=lambda: {
                    "prompt_tokens": 17,
                    "completion_tokens": 8,
                    "total_tokens": 25,
                }
            ),
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content='{"ok": true}'),
                    finish_reason="stop",
                )
            ],
        )
        client_type.return_value.chat.completions.create.return_value = response
        backend = JsonLLMBackend(
            backend="hosted-chat",
            model="model",
            api_key="test",
            base_url="https://example.test/v1",
            top_k=20,
            temperature=0.2,
            max_output_tokens=100,
        )
        result = backend.call_json(system_prompt="system", user_prompt="user")
        kwargs = client_type.return_value.chat.completions.create.call_args.kwargs
        self.assertNotIn("extra_body", kwargs)
        self.assertNotIn("top_k", kwargs)
        self.assertEqual(kwargs["response_format"], {"type": "json_object"})
        self.assertEqual(result.payload, {"ok": True})
        self.assertEqual(result.metrics["usage"]["total_tokens"], 25)
        self.assertEqual(result.metrics["served_model"], "served-model")
        self.assertIsNone(result.metrics["estimated_cost_usd"])

    @patch("harness_improvement.llm_backend.OpenAI")
    def test_local_vllm_preserves_sampling_extension(self, client_type):
        backend = JsonLLMBackend(
            backend="local-vllm",
            model="model",
            api_key="EMPTY",
            base_url="http://localhost:8000/v1",
            top_k=20,
            enable_thinking=False,
        )
        backend._local_chat(system_prompt="s", user_prompt="u", json_mode=False)
        self.assertEqual(
            client_type.return_value.chat.completions.create.call_args.kwargs[
                "extra_body"
            ],
            {"chat_template_kwargs": {"enable_thinking": False}, "top_k": 20},
        )

    @patch("harness_improvement.llm_backend.OpenAI")
    def test_hosted_verifies_selected_model(self, client_type):
        client_type.return_value.models.list.return_value = SimpleNamespace(
            data=[SimpleNamespace(id="different")]
        )
        backend = JsonLLMBackend(
            backend="hosted-chat",
            model="wanted",
            api_key="test",
            base_url="https://example.test/v1",
        )
        with self.assertRaisesRegex(RuntimeError, "does not serve"):
            backend.verify_model()


if __name__ == "__main__":
    unittest.main()
