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

    def test_external_registry_generates_id_from_file_name(self):
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

        registry = CharRegistry(external_dir=external_dir)
        entry = registry.get("external:hero")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.source, "external")
        self.assertEqual(entry.char_cls.__name__, "FutureHero")
        self.assertEqual(entry.display_name("zh_CN"), "外置英雄")
        self.assertEqual(registry.get_external_impl_ids_by_class_name("FutureHero"), ["external:hero"])
        self.assertIsNone(registry.get("external:futurehero"))

    def test_v7_external_implementation_ids_migrate_to_paths(self):
        legacy = {
            "schema_version": 7,
            "combos": {},
            "characters": {
                "char_hero": {
                    "name": "Hero",
                    "impl_id": "external:futurehero",
                    "feature_ids": [],
                }
            },
            "features": {},
            "fixed_team": {
                "enabled": True,
                "slots": [{"char_id": "char_hero", "impl_id": "external:futurehero"}],
            },
        }
        with open(self.db_path, "w", encoding="utf-8") as file:
            json.dump(legacy, file)

        context = MigrationContext(
            is_builtin_impl=lambda impl_id: impl_id == "external:测试队伍/hero",
            get_builtin_prefix=lambda: "[built-in] ",
            iter_builtin_impl_items=lambda: [],
            generate_combo_id=lambda _existing: "combo_generated",
            get_external_impl_ids_by_class_name=lambda class_name: (
                ["external:测试队伍/hero"] if class_name == "futurehero" else []
            ),
        )
        CustomCharDb(self.db_path, self.features_dir, context)

        with open(self.db_path, encoding="utf-8") as file:
            persisted = json.load(file)
        self.assertEqual(persisted["characters"]["char_hero"]["impl_id"], "external:测试队伍/hero")
        self.assertEqual(
            persisted["fixed_team"]["slots"][0]["impl_id"], "external:测试队伍/hero"
        )

    def test_external_registry_scans_one_nested_folder_and_prefixes_display_name(self):
        external_dir = Path(self.temp_dir) / "external_chars"
        char_dir = external_dir / "测试队伍"
        char_dir.mkdir(parents=True)
        second_char_dir = external_dir / "备用队伍"
        second_char_dir.mkdir()
        (char_dir / "hero.py").write_text(
            "from src.char.BaseChar import BaseChar, Element\n"
            "\n"
            "class FutureHero(BaseChar):\n"
            "    cn_name = '真红'\n"
            "    en_name = 'Crimson'\n"
            "    element = Element.PURPLE\n",
            encoding="utf-8",
        )
        (second_char_dir / "hero.py").write_text(
            "from src.char.BaseChar import BaseChar, Element\n"
            "\n"
            "class FutureHero(BaseChar):\n"
            "    cn_name = '苍蓝'\n"
            "    en_name = 'Azure'\n"
            "    element = Element.BLUE\n",
            encoding="utf-8",
        )

        registry = CharRegistry(external_dir=external_dir)
        entry = registry.get("external:测试队伍/hero")
        second_entry = registry.get("external:备用队伍/hero")

        self.assertIsNotNone(entry)
        self.assertEqual(entry.display_name("zh_CN"), "测试队伍 - 真红")
        self.assertEqual(entry.display_name(), "测试队伍 - Crimson")
        self.assertIsNotNone(second_entry)
        self.assertEqual(second_entry.char_cls.__name__, entry.char_cls.__name__)
        self.assertEqual(second_entry.display_name("zh_CN"), "备用队伍 - 苍蓝")

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
        self.assertIsNotNone(registry.get("external:hero"))


if __name__ == "__main__":
    unittest.main()
