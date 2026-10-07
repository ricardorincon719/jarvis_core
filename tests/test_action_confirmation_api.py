import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest

from action_proposals import ActionProposalStore
import os
os.environ.setdefault("JARVIS_SECRET_TOKEN", "test-master-token-0123456789abcdef")
import core


class FakePlannedPlugin:
    def __init__(self, plugin_name="domotica", action_type="turn_on"):
        self.plugin_name = plugin_name
        self.action_type = action_type
        self.executions = 0
        self.handles = 0
        self.applied_scenes = []

    def build_plan(self, prompt):
        action = {"type": self.action_type}
        if self.plugin_name == "domotica":
            action["device"] = "lamp_sala"
        elif self.action_type == "play":
            action["query"] = "jazz"
        return {
            "agent": self.plugin_name,
            "intent": self.action_type,
            "requires_confirmation": False,
            "actions": [action],
        }

    def execute_confirmed_plan(self, plan, prompt):
        self.executions += 1
        return {
            "respuesta": f"ejecutado {plan['actions'][0]['type']}",
            "ok": True,
            "debug": {"plan": plan},
        }

    def handle(self, prompt):
        self.handles += 1
        return {"respuesta": "consulta inmediata", "ok": True}

    def apply_scene_to_device(self, device, scene):
        self.applied_scenes.append((device, scene))
        return {"respuesta": "escena aplicada", "ok": True}


class FakeSharedSceneMemory:
    def __init__(self, scene=None):
        self.scene = scene
        self.compound_records = []
        self.executed = []

    def find_scene(self, query):
        if not self.scene:
            return None
        return self.scene if query in {self.scene["id"], self.scene["name"]} else None

    def mark_scene_executed(self, scene_id):
        self.executed.append(scene_id)

    def record_compound_result(self, prompt, dispatch, result):
        self.compound_records.append((prompt, dispatch, result))
        return {"recorded": True, "candidates_created": []}


class FakeConversationalPlugin:
    def __init__(self):
        self.handles = 0

    def handle(self, prompt):
        self.handles += 1
        return {"respuesta": f"respuesta a {prompt}", "ok": True}


class RecordingNovaEventBus:
    def __init__(self, error=None):
        self.error = error
        self.publications = []

    def publish_compound_response(self, prompt, payload):
        if self.error is not None:
            raise self.error
        self.publications.append((prompt, payload))
        return "nova-event-1"


