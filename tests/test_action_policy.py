import unittest

from action_policy import (
    LEVEL_BLOCKED,
    LEVEL_CONFIRM,
    LEVEL_RESPOND_ONLY,
    LEVEL_SAFE,
    blocked_prompt_reason,
    classify_plan,
)


class ActionPolicyTest(unittest.TestCase):
    def test_empty_plan_only_responds(self):
        self.assertEqual(classify_plan("local_ia", {"actions": []}), LEVEL_RESPOND_ONLY)

    def test_all_direct_light_modes_are_safe(self):
        for action in (
            {"type": "turn_on", "device": "lamp_sala"},
            {"type": "turn_off", "device": "lamp_sala"},
            {"type": "apply_scene", "scene_name": "calida", "scene": {}},
            {"type": "apply_scene", "scene_name": "brillo_40", "scene": {}},
        ):
            with self.subTest(action=action):
                self.assertEqual(
                    classify_plan("domotica", {"actions": [action]}),
                    LEVEL_SAFE,
                )

    def test_scene_activation_requires_confirmation(self):
        plan = {"actions": [{"type": "apply_learned_scene", "query": "relax"}]}
        self.assertEqual(classify_plan("domotica", plan), LEVEL_CONFIRM)

    def test_music_pause_is_safe_but_play_requires_confirmation(self):
        self.assertEqual(
            classify_plan("music", {"actions": [{"type": "pause"}]}),
            LEVEL_SAFE,
        )
        self.assertEqual(
            classify_plan("music", {"actions": [{"type": "play"}]}),
            LEVEL_CONFIRM,
        )

    def test_unknown_and_sensitive_actions_are_blocked(self):
        for action_type in ("unknown_mutation", "delete_file", "expose_port", "modify_token"):
            with self.subTest(action_type=action_type):
                self.assertEqual(
                    classify_plan("critical", {"actions": [{"type": action_type}]}),
                    LEVEL_BLOCKED,
                )

    def test_sensitive_prompts_are_blocked_but_ngrok_is_confirmable(self):
        self.assertEqual(blocked_prompt_reason("borra todos los archivos"), "borrado_de_archivos")
        self.assertEqual(blocked_prompt_reason("expone el puerto 8080"), "exposicion_de_puertos")
        self.assertEqual(blocked_prompt_reason("modifica el token de acceso"), "modificacion_de_secretos")
        self.assertEqual(blocked_prompt_reason("cambia el archivo .env"), "configuracion_sensible")
        self.assertIsNone(blocked_prompt_reason("abre un tunel ngrok"))


if __name__ == "__main__":
    unittest.main()
