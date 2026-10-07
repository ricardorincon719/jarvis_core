import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import os
import tempfile
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import brain_notify
import core
from action_proposals import ActionProposalStore
from test_action_confirmation_api import FakePlannedPlugin


class RouteLabelTest(unittest.TestCase):
    def test_labels_are_readable_and_deduplicated(self):
        self.assertEqual(brain_notify.route_label(["local_ia"]), "→ Nova")
        self.assertEqual(brain_notify.route_label(["music", "domotica", "music_local"]),
                         "→ música + domótica")
        self.assertEqual(brain_notify.route_label(["nuevo_plugin"]), "→ nuevo_plugin")


class PulseRouteTest(unittest.TestCase):
    def test_disabled_without_url(self):
        with patch.dict(os.environ, {"JINNEX_BRAIN_URL": ""}), \
                patch.object(brain_notify, "_post") as post:
            brain_notify.pulse_route("domotica")
            time.sleep(0.05)
        post.assert_not_called()

    def test_publishes_router_pulse_in_order_without_text(self):
        sent = []
        with patch.dict(os.environ, {"JINNEX_BRAIN_URL": "http://brain"}), \
                patch.object(brain_notify, "_post", sent.append):
            brain_notify.pulse_route("domotica")
            brain_notify.pulse_route("local_ia")
            deadline = time.time() + 2
            while len(sent) < 2 and time.time() < deadline:
                time.sleep(0.01)
        self.assertEqual(sent, [
            {"phase": "pulse", "region": "router", "source": "jarvis_core",
             "detail": "→ domótica"},
            {"phase": "pulse", "region": "router", "source": "jarvis_core",
             "detail": "→ Nova"},
        ])

    def test_unreachable_hub_never_raises(self):
        with patch.dict(os.environ, {"JINNEX_BRAIN_URL": "http://127.0.0.1:9/event"}):
            brain_notify._post({"phase": "pulse", "region": "router"})


class CoreRoutePulseTest(unittest.TestCase):
    def setUp(self):
        core.app.config.update(TESTING=True)
        self.client = core.app.test_client()
        self.headers = {"Authorization": f"Bearer {core.SECRET_TOKEN}"}
        plugins = {name: {"module": object()} for name in ("domotica", "music", "local_ia")}
        plugins_patch = patch.dict(core.plugins, plugins, clear=True)
        plugins_patch.start()
        self.addCleanup(plugins_patch.stop)

    def test_classification_flashes_the_chosen_route(self):
        with patch.object(core, "pulse_route") as pulse:
            self.client.post("/api/v1/route", json={"text": "apaga la luz"},
                             headers=self.headers)
            self.client.post("/api/v1/route", json={"text": "qué música te gusta"},
                             headers=self.headers)
        self.assertEqual([call.args for call in pulse.call_args_list],
                         [("domotica",), ("local_ia",)])

    def test_rejected_request_does_not_flash(self):
        with patch.object(core, "pulse_route") as pulse:
            self.client.post("/api/v1/route", json={"text": " "}, headers=self.headers)
            self.client.post("/api/v1/route", json={"text": "apaga la luz"})
        pulse.assert_not_called()



class ApprovalMessagesTest(unittest.TestCase):
    def test_waiting_and_decided_messages(self):
        sent = []
        with patch.object(brain_notify, "_send", sent.append):
            brain_notify.approval_waiting("p1", "music: play: jazz", 180)
            brain_notify.approval_decided("p1", False, "cancelada")
        self.assertEqual(sent, [
            {"phase": "start", "region": "aprobacion", "id": "core-proposal:p1",
             "source": "jarvis_core", "detail": "music: play: jazz", "ttl": 180},
            {"phase": "end", "id": "core-proposal:p1", "ok": False, "reason": "cancelada"},
        ])


class CoreApprovalTest(unittest.TestCase):
    """Una propuesta de Core enciende la aprobación hasta que se decide."""

    def setUp(self):
        core.app.config.update(TESTING=True)
        self.client = core.app.test_client()
        self.headers = {"Authorization": f"Bearer {core.SECRET_TOKEN}"}
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.module = FakePlannedPlugin("music", "play")
        plugins = {"music": {"module": self.module, "version": "test",
                             "description": "test", "triggers": []}}
        self.sent = []
        for target, value in (
                ("action_proposal_store",
                 ActionProposalStore(Path(temp_dir.name) / "actions.json")),
                ("plugins", plugins), ("route_query", lambda *a: "music"),
                ("pulse_route", lambda *a: None)):
            patcher = patch.object(core, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(brain_notify, "_send", self.sent.append)
        patcher.start()
        self.addCleanup(patcher.stop)

    def ask(self, text):
        return self.client.post("/ask", headers=self.headers, json={"pregunta": text})

    def test_confirmed_action_turns_approval_off_in_green(self):
        self.ask("reproduce jazz instrumental")
        self.ask("confirmado")
        start, end = self.sent
        self.assertEqual((start["phase"], start["region"]), ("start", "aprobacion"))
        self.assertIn("jazz", start["detail"])
        self.assertEqual(start["ttl"], core.action_proposal_store.ttl_seconds)
        self.assertEqual((end["id"], end["ok"]), (start["id"], True))
        self.assertEqual(self.module.executions, 1)

    def test_cancelled_action_turns_approval_off_in_red(self):
        self.ask("reproduce jazz instrumental")
        self.ask("cancela")
        self.assertEqual((self.sent[-1]["ok"], self.sent[-1]["reason"]), (False, "cancelada"))
        self.assertEqual(self.module.executions, 0)


if __name__ == "__main__":
    unittest.main()
