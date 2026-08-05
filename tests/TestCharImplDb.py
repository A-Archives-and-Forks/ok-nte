import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from src.char.core.CharRegistry import CharRegistry, char_registry
from src.char.custom.CustomCharDb import DB_SCHEMA_VERSION, CustomCharDb
from src.char.custom.CustomCharDbMigrator import MigrationContext
from src.char.Zero import Zero


class TestCharImplDb(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "db.json")
        self.features_dir = os.path.join(self.temp_dir, "features")
        os.makedirs(self.features_dir)
        CustomCharDb.reset_instance()
        self.context = MigrationContext(
            is_builtin_impl=lambda impl_id: str(impl_id).startswith("builtin:"),
            get_builtin_prefix=lambda: "[built-in] ",
            iter_builtin_impl_items=lambda: [("Zero", "builtin:zero")],
            generate_combo_id=lambda _existing: "combo_generated",
        )

    def tearDown(self):
        CustomCharDb.reset_instance()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_v6_records_migrate_to_impl_ids(self):
        legacy = {
            "schema_version": 6,
            "combos": {"combo_text": {"name": "Text", "content": "skill"}},
            "characters": {
                "char_builtin": {"name": "Zero", "combo_id": "char_zero", "feature_ids": []},
                "char_custom": {"name": "Custom", "combo_id": "combo_text", "feature_ids": []},
            },
            "features": {},
            "fixed_team": {
                "enabled": True,
                "slots": [{"char_id": "char_builtin", "combo_id": "char_zero"}],
            },
        }
        with open(self.db_path, "w", encoding="utf-8") as file:
            json.dump(legacy, file)

        database = CustomCharDb(self.db_path, self.features_dir, self.context)

        with open(self.db_path, encoding="utf-8") as file:
            persisted = json.load(file)
        self.assertEqual(persisted["schema_version"], DB_SCHEMA_VERSION)
        self.assertEqual(persisted["characters"]["char_builtin"]["impl_id"], "builtin:zero")
        self.assertEqual(persisted["characters"]["char_custom"]["impl_id"], "combo_text")
        self.assertNotIn("combo_id", persisted["characters"]["char_builtin"])
        self.assertEqual(database.get_fixed_team()["slots"][0]["impl_id"], "builtin:zero")

    def test_builtin_registry_generates_id_from_the_character_module(self):
        entry = char_registry.get("builtin:zero")

        self.assertIsNotNone(entry)
        self.assertIs(entry.char_cls, Zero)
        self.assertEqual(entry.cn_name, "零")

    def test_external_registry_generates_id_from_class_name(self):
        external_dir = Path(self.temp_dir) / "external_chars"
        external_dir.mkdir()
        (external_dir / "hero.py").write_text(
            "from src.char.BaseChar import BaseChar, Element\n"
            "\n"
            "class FutureHero(BaseChar):\n"
            "    cn_name = '外置英雄'\n"
            "    en_name = 'Future Hero'\n"
            "    element = Element.PURPLE\n",
            encoding="utf-8",
        )

        entry = CharRegistry(external_dir=external_dir).get("external:futurehero")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.source, "external")
        self.assertEqual(entry.char_cls.__name__, "FutureHero")
        self.assertEqual(entry.display_name("zh_CN"), "外置英雄")

    def test_external_registry_rescan_does_not_reload_builtins(self):
        external_dir = Path(self.temp_dir) / "external_chars"
        external_dir.mkdir()
        registry = CharRegistry(external_dir=external_dir)
        builtin_entry = registry.get("builtin:zero")

        (external_dir / "hero.py").write_text(
            "from src.char.BaseChar import BaseChar, Element\n"
            "\n"
            "class FutureHero(BaseChar):\n"
            "    cn_name = '外置英雄'\n"
            "    en_name = 'Future Hero'\n"
            "    element = Element.PURPLE\n",
            encoding="utf-8",
        )

        registry.rescan_external()

        self.assertIs(registry.get("builtin:zero"), builtin_entry)
        self.assertIsNotNone(registry.get("external:futurehero"))


if __name__ == "__main__":
    unittest.main()
