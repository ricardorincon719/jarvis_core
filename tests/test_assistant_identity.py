import importlib.util
import json
from pathlib import Path
from unittest.mock import Mock, patch
import unittest

from assistant_identity import build_assistant_prompt


PLUGIN_PATH = Path(__file__).resolve().parents[1] / "branches/local_ia/v1.0.0/plugin.py"


def load_local_ai_plugin():
    spec = importlib.util.spec_from_file_location("test_local_ia_plugin", PLUGIN_PATH)
    module = importlib.util.module_from_spec(spec)
    with patch.dict("os.environ", {"PEARL_NOVA_ENABLED": "false"}):
        spec.loader.exec_module(module)
    return module


class AssistantIdentityTest(unittest.TestCase):
    def test_shared_prompt_defines_jarvis_identity(self):
        prompt = build_assistant_prompt("Como te llamas?")

        self.assertIn("Tu nombre es JARVIS", prompt)
        self.assertIn("asistente local de PEARL HOME", prompt)
        self.assertIn("No te presentes como Qwen", prompt)
        self.assertIn("español latinoamericano neutro", prompt)
        self.assertIn("caracteres Unicode", prompt)
        self.assertTrue(prompt.endswith("JARVIS:"))

    def test_local_ai_wraps_user_prompt_before_calling_openrouter(self):
        plugin = load_local_ai_plugin()
        response = Mock(status_code=200)
        response.json.return_value = {
            "choices": [{"message": {"content": "Soy JARVIS."}}]
        }

        with patch.object(plugin, "OPENROUTER_API_KEY", "test-key"), patch.object(
            plugin.requests, "post", return_value=response
        ) as post:
            result = plugin.handle("Quien eres?")

        sent_request = post.call_args.kwargs["json"]
        sent_prompt = sent_request["messages"][0]["content"]
        self.assertIn("Tu nombre es JARVIS", sent_prompt)
        self.assertIn("Usuario: Quien eres?", sent_prompt)
        self.assertEqual(sent_request["model"], plugin.OPENROUTER_MODEL)
        self.assertEqual(
            post.call_args.kwargs["headers"]["Authorization"],
            "Bearer test-key",
        )
        self.assertEqual(result["respuesta"], "Soy JARVIS.")

    def test_local_ai_reports_missing_openrouter_key(self):
        plugin = load_local_ai_plugin()

        with patch.object(plugin, "OPENROUTER_API_KEY", ""):
            result = plugin.handle("Hola")

        self.assertEqual(result["status"], "not_configured")
        self.assertIn("OPENROUTER_API_KEY", result["respuesta"])

    def test_local_ai_parses_openrouter_sse_stream(self):
        plugin = load_local_ai_plugin()
        response = Mock(status_code=200)
        response.iter_lines.return_value = [
            b": OPENROUTER PROCESSING",
            b'data: {"model":"test/model","choices":[{"delta":{"content":"Soy "}}]}',
            'data: {"choices":[{"delta":{"content":"© JARVIS."}}]}'.encode("utf-8"),
            b"data: [DONE]",
        ]
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=None)

        with patch.object(plugin, "OPENROUTER_API_KEY", "test-key"), patch.object(
            plugin.requests, "post", return_value=response
        ):
            events = [json.loads(line) for line in plugin.handle_stream("Hola")]

        self.assertEqual(events[0]["event"], "meta")
        self.assertEqual(
            "".join(event["response"] for event in events if event["event"] == "token"),
            "Soy © JARVIS.",
        )
        self.assertEqual(events[-1]["event"], "done")


if __name__ == "__main__":
    unittest.main()
