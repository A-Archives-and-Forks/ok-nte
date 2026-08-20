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
        self.assertNotIn("fixed_team", persisted)
        self.assertEqual(persisted["team_presets"][0]["name"], "固定队伍")
        self.assertTrue(persisted["team_presets"][0]["is_fixed"])
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
            persisted["team_presets"][0]["slots"][0]["impl_id"], "external:测试队伍/hero"
        )

    def test_presets_apply_and_fixed_projection(self):
        database = CustomCharDb(self.db_path, self.features_dir, self.context)
        combo_a = database.add_combo("A", "skill")
        combo_b = database.add_combo("B", "ultimate")
        char_a = database.create_character("A", combo_a)
        char_b = database.create_character("B", combo_a)
        preset = database.create_team_preset("Boss")
        self.assertTrue(
            database.update_team_preset(
                preset["id"],
                slots=[
                    {"char_id": char_a, "impl_id": combo_b},
                    {"char_id": char_b, "impl_id": ""},
                ],
            )
        )

        self.assertEqual(database.apply_team_preset(preset["id"]), [char_a])
        self.assertEqual(database.get_character_record(char_a)["impl_id"], combo_b)
        self.assertEqual(database.get_character_record(char_b)["impl_id"], combo_a)
        self.assertEqual(database.apply_team_preset(preset["id"], fixed=True), [char_a])
        self.assertTrue(database.get_fixed_team()["enabled"])
        self.assertEqual(database.get_fixed_team()["slots"][0]["char_id"], char_a)
        self.assertTrue(database.clear_fixed_team_preset())
        self.assertFalse(database.get_fixed_team()["enabled"])

    def test_presets_reject_duplicates_and_clean_deleted_references(self):
        database = CustomCharDb(self.db_path, self.features_dir, self.context)
        combo_id = database.add_combo("A", "skill")
        char_id = database.create_character("A", combo_id)
        preset = database.create_team_preset("Team")
        duplicate_slots = [
            {"char_id": char_id, "impl_id": combo_id},
            {"char_id": char_id, "impl_id": combo_id},
        ]
        self.assertFalse(database.update_team_preset(preset["id"], slots=duplicate_slots))
        self.assertTrue(
            database.update_team_preset(
                preset["id"], slots=[{"char_id": char_id, "impl_id": combo_id}]
            )
        )
        database.delete_combo(combo_id)
        self.assertEqual(database.get_team_presets()[0]["slots"][0]["impl_id"], "")
        database.delete_character(char_id)
        self.assertEqual(database.get_team_presets()[0]["slots"][0], {"char_id": "", "impl_id": ""})

    def test_failed_preset_update_does_not_apply_the_name(self):
        database = CustomCharDb(self.db_path, self.features_dir, self.context)
        char_id = database.create_character("A", "")
        preset = database.create_team_preset("Before")

        self.assertFalse(
            database.update_team_preset(
                preset["id"],
                name="After",
                slots=[{"char_id": char_id}, {"char_id": char_id}],
            )
        )
        self.assertEqual(database.get_team_presets()[0]["name"], "Before")

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
