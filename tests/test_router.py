import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import unittest

from router import classify_query, is_explicit_ai_assistant_request, route_query


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


class StrictActionGateTest(unittest.TestCase):
    """Palabras de la casa sin una orden explícita son conversación."""

    def setUp(self):
        self.plugins = ["domotica", "music", "music_local", "hardware", "local_ia"]

    def test_conversation_about_home_topics_goes_to_assistant(self):
        for prompt in [
            "qué música te gusta",
            "recomiéndame una canción",
            "me gusta la luz cálida",
            "apaga la reputación",  # transcripción errónea de voz
            "prende la invitación",
        ]:
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    classify_query(prompt, self.plugins),
                    {"plugin": "local_ia", "kind": "assistant"},
                )

    def test_explicit_orders_are_actions(self):
        expected = {
            "apaga la luz de la sala": "domotica",
            "por favor prende las luces": "domotica",
            "pon la escena lectura": "domotica",
            "pon jazz": "music",
            "reproduce lofi": "music",
            "siguiente": "music",
            "baja el volumen": "music",
            "vibra": "hardware",
            "estado de la batería": "hardware",
        }
        for prompt, plugin in expected.items():
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    classify_query(prompt, self.plugins),
                    {"plugin": plugin, "kind": "action"},
                )

    def test_corpus_inherited_from_nova_intent_router(self):
        # Antes Nova decidía esto con su propia lista; ahora sólo lo decide Core.
        plugins = self.plugins + ["vision"]
        actions = [
            "enciende la luz del dormitorio", "por favor cambia el color de lamp_sala a azul",
            "dime el estado de las luces", "reproduce música jazz", "pausa", "sube el volumen",
            "estado del sistema", "enciende la linterna", "reproduce Queen", "escenas aprendidas",
            "aprueba escena sala relax", "estado de la luz", "¿Cómo me veo?", "mírame",
            "¿qué ves?", "¿cómo estoy?", "¿cómo he estado?", "cuánto llevo frente a la laptop",
            "deja de mirarme", "vuelve a mirarme", "apaga la cámara",
        ]
        conversation = [
            "¿cómo estoy de tiempo para la reunión?", "¿Cómo estás?",
            "guarda en Jarvis que mi lámpara es azul", "recuerda que escucho jazz",
            "explícame cómo encender una luz", "¿Qué música recomiendas?",
            "pon un ejemplo de código",
        ]
        for prompt in actions:
            with self.subTest(prompt=prompt):
                self.assertEqual(classify_query(prompt, plugins)["kind"], "action")
        for prompt in conversation:
            with self.subTest(prompt=prompt):
                self.assertEqual(classify_query(prompt, plugins)["kind"], "assistant")


if __name__ == "__main__":
    unittest.main()
