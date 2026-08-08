import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.tasks.daily.DailyConfig import DailyConfigSchema, compose_config_key
from src.tasks.daily.DailyConfigMigrator import LEGACY_TASK_NAMES, DailyConfigMigrator


class TestDailyConfigMigrator(unittest.TestCase):
    def test_migrates_unique_flat_keys_and_renamed_namespaces_without_overwrite(self):
        primary = DailyConfigSchema("新任务")
        primary.default_config.update({"独有": 0, "改名设置": 0, "重复设置": 0})
        other = DailyConfigSchema("另一任务")
        other.default_config["重复设置"] = 0
        current_renamed_key = compose_config_key("新任务", "改名设置")
        legacy_renamed_key = compose_config_key("旧任务", "改名设置")
        values = {
            "独有": 1,
            "重复设置": 2,
            current_renamed_key: 3,
            legacy_renamed_key: 4,
        }

        task = SimpleNamespace(
            _daily_config_schemas={"新任务": primary, "另一任务": other},
            default_config={},
        )

        with patch.dict(LEGACY_TASK_NAMES, {"新任务": ("旧任务",)}, clear=True):
            changed = DailyConfigMigrator(task).migrate_values(values)

        self.assertTrue(changed)
        self.assertEqual(values[compose_config_key("新任务", "独有")], 1)
        self.assertEqual(values[current_renamed_key], 3)
        self.assertNotIn("独有", values)
        self.assertNotIn(legacy_renamed_key, values)
        self.assertEqual(values["重复设置"], 2)
