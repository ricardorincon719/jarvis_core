import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

import tempfile
from pathlib import Path
import unittest

from action_proposals import (
    ActionProposalStore,
    ProposalAccessDenied,
    ProposalStateError,
)


class ActionProposalStoreTest(unittest.TestCase):
    def setUp(self):
        self.now = 1_000.0
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = ActionProposalStore(
            Path(self.temp_dir.name) / "actions.json",
            ttl_seconds=15,
            clock=lambda: self.now,
        )
        self.phone = {"type": "device", "id": "phone-1", "name": "Phone"}

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_accept_claim_is_idempotent_and_bound_to_owner(self):
        proposal = self.store.create(
            "plugin_plan",
            {"plugin": "domotica", "plan": {"actions": [{"type": "turn_on"}]}},
            "encender luz",
            self.phone,
        )

        with self.assertRaises(ProposalAccessDenied):
            self.store.claim(
                proposal["id"],
                "accept",
                "other-device",
                {"type": "device", "id": "phone-2"},
            )

        claimed, changed = self.store.claim(proposal["id"], "accept", "decision-1", self.phone)
        replay, replay_changed = self.store.claim(proposal["id"], "accept", "decision-1", self.phone)

        self.assertTrue(changed)
        self.assertEqual(claimed["status"], "executing")
        self.assertFalse(replay_changed)
        self.assertEqual(replay["idempotency_key"], "decision-1")

        with self.assertRaises(ProposalStateError):
            self.store.claim(proposal["id"], "accept", "decision-2", self.phone)

    def test_expired_proposal_cannot_execute(self):
        proposal = self.store.create(
            "plugin_plan",
            {"plugin": "music", "plan": {"actions": [{"type": "play", "query": "jazz"}]}},
            "reproducir jazz",
            self.phone,
        )
        self.now += 16

        self.assertEqual(self.store.list_pending(self.phone), [])
        with self.assertRaises(ProposalStateError):
            self.store.claim(proposal["id"], "accept", "late", self.phone)

    def test_duplicate_pending_plan_is_reused(self):
        plan = {"plugin": "domotica", "plan": {"actions": [{"type": "turn_off"}]}}
        first = self.store.create("plugin_plan", plan, "apagar luz", self.phone)
        second = self.store.create("plugin_plan", plan, "apagar luz", self.phone)

        self.assertEqual(first["id"], second["id"])

    def test_new_plan_supersedes_previous_pending_plan_for_same_owner(self):
        first = self.store.create(
            "plugin_plan",
            {"plugin": "domotica", "plan": {"actions": [{"type": "turn_on"}]}},
            "encender luz",
            self.phone,
        )
        second = self.store.create(
            "plugin_plan",
            {"plugin": "domotica", "plan": {"actions": [{"type": "turn_off"}]}},
            "apagar luz",
            self.phone,
        )

        self.assertEqual([item["id"] for item in self.store.list_pending(self.phone)], [second["id"]])
        with self.assertRaises(ProposalStateError) as error:
            self.store.claim(first["id"], "accept", "stale-decision", self.phone)
        self.assertEqual(str(error.exception), "proposal_cancelled")

    def test_natural_lookup_does_not_mix_master_and_device_ownership(self):
        phone_proposal = self.store.create(
            "plugin_plan",
            {"plugin": "domotica", "plan": {"actions": [{"type": "turn_on"}]}},
            "encender luz",
            self.phone,
        )
        master = {"type": "master", "id": "master"}
        master_proposal = self.store.create(
            "plugin_plan",
            {"plugin": "hardware", "plan": {"actions": [{"type": "vibrate"}]}},
            "vibrar",
            master,
        )

        self.assertEqual(len(self.store.list_pending(master)), 2)
        owned = self.store.list_pending(master, include_all_for_master=False)
        self.assertEqual([item["id"] for item in owned], [master_proposal["id"]])
        self.assertNotEqual(phone_proposal["id"], master_proposal["id"])


if __name__ == "__main__":
    unittest.main()
