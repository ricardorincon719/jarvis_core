import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)
import unittest

import router
from branches.music.agent import MusicAgent, normalize_text


class LofiAliasTest(unittest.TestCase):
    """Scribe escribe "lo-fi"; el router y el preset musical conocen "lofi"."""

    def test_router_reads_lo_fi_as_lofi(self):
        for text in ("Reproduce lo-fi.", "reproduce lo fi", "reproduce LO-FI"):
            self.assertEqual(router.normalize_text(text), "reproduce lofi", text)
        self.assertEqual(router.normalize_text("lo final"), "lo final")

    def test_music_preset_for_lo_fi(self):
        agent = object.__new__(MusicAgent)
        for text in ("reproduce lo-fi.", "reproduce lo fi", "reproduce lofi"):
            self.assertEqual(agent.resolve_query(normalize_text(text)), "lofi chill out", text)
        self.assertEqual(agent.resolve_query(normalize_text("reproduce la ofi")), "la ofi")


if __name__ == "__main__":
    unittest.main()
