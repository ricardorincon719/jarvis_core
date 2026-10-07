import isolated_env  # noqa: F401  (antes que core: nunca leer el .env real)

from unittest.mock import patch
import unittest

from branches.hardware.current import plugin


class HardwarePlanTest(unittest.TestCase):
    def test_build_plan_does_not_execute_torch(self):
        with patch.object(plugin.subprocess, "run") as run:
            plan = plugin.build_plan("enciende la linterna")

        self.assertEqual(plan["actions"], [{"type": "torch_on"}])
        run.assert_not_called()

    def test_only_confirmed_plan_executes_allowlisted_command(self):
        plan = plugin.build_plan("enciende la linterna")

        with patch.object(plugin.subprocess, "run") as run:
            result = plugin.execute_confirmed_plan(plan, "enciende la linterna")

        run.assert_called_once_with(["termux-torch", "on"])
        self.assertTrue(result["ok"])

    def test_battery_is_classified_as_read_only(self):
        plan = plugin.build_plan("estado de la bateria")

        self.assertEqual(plan["actions"], [{"type": "battery_status"}])


if __name__ == "__main__":
    unittest.main()
