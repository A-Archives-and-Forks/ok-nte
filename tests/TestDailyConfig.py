import unittest
from types import SimpleNamespace

from src.tasks.daily.DailyConfig import (
    COMPOSED_CONFIG_FORMAT,
    DailyConfigSchema,
    NamespacedConfigView,
    compose_config_key,
    register_composed_config_i18n,
)
from src.utils.i18n_format import match_i18n_format


class ConfigStub(dict):
    def __init__(self, default):
        super().__init__(default)
        self.default = default
        self.save_count = 0

    def get_default(self, key):
        return self.default.get(key)

    def save_file(self):
        self.save_count += 1


class TestDailyConfig(unittest.TestCase):
    def test_namespaced_views_isolate_same_local_config_key(self):
        config_name = "目标"
        alpha_key = compose_config_key("任务甲", config_name)
        beta_key = compose_config_key("任务乙", config_name)
        config = ConfigStub({alpha_key: "A", beta_key: "B"})
        alpha = NamespacedConfigView(config, "任务甲", {config_name}, {"runtime_value"})
        beta = NamespacedConfigView(config, "任务乙", {config_name}, set())

        alpha[config_name] = "A2"
        beta[config_name] = "B2"
        alpha["runtime_value"] = 1

        self.assertEqual(alpha[config_name], "A2")
        self.assertEqual(beta[config_name], "B2")
        self.assertEqual(config[alpha_key], "A2")
        self.assertEqual(config[beta_key], "B2")
        self.assertNotIn(compose_config_key("任务甲", "runtime_value"), config)

    def test_namespaced_view_rejects_undeclared_config_keys(self):
        config = ConfigStub({compose_config_key("任务甲", "目标"): "A"})
        view = NamespacedConfigView(config, "任务甲", {"目标"}, set())

        with self.assertRaisesRegex(KeyError, "undeclared Daily configuration key"):
            view["拼写错误"] = "value"

    def test_schema_qualifies_sub_configs_and_registers_i18n_format(self):
        schema = DailyConfigSchema("任务甲")
        schema.default_config.update({"模式": "A", "目标": "default"})
        schema.config_type["模式"] = {"sub_configs": {"A": "目标"}}
        target = SimpleNamespace(default_config={}, config_description={}, config_type={})

        top_level = schema.install(target)
        register_composed_config_i18n([schema])

        mode_key = compose_config_key("任务甲", "模式")
        target_key = compose_config_key("任务甲", "目标")
        self.assertEqual(top_level, [mode_key])
        self.assertEqual(target.config_type[mode_key]["sub_configs"]["A"], target_key)
        rule, match = match_i18n_format(target_key)
        self.assertEqual(rule.template, COMPOSED_CONFIG_FORMAT)
        self.assertEqual(match.groupdict(), {"task": "任务甲", "config": "目标"})
