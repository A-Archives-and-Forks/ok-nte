from __future__ import annotations

from collections.abc import Iterator, MutableMapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol

from src.utils.i18n_format import register_i18n_format

COMPOSED_CONFIG_FORMAT = "{task} · {config}"


class DailyConfigurable(Protocol):
    """Contract for a task that can contribute configuration to DailyTask."""

    NAME: ClassVar[str]

    @classmethod
    def setup_config(cls, instance: "DailyConfigSchema", *, daily: bool = False) -> None: ...


def compose_config_key(task_name: str, config_name: str) -> str:
    return COMPOSED_CONFIG_FORMAT.format(task=task_name, config=config_name)


@dataclass
class DailyConfigSchema:
    """Collect one child task's local configuration before installing it on DailyTask."""

    task_name: str
    default_config: dict[str, Any] = field(default_factory=dict)
    config_description: dict[str, str] = field(default_factory=dict)
    config_type: dict[str, Any] = field(default_factory=dict)
    runtime_keys: set[str] = field(default_factory=set)

    @property
    def config_keys(self) -> set[str]:
        return set(self._ordered_config_keys())

    @property
    def top_level_keys(self) -> list[str]:
        nested_keys = set()
        for config in self.config_type.values():
            nested_keys.update(_sub_config_keys(config))
        return [key for key in self._ordered_config_keys() if key not in nested_keys]

    def _ordered_config_keys(self) -> list[str]:
        return list(
            dict.fromkeys([*self.default_config, *self.config_description, *self.config_type])
        )

    def add_runtime_keys(self, *keys: str) -> None:
        self.runtime_keys.update(keys)

    def install(self, task) -> list[str]:
        """Install this schema on DailyTask and return its qualified top-level keys."""
        task.default_config.update(
            {
                compose_config_key(self.task_name, key): value
                for key, value in self.default_config.items()
            }
        )
        task.config_description.update(
            {
                compose_config_key(self.task_name, key): value
                for key, value in self.config_description.items()
            }
        )
        task.config_type.update(
            {
                compose_config_key(self.task_name, key): _qualify_config_type(value, self.task_name)
                for key, value in self.config_type.items()
            }
        )
        return [compose_config_key(self.task_name, key) for key in self.top_level_keys]


class NamespacedConfigView(MutableMapping[str, Any]):
    """Expose a DailyTask configuration namespace through a child's local keys."""

    def __init__(
        self,
        config,
        task_name: str,
        declared_keys: set[str],
        runtime_keys: set[str],
    ):
        self._config = config
        self.task_name = task_name
        self._declared_keys = declared_keys
        self._runtime_keys = runtime_keys
        self._runtime_values: dict[str, Any] = {}
        # BaseNTETask.sync_config uses this to refresh the visible DailyTask card.
        self.ui_config = config

    def _key(self, key: str) -> str:
        return compose_config_key(self.task_name, key)

    def __getitem__(self, key: str) -> Any:
        if key in self._declared_keys:
            return self._config[self._key(key)]
        self._ensure_runtime_key(key)
        return self._runtime_values[key]

    def __setitem__(self, key: str, value: Any) -> None:
        if key in self._declared_keys:
            self._config[self._key(key)] = value
        else:
            self._ensure_runtime_key(key)
            self._runtime_values[key] = value

    def __delitem__(self, key: str) -> None:
        if key in self._declared_keys:
            del self._config[self._key(key)]
        else:
            self._ensure_runtime_key(key)
            del self._runtime_values[key]

    def __iter__(self) -> Iterator[str]:
        for key in self._declared_keys:
            if self._key(key) in self._config:
                yield key
        yield from self._runtime_values

    def __len__(self) -> int:
        return sum(1 for _ in self)

    def get(self, key: str, default=None):
        if key in self._declared_keys:
            return self._config.get(self._key(key), default)
        self._ensure_runtime_key(key)
        return self._runtime_values.get(key, default)

    def get_default(self, key: str):
        if key not in self._declared_keys:
            self._ensure_runtime_key(key)
            return None
        return self._config.get_default(self._key(key))

    def save_file(self):
        self._config.save_file()

    def has_user_config(self):
        return any(not key.startswith("_") for key in self)

    def _ensure_runtime_key(self, key: str) -> None:
        if key not in self._runtime_keys:
            raise KeyError(f"{self.task_name} used undeclared Daily configuration key: {key}")


def register_composed_config_i18n(schemas: list[DailyConfigSchema]) -> None:
    task_names = [schema.task_name for schema in schemas]
    config_names = sorted({key for schema in schemas for key in schema.config_keys})
    if task_names and config_names:
        register_i18n_format(
            COMPOSED_CONFIG_FORMAT,
            translated_fields=frozenset({"task", "config"}),
            allowed_values={"task": task_names, "config": config_names},
            translate_template=False,
        )


def _qualify_config_type(value: Any, task_name: str) -> Any:
    value = deepcopy(value)
    if not isinstance(value, dict):
        return value
    sub_configs = value.get("sub_configs")
    if isinstance(sub_configs, dict):
        value["sub_configs"] = {
            option: _qualify_sub_config_keys(keys, task_name)
            for option, keys in sub_configs.items()
        }
    for key, nested_value in value.items():
        if key != "sub_configs":
            value[key] = _qualify_config_type(nested_value, task_name)
    return value


def _qualify_sub_config_keys(keys: Any, task_name: str) -> Any:
    if isinstance(keys, str):
        return compose_config_key(task_name, keys)
    if isinstance(keys, (list, tuple, set)):
        return [compose_config_key(task_name, key) for key in keys]
    return keys


def _sub_config_keys(value: Any) -> set[str]:
    if not isinstance(value, dict):
        return set()
    keys = set()
    sub_configs = value.get("sub_configs")
    if isinstance(sub_configs, dict):
        for config_keys in sub_configs.values():
            if isinstance(config_keys, str):
                keys.add(config_keys)
            elif isinstance(config_keys, (list, tuple, set)):
                keys.update(config_keys)
    for key, nested_value in value.items():
        if key != "sub_configs":
            keys.update(_sub_config_keys(nested_value))
    return keys
