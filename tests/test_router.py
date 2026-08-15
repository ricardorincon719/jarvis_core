import unittest

from router import route_query


class RouterTest(unittest.TestCase):
    def setUp(self):
        self.plugins = ["domotica", "music", "music_local", "local_ia"]

    def test_relax_light_scene_routes_to_domotica(self):
        prompts = [
            "luz relax lamp_sala",
            "luz lamp_sala relax",
            "luz relax lamp_quarto",
            "lampara relajante sala",
        ]

        for prompt in prompts:
            with self.subTest(prompt=prompt):
                self.assertEqual(route_query(prompt, self.plugins), "domotica")

    def test_explicit_relax_music_request_stays_in_music(self):
        self.assertEqual(
            route_query("reproduce musica relax", self.plugins),
            "music",
        )

    def test_explicit_assistant_prefix_precedes_domain_scoring(self):
        plugins = ["domotica", "music", "critical", "local_ia"]

        self.assertEqual(
            route_query("Codex, analiza la arquitectura", plugins),
            "local_ia",
        )
        self.assertEqual(
            route_query("Nova, explícame la escena de lectura", plugins),
            "local_ia",
        )


if __name__ == "__main__":
    unittest.main()
