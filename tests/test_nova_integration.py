import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import os
os.environ.setdefault("JARVIS_SECRET_TOKEN", "test-master-token-0123456789abcdef")
import core
from branches.local_ia.current import plugin as local_ia
from nova_event_bus import NovaEventBus
from router import route_query


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class LocalIaNovaBridgeTests(unittest.TestCase):
    def test_local_ia_uses_nova_for_ai_queries(self):
        response = FakeResponse(
            payload={
                "status": "succeeded",
                "output": {"text": "Respuesta real de Nova."},
            }
        )
        with patch.object(local_ia, "NOVA_BRIDGE_ENABLED", True), patch.object(
            local_ia.requests,
            "post",
            return_value=response,
        ) as post:
            result = local_ia.handle("Explícame la memoria de PEARL")

        self.assertEqual(result["respuesta"], "Respuesta real de Nova.")
        self.assertEqual(result["cerebro"], "nova")
        self.assertEqual(result["provider"], "jinnex-next")
        self.assertTrue(post.call_args.args[0].endswith("/v1/query"))

    def test_openrouter_remains_a_fallback_when_nova_is_unavailable(self):
        def post(url, **kwargs):
            del kwargs
            if url.endswith("/v1/query"):
                raise local_ia.requests.exceptions.ConnectionError()
            return FakeResponse(
                payload={
                    "choices": [
                        {"message": {"content": "Fallback de PEARL."}}
                    ]
                }
            )

        with patch.object(local_ia, "NOVA_BRIDGE_ENABLED", True), patch.object(
            local_ia,
            "OPENROUTER_API_KEY",
            "configured",
        ), patch.object(local_ia.requests, "post", side_effect=post):
            result = local_ia.handle("Hola")

        self.assertEqual(result["respuesta"], "Fallback de PEARL.")
        self.assertEqual(result["cerebro"], "local_ia")

    def test_explicit_codex_query_uses_jinnex_result(self):
        response = FakeResponse(
            payload={
                "status": "succeeded",
                "route": {
                    "assistant": "codex",
                    "action": "analyze",
                    "command": "codex.analyze",
                },
                "output": {
                    "response": "Análisis real de Codex.",
                    "version": "codex-cli 0.147.0",
                },
            }
        )
        with patch.object(local_ia, "NOVA_BRIDGE_ENABLED", True), patch.object(
            local_ia.requests,
            "post",
            return_value=response,
        ) as post:
            result = local_ia.handle("Codex, analiza el kernel")

        self.assertEqual(result["respuesta"], "Análisis real de Codex.")
        self.assertEqual(result["cerebro"], "codex")
        self.assertEqual(result["intent"], "analyze")
        self.assertEqual(post.call_count, 1)

    def test_ambiguous_codex_query_never_falls_back_to_openrouter(self):
        response = FakeResponse(
            status_code=422,
            payload={
                "status": "failed",
                "route": {"assistant": "codex"},
                "error": {
                    "code": "codex_verb_required",
                    "message": "Después de Codex debe usar un verbo explícito.",
                },
            },
        )
        with patch.object(local_ia, "NOVA_BRIDGE_ENABLED", True), patch.object(
            local_ia,
            "OPENROUTER_API_KEY",
            "configured",
        ), patch.object(local_ia.requests, "post", return_value=response) as post:
            result = local_ia.handle("Codex, qué opinas del kernel")

        self.assertEqual(result["cerebro"], "codex")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(post.call_count, 1)

    def test_unavailable_codex_bridge_never_falls_back_to_openrouter(self):
        with patch.object(local_ia, "NOVA_BRIDGE_ENABLED", True), patch.object(
            local_ia,
            "OPENROUTER_API_KEY",
            "configured",
        ), patch.object(
            local_ia.requests,
            "post",
            side_effect=local_ia.requests.exceptions.ConnectionError(),
        ) as post:
            result = local_ia.handle("Codex, planifica pruebas")

        self.assertEqual(result["cerebro"], "codex")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(post.call_count, 1)

    def test_stream_identifies_nova_as_the_active_model(self):
        response = FakeResponse(
            payload={
                "status": "succeeded",
                "output": {"text": "Respuesta hablada de Nova."},
            }
        )
        with patch.object(local_ia, "NOVA_BRIDGE_ENABLED", True), patch.object(
            local_ia.requests,
            "post",
            return_value=response,
        ):
            events = [json.loads(line) for line in local_ia.handle_stream("Hola")]

        self.assertEqual(events[0]["event"], "meta")
        self.assertEqual(events[0]["model"], "nova-2.0.1")
        self.assertEqual(events[-1]["model"], "nova-2.0.1")

    def test_deterministic_router_keeps_physical_domains_away_from_nova(self):
        plugins = ["domotica", "music", "hardware", "local_ia"]

        self.assertEqual(route_query("enciende la luz de la sala", plugins), "domotica")
        self.assertEqual(route_query("reproduce jazz", plugins), "music")
        self.assertEqual(route_query("estado de la batería", plugins), "hardware")
        self.assertEqual(route_query("explícame qué es una estrella", plugins), "local_ia")

    def test_ai_status_reports_nova_as_active_local_provider(self):
        response = FakeResponse(
            payload={
                "status": "ok",
                "nova": "connected",
                "service": "jinnex-nova",
                "liveness": True,
                "readiness": {"ready": True, "status": "ok"},
            }
        )
        with patch.object(core, "NOVA_ENABLED", True), patch.dict(
            core.plugins,
            {"local_ia": {"module": local_ia}},
        ), patch.object(core.requests, "get", return_value=response) as get:
            result = core.check_local_ai_status()

        self.assertEqual(result["provider"], "jinnex-next")
        self.assertEqual(result["model"], "nova-2.0.1")
        self.assertTrue(result["connected"])
        self.assertEqual(result["status"], "connected")
        self.assertEqual(get.call_args.args[0], f"{core.NOVA_URL}/health")

    def test_core_fetches_real_nova_complex_event_candidates(self):
        candidates = [{
            "complex_event_id": "complex-1",
            "status": "candidate",
            "summary": "Música y luz de lectura",
            "requires_confirmation": True,
            "auto_execute": False,
        }]
        response = FakeResponse(payload={"status": "ok", "candidates": candidates})

        with patch.object(core, "NOVA_ENABLED", True), patch.object(
            core.requests,
            "get",
            return_value=response,
        ) as get:
            result = core.fetch_nova_complex_event_candidates(limit=25)

        self.assertEqual(result, candidates)
        self.assertEqual(
            get.call_args.args[0],
            f"{core.NOVA_URL}/v1/complex-events/candidates",
        )
        self.assertEqual(get.call_args.kwargs["params"], {"limit": 25})

    def test_candidate_phrase_is_answered_from_nova_not_conversation(self):
        candidate = {
            "complex_event_id": "complex-1",
            "status": "candidate",
            "summary": "Música jazz y luz blanca",
            "occurred_at": "2026-08-14T21:09:32+00:00",
        }
        client = core.app.test_client()
        headers = {"Authorization": f"Bearer {core.SECRET_TOKEN}"}

        with patch.object(
            core,
            "fetch_nova_complex_event_candidates",
            return_value=[candidate],
        ), patch.object(core, "route_query") as router:
            response = client.post(
                "/ask_stream",
                headers=headers,
                json={"pregunta": "Escenas candidatas"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["candidate_source"], "nova_complex_events")
        self.assertEqual(response.get_json()["nova_candidates"], [candidate])
        self.assertIn("Candidatos de eventos compuestos en Nova", response.get_json()["respuesta"])
        router.assert_not_called()

    def test_authenticated_core_endpoint_keeps_nova_candidates_separate(self):
        candidate = {"complex_event_id": "complex-1", "status": "candidate"}
        client = core.app.test_client()
        headers = {"Authorization": f"Bearer {core.SECRET_TOKEN}"}

        with patch.object(
            core,
            "fetch_nova_complex_event_candidates",
            return_value=[candidate],
        ):
            response = client.get(
                "/api/v1/nova/complex-event-candidates?limit=10",
                headers=headers,
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["source"], "nova")
        self.assertEqual(response.get_json()["candidate_type"], "complex_event")
        self.assertEqual(response.get_json()["candidates"], [candidate])


class NovaEventBusTests(unittest.TestCase):
    def test_compound_event_is_durable_and_delivered_without_changing_pearl(self):
        delivered = []

        def post(url, **kwargs):
            delivered.append((url, kwargs["json"]))
            return FakeResponse(status_code=200, payload={
                "status": "succeeded", "output": {"status": "candidate", "complex_event": {
                    "source_event_id": kwargs["json"]["event_id"], "auto_execute": False,
                }},
            })

        response = {
            "compound": True,
            "ok": True,
            "steps": [
                {"plugin": "music", "ok": True},
                {"plugin": "domotica", "ok": True},
            ],
            "scene_memory": {
                "event": {
                    "id": "compound_event_test",
                    "timestamp": "2026-08-14T12:00:00+00:00",
                    "music": {"query": "lofi"},
                    "light_actions": [{"device": "lamp_sala"}],
                }
            },
        }
        with tempfile.TemporaryDirectory() as temporary_directory:
            bus = NovaEventBus(
                Path(temporary_directory) / "outbox.db",
                "http://127.0.0.1:5010",
                http_post=post,
                start_worker=False,
            )
            try:
                event_id = bus.publish_compound_response("música y luces", response)
                self.assertEqual(event_id, "compound_event_test")
                self.assertEqual(bus.list_outbox()[0]["status"], "pending")

                self.assertEqual(bus.deliver_pending_once(), 1)

                self.assertEqual(bus.list_outbox()[0]["status"], "delivered")
                envelope = delivered[0][1]
                self.assertEqual(envelope["event_type"], "pearl.compound.completed")
                self.assertEqual(len(envelope["payload"]["steps"]), 2)
            finally:
                bus.close()

    def test_core_observer_failure_never_changes_compound_response(self):
        class BrokenBus:
            def publish_compound_response(self, prompt, payload):
                del prompt, payload
                raise RuntimeError("nova offline")

        previous = core.app.config.get("NOVA_EVENT_BUS")
        core.app.config["NOVA_EVENT_BUS"] = BrokenBus()
        try:
            with core.app.test_request_context(
                "/ask",
                method="POST",
                json={"pregunta": "reproduce lofi y enciende la luz"},
            ):
                original = core.app.response_class(
                    json.dumps({"compound": True, "ok": True}),
                    content_type="application/json",
                )
                observed = core.publish_compound_event_to_nova(original)
        finally:
            if previous is None:
                core.app.config.pop("NOVA_EVENT_BUS", None)
            else:
                core.app.config["NOVA_EVENT_BUS"] = previous

        self.assertIs(observed, original)
        self.assertEqual(observed.get_json(), {"compound": True, "ok": True})

if __name__ == "__main__":
    unittest.main()
