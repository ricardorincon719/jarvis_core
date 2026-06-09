import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from branches.domotica.agent import DomoticaAgent, normalize_text
import branches.scene_memory as scene_memory
import core


DEVICES = {
    "lamp_quarto": {
        "label": "Lampara Cuarto",
        "room": "cuarto",
        "type": "light",
        "capabilities": ["light"],
    },
    "lamp_sala": {
        "label": "Lampara Sala",
        "room": "sala",
        "type": "light",
        "capabilities": ["light"],
    },
}


class FakeMemory:
    def __init__(self):
        self.events = []

    def record_light_event(self, device, intent, scene_name, scene, result, prompt):
        self.events.append((device, intent, scene_name, scene, result, prompt))
        return {"candidates_created": []}


class FakeService:
    def __init__(self):
        self.applied = []

    def devices(self):
        return DEVICES

    def apply_scene(self, device, scene):
        self.applied.append((device, scene))
        return {"ok": True, "device": device}


class DomoticaCompositePlanTest(unittest.TestCase):
    def setUp(self):
        self.service = FakeService()
        self.memory = FakeMemory()
        self.agent = DomoticaAgent(service=self.service, memory=self.memory)

    def test_collective_scene_targets_both_lamps(self):
        plan = self.agent.build_plan("pon ambas lamparas en relax")

        self.assertEqual(
            [(action["device"], action["scene_name"]) for action in plan["actions"]],
            [("lamp_quarto", "relax"), ("lamp_sala", "relax")],
        )

    def test_distinct_scene_is_preserved_for_each_lamp(self):
        plan = self.agent.build_plan(
            "pon la lampara del cuarto en lectura y la lampara de la sala en relax"
        )

        self.assertEqual(plan["intent"], "apply_composite_lighting_scene")
        self.assertEqual(
            [(action["device"], action["scene_name"]) for action in plan["actions"]],
            [("lamp_quarto", "lectura"), ("lamp_sala", "relax")],
        )

    def test_composite_plan_executes_and_records_both_lamps(self):
        prompt = "luz calida en cuarto y sala"
        plan = self.agent.build_plan(prompt)
        response = self.agent.execute_plan(plan, prompt, normalize_text(prompt))

        self.assertTrue(response["ok"])
        self.assertEqual([device for device, _ in self.service.applied], ["lamp_quarto", "lamp_sala"])
        self.assertEqual([event[0] for event in self.memory.events], ["lamp_quarto", "lamp_sala"])


class SharedSceneMemoryMultiLightTest(unittest.TestCase):
    def test_legacy_single_light_signature_is_preserved(self):
        event = {
            "timestamp": "2026-06-09T20:00:00",
            "music": {"target": "laptop", "genre": "lofi"},
            "lights": {
                "device": "lamp_sala",
                "scene_name": "lectura",
                "scene": {"mode": "white", "brightness": 1000},
            },
        }

        self.assertEqual(
            scene_memory._scene_signature(event),
            ("laptop", "lofi", "lamp_sala", "lectura", "white", "high", "evening"),
        )

    def test_candidate_keeps_all_light_actions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir)
            events_file = memory_dir / "compound_events.json"
            scenes_file = memory_dir / "learned_scenes.json"
            result = {
                "ok": True,
                "steps": [
                    {
                        "plugin": "music",
                        "respuesta": "Reproduciendo lofi",
                        "compound_prompt": "reproduce lofi en laptop",
                        "debug": {
                            "plan": {
                                "target": "laptop",
                                "actions": [{"type": "play", "query": "lofi"}],
                            }
                        },
                    },
                    {
                        "plugin": "domotica",
                        "respuesta": "Escena compuesta aplicada",
                        "compound_prompt": "cuarto lectura y sala relax",
                        "debug": {
                            "plan": {
                                "actions": [
                                    {
                                        "type": "apply_scene",
                                        "device": "lamp_quarto",
                                        "scene_name": "lectura",
                                        "scene": {"mode": "white", "brightness": 1000, "temp": 850},
                                    },
                                    {
                                        "type": "apply_scene",
                                        "device": "lamp_sala",
                                        "scene_name": "relax",
                                        "scene": {"mode": "white", "brightness": 350, "temp": 150},
                                    },
                                ]
                            }
                        },
                    },
                ],
            }

            with patch.object(scene_memory, "MEMORY_DIR", memory_dir), patch.object(
                scene_memory, "EVENTS_FILE", events_file
            ), patch.object(scene_memory, "SCENES_FILE", scenes_file), patch.object(
                scene_memory, "DEFAULT_MIN_REPETITIONS", 1
            ), patch.object(scene_memory, "DEFAULT_MIN_UNIQUE_DAYS", 1):
                store = scene_memory.SharedSceneMemory()
                recorded = store.record_compound_result(
                    "reproduce lofi y cuarto lectura y sala relax",
                    [],
                    result,
                )

            self.assertTrue(recorded["recorded"])
            self.assertEqual(len(recorded["event"]["light_actions"]), 2)
            self.assertTrue(recorded["candidates_created"])
            for candidate in recorded["candidates_created"]:
                light_actions = [
                    action for action in candidate["actions"]
                    if action.get("domain") == "domotica"
                ]
                self.assertEqual(
                    [(action["device"], action["scene_name"]) for action in light_actions],
                    [("lamp_quarto", "lectura"), ("lamp_sala", "relax")],
                )


class SharedSceneExecutionTest(unittest.TestCase):
    def test_shared_scene_executes_both_light_actions(self):
        class DomoticaModule:
            def __init__(self):
                self.calls = []

            def apply_scene_to_device(self, device, scene):
                self.calls.append((device, scene["brightness"]))
                return {"ok": True, "respuesta": f"{device} aplicada"}

        class ExecutionMemory:
            def mark_scene_executed(self, scene_id):
                self.scene_id = scene_id

        module = DomoticaModule()
        memory = ExecutionMemory()
        scene = {
            "id": "scene_dos_lamparas",
            "name": "Lofi con cuarto y sala",
            "status": "approved",
            "actions": [
                {
                    "domain": "music",
                    "plugin": "music",
                    "type": "play",
                    "target": "laptop",
                    "query": "lofi",
                },
                {
                    "domain": "domotica",
                    "plugin": "domotica",
                    "type": "apply_scene",
                    "device": "lamp_quarto",
                    "scene_name": "lectura",
                    "scene": {"mode": "white", "brightness": 1000},
                },
                {
                    "domain": "domotica",
                    "plugin": "domotica",
                    "type": "apply_scene",
                    "device": "lamp_sala",
                    "scene_name": "relax",
                    "scene": {"mode": "white", "brightness": 350},
                },
            ],
        }

        plugins = {
            "domotica": {
                "module": module,
                "version": "test",
                "description": "test",
                "triggers": [],
            }
        }
        with patch.object(core, "plugins", plugins), patch.object(
            core, "shared_scene_memory", memory
        ):
            response = core.execute_shared_scene(
                scene,
                "activar escena scene_dos_lamparas solo luces",
            )

        self.assertTrue(response["ok"])
        self.assertEqual(
            module.calls,
            [("lamp_quarto", 1000), ("lamp_sala", 350)],
        )
        self.assertEqual(memory.scene_id, "scene_dos_lamparas")


if __name__ == "__main__":
    unittest.main()
