import unittest

from router import is_explicit_ai_assistant_request, route_query


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

    def test_jinnex_alias_and_memory_destination_precede_domain_scoring(self):
        for name in ('jarvis', 'jinnex', 'jinnez', 'ginnex', 'ginnes', 'chinnese'):
            for text in (f'{name}, explica mi escena de luz azul',
                         f'guarda en {name} que mi color es rojo',
                         f'guarda mi color rojo en {name}',
                         f'guarda esto en {name}: mi lámpara es azul'):
                with self.subTest(text=text):
                    self.assertEqual(route_query(text, self.plugins), 'local_ia')

    def test_alias_inside_data_and_unknown_similar_names_are_not_invocations(self):
        for text in ('mi vecino ginnes vive aquí', 'ginnexican es un nombre',
                     'guarda en ginnexican que mi color es rojo',
                     'guarda en guinness que dato'):
            self.assertFalse(is_explicit_ai_assistant_request(text))


if __name__ == "__main__":
    unittest.main()