class ActionConfirmationApiTest(unittest.TestCase):
    def setUp(self):
        core.app.config.update(TESTING=True)
        self.client = core.app.test_client()
        self.headers = {"Authorization": f"Bearer {core.SECRET_TOKEN}"}
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ActionProposalStore(Path(self.temp_dir.name) / "actions.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def plugin_registry(self, name, module):
        return {
            name: {
                "module": module,
                "version": "test",
                "description": "test",
                "triggers": [],
            }
        }

    def test_confirmation_vocabulary_is_explicit(self):
        for phrase in ("sí", "si", "confirmo", "confirmar", "sí hazlo"):
            self.assertEqual(core.natural_action_decision(phrase), "accept")
        for phrase in ("no", "cancelar", "rechazar", "no lo hagas"):
            self.assertEqual(core.natural_action_decision(phrase), "cancel")
        for phrase in ("ok", "dale", "adelante"):
            self.assertIsNone(core.natural_action_decision(phrase))

    def test_confirmado_and_its_cancel_variants(self):
        for phrase in ("Confirmado.", "confirmada", "Sí, confirmado"):
            self.assertEqual(core.natural_action_decision(phrase), "accept")
        for phrase in ("cancelado", "mejor no", "déjalo", "olvídalo"):
            self.assertEqual(core.natural_action_decision(phrase), "cancel")

    def test_voice_confirmation_is_routed_as_action_only_with_pending_proposal(self):
        """Nova pregunta a /api/v1/route y sólo envía a /ask lo que es acción."""
        module = FakePlannedPlugin("music", "play")
        plugins = {**self.plugin_registry("music", module),
                   **self.plugin_registry("local_ia", FakeConversationalPlugin())}
        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", plugins
        ), patch.object(core, "pulse_route"):
            before = self.client.post("/api/v1/route", headers=self.headers,
                                      json={"text": "confirmado"}).get_json()
            with patch.object(core, "route_query", return_value="music"):
                self.client.post("/ask", headers=self.headers,
                                 json={"pregunta": "reproduce jazz instrumental"})
            routed = self.client.post("/api/v1/route", headers=self.headers,
                                      json={"text": "Confirmado."}).get_json()
            confirmed = self.client.post("/ask", headers=self.headers,
                                         json={"pregunta": "Confirmado."})

        self.assertEqual(before["kind"], "assistant")
        self.assertEqual(routed["kind"], "action")
        self.assertEqual(confirmed.get_json()["status"], "executed")
        self.assertEqual(module.executions, 1)

    def test_other_device_cannot_confirm_by_voice(self):
        module = FakePlannedPlugin("music", "play")
        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", self.plugin_registry("music", module)
        ), patch.object(core, "route_query", return_value="music"):
            self.client.post("/ask", headers=self.headers,
                             json={"pregunta": "reproduce jazz"})
            with patch.object(core, "action_requester",
                              return_value={"type": "device", "id": "otro", "name": "x"}):
                self.assertFalse(core.pending_natural_decision("confirmado", None))

    def test_level_two_action_waits_for_confirmation_and_executes_once(self):
        module = FakePlannedPlugin("music", "play")
        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", self.plugin_registry("music", module)
        ), patch.object(core, "route_query", return_value="music"):
            proposed = self.client.post(
                "/ask_stream",
                headers=self.headers,
                json={"pregunta": "reproduce jazz"},
            )
            proposal = proposed.get_json()["proposal"]

            self.assertEqual(proposed.status_code, 200)
            self.assertTrue(proposed.get_json()["requires_confirmation"])
            self.assertEqual(module.executions, 0)
            self.assertEqual(module.handles, 0)

            accepted = self.client.post(
                f"/api/v1/actions/{proposal['id']}/decision",
                headers=self.headers,
                json={"decision": "accept", "idempotency_key": "decision-1"},
            )
            replay = self.client.post(
                f"/api/v1/actions/{proposal['id']}/decision",
                headers=self.headers,
                json={"decision": "accept", "idempotency_key": "decision-1"},
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.get_json()["status"], "executed")
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.get_json()["idempotent"])
        self.assertEqual(module.executions, 1)

    def test_read_only_plan_executes_without_confirmation(self):
        module = FakePlannedPlugin(action_type="status")
        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", self.plugin_registry("domotica", module)
        ), patch.object(core, "route_query", return_value="domotica"):
            response = self.client.post(
                "/ask",
                headers=self.headers,
                json={"pregunta": "estado de la luz"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("proposal", response.get_json())
        self.assertEqual(module.handles, 0)
        self.assertEqual(module.executions, 1)

    def test_all_direct_light_modes_execute_without_confirmation(self):
        for action_type in ("turn_on", "turn_off", "apply_scene"):
            module = FakePlannedPlugin("domotica", action_type)
            with self.subTest(action_type=action_type), patch.object(
                core, "action_proposal_store", self.store
            ), patch.object(
                core, "plugins", self.plugin_registry("domotica", module)
            ), patch.object(core, "route_query", return_value="domotica"), patch.object(
                core, "maybe_propose_shared_scene", return_value=None
            ), patch.object(core, "handle_shared_scene_command", return_value=None):
                response = self.client.post(
                    "/ask",
                    headers=self.headers,
                    json={"pregunta": f"luz {action_type}"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertNotIn("proposal", response.get_json())
            self.assertEqual(response.get_json()["action_level"], 1)
            self.assertEqual(module.executions, 1)

    def test_cancel_never_executes(self):
        module = FakePlannedPlugin("music", "play")
        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", self.plugin_registry("music", module)
        ), patch.object(core, "route_query", return_value="music"):
            proposed = self.client.post(
                "/ask",
                headers=self.headers,
                json={"pregunta": "reproduce jazz"},
            ).get_json()
            cancelled = self.client.post(
                f"/api/v1/actions/{proposed['proposal']['id']}/decision",
                headers=self.headers,
                json={"decision": "cancel", "idempotency_key": "cancel-1"},
            )

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.get_json()["status"], "cancelled")
        self.assertEqual(module.executions, 0)

    def test_natural_yes_confirms_pending_action_before_router(self):
        module = FakePlannedPlugin("music", "play")
        plugins = self.plugin_registry("music", module)

        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", plugins
        ), patch.object(core, "route_query", return_value="music") as router:
            proposed = self.client.post(
                "/ask_stream",
                headers=self.headers,
                json={"pregunta": "reproduce jazz"},
            ).get_json()
            confirmed = self.client.post(
                "/ask_stream",
                headers=self.headers,
                json={"pregunta": "sí"},
            )

        self.assertIn("proposal", proposed)
        self.assertEqual(confirmed.status_code, 200)
        self.assertEqual(confirmed.get_json()["status"], "executed")
        self.assertTrue(confirmed.get_json()["natural_confirmation"])
        self.assertEqual(module.executions, 1)
        self.assertEqual(router.call_count, 1)

    def test_natural_cancel_discards_pending_action(self):
        module = FakePlannedPlugin("music", "play")
        plugins = self.plugin_registry("music", module)

        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", plugins
        ), patch.object(core, "route_query", return_value="music"):
            self.client.post(
                "/ask",
                headers=self.headers,
                json={"pregunta": "reproduce jazz"},
            )
            cancelled = self.client.post(
                "/ask",
                headers=self.headers,
                json={"pregunta": "cancelar"},
            )

        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.get_json()["status"], "cancelled")
        self.assertTrue(cancelled.get_json()["natural_confirmation"])
        self.assertEqual(module.executions, 0)

    def test_yes_without_pending_action_keeps_normal_routing(self):
        module = FakeConversationalPlugin()
        plugins = self.plugin_registry("local_ia", module)

        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", plugins
        ), patch.object(core, "route_query", return_value="local_ia") as router:
            response = self.client.post(
                "/ask",
                headers=self.headers,
                json={"pregunta": "sí"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("natural_confirmation", response.get_json())
        self.assertEqual(module.handles, 1)
        router.assert_called_once()

    def test_sensitive_prompt_is_blocked_before_router(self):
        module = FakeConversationalPlugin()
        with patch.object(
            core, "plugins", self.plugin_registry("local_ia", module)
        ), patch.object(core, "route_query", return_value="local_ia") as router:
            response = self.client.post(
                "/ask",
                headers=self.headers,
                json={"pregunta": "borra todos los archivos"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "blocked")
        self.assertEqual(response.get_json()["action_level"], 3)
        self.assertEqual(module.handles, 0)
        router.assert_not_called()

    def test_compound_command_executes_all_bound_plans_after_one_confirmation(self):
        music = FakePlannedPlugin("music", "play")
        lights = FakePlannedPlugin("domotica", "turn_on")
        plugins = {
            **self.plugin_registry("music", music),
            **self.plugin_registry("domotica", lights),
        }
        memory = FakeSharedSceneMemory()
        event_bus = RecordingNovaEventBus()

        def route(text, available):
            return "music" if "jazz" in text else "domotica"

        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", plugins
        ), patch.object(core, "route_query", side_effect=route), patch.object(
            core, "shared_scene_memory", memory
        ), patch.object(
            core, "get_nova_event_bus", return_value=event_bus
        ):
            proposed = self.client.post(
                "/ask",
                headers=self.headers,
                json={"pregunta": "reproduce jazz y enciende la luz"},
            ).get_json()
            accepted = self.client.post(
                f"/api/v1/actions/{proposed['proposal']['id']}/decision",
                headers=self.headers,
                json={"decision": "accept", "idempotency_key": "compound-1"},
            )
            replay = self.client.post(
                f"/api/v1/actions/{proposed['proposal']['id']}/decision",
                headers=self.headers,
                json={"decision": "accept", "idempotency_key": "compound-1"},
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(proposed["proposal"]["kind"], "compound_plan")
        self.assertEqual(music.executions, 1)
        self.assertEqual(lights.executions, 1)
        self.assertEqual(len(memory.compound_records), 1)
        self.assertTrue(replay.get_json()["idempotent"])
        self.assertEqual(len(event_bus.publications), 1)
        self.assertEqual(event_bus.publications[0][0], "reproduce jazz y enciende la luz")
        self.assertTrue(event_bus.publications[0][1]["compound"])

    def test_nova_observer_failure_does_not_change_confirmed_execution(self):
        music = FakePlannedPlugin("music", "play")
        lights = FakePlannedPlugin("domotica", "turn_on")
        plugins = {
            **self.plugin_registry("music", music),
            **self.plugin_registry("domotica", lights),
        }

        def route(text, available):
            del available
            return "music" if "jazz" in text else "domotica"

        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", plugins
        ), patch.object(core, "route_query", side_effect=route), patch.object(
            core, "shared_scene_memory", FakeSharedSceneMemory()
        ), patch.object(
            core,
            "get_nova_event_bus",
            return_value=RecordingNovaEventBus(RuntimeError("nova offline")),
        ):
            proposed = self.client.post(
                "/ask",
                headers=self.headers,
                json={"pregunta": "reproduce jazz y enciende la luz"},
            ).get_json()
            accepted = self.client.post(
                f"/api/v1/actions/{proposed['proposal']['id']}/decision",
                headers=self.headers,
                json={"decision": "accept", "idempotency_key": "compound-offline"},
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.get_json()["status"], "executed")
        self.assertEqual(music.executions, 1)
        self.assertEqual(lights.executions, 1)

    def test_approved_shared_scene_is_proposed_before_physical_execution(self):
        lights = FakePlannedPlugin("domotica", "apply_scene")
        scene = {
            "id": "scene_relax",
            "name": "sala relax",
            "status": "approved",
            "actions": [{
                "domain": "domotica",
                "plugin": "domotica",
                "type": "apply_scene",
                "device": "lamp_sala",
                "scene_name": "relax",
                "scene": {"switch": True, "mode": "white", "brightness": 350},
            }],
        }
        memory = FakeSharedSceneMemory(scene)

        with patch.object(core, "action_proposal_store", self.store), patch.object(
            core, "plugins", self.plugin_registry("domotica", lights)
        ), patch.object(core, "route_query", return_value="domotica"), patch.object(
            core, "shared_scene_memory", memory
        ):
            proposed = self.client.post(
                "/ask_stream",
                headers=self.headers,
                json={"pregunta": "activar escena sala relax"},
            ).get_json()

            self.assertEqual(lights.applied_scenes, [])
            accepted = self.client.post(
                f"/api/v1/actions/{proposed['proposal']['id']}/decision",
                headers=self.headers,
                json={"decision": "accept", "idempotency_key": "scene-1"},
            )

        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(proposed["proposal"]["kind"], "shared_scene")
        self.assertEqual(len(lights.applied_scenes), 1)
        self.assertEqual(memory.executed, ["scene_relax"])


if __name__ == "__main__":
    unittest.main()
