import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openrouter_adapter import budget_lock, reserve_budget, settle_budget


class BudgetTests(unittest.TestCase):
    def test_reservations_survive_restarts_and_stop_before_limit(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'budget.json'
            for _ in range(7):
                reserve_budget(path)
            with self.assertRaises(RuntimeError):
                reserve_budget(path)
            self.assertEqual(len(json.loads(path.read_text())['entries']), 7)

    def test_reported_cost_releases_reserve_and_unknown_cost_retains_it(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'budget.json'
            identifier = reserve_budget(path)
            settle_budget(identifier, None, path)
            self.assertEqual(json.loads(path.read_text())['entries'][0]['charged_or_reserved_usd'], '0.12')
            settle_budget(identifier, 0.001, path)
            self.assertEqual(json.loads(path.read_text())['entries'][0]['charged_or_reserved_usd'], '0.001')
            settle_budget(identifier, 0.13, path)
            with self.assertRaises(RuntimeError):
                reserve_budget(path)

    def test_concurrent_access_fails_closed(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / 'budget.json'
            with budget_lock(path), self.assertRaises(RuntimeError):
                reserve_budget(path)


if __name__ == '__main__':
    unittest.main()
