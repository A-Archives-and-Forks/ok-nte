from __future__ import annotations

from collections import defaultdict
from collections.abc import MutableMapping
from typing import Any

from ok.util.config import Config
from ok.util.file import get_relative_path, read_json_file, write_json_file

from src.tasks.daily.DailyConfig import compose_config_key

# Add a current NAME -> prior NAME mapping here only when a Daily child is renamed.
# NAME remains the sole runtime identifier and persistent namespace.
LEGACY_TASK_NAMES: dict[str, tuple[str, ...]] = {}


class DailyConfigMigrator:
    """Migrate known DailyTask configuration layouts before Config validates them.

    The previous Daily layout stored child settings as flat keys. A flat key can
    only be migrated when exactly one Daily child owns it. Ambiguous keys are
    intentionally left untouched so configuration validation can safely discard
    them instead of assigning a value to the wrong child task.
    """

    def __init__(
        self,
        task: Any,
    ):
        self.task = task
        self.schemas = tuple(task._daily_config_schemas.values())
        self.legacy_names = LEGACY_TASK_NAMES
        self.reserved_keys = frozenset(task.default_config) - {
            compose_config_key(schema.task_name, config_name)
            for schema in self.schemas
            for config_name in schema.config_keys
        }

    def migrate(self) -> bool:
        """Migrate this task's JSON file before BaseTask creates its Config object."""
        config_file = get_relative_path(
            Config.config_folder,
            f"{self.task.__class__.__name__}.json",
        )
        return self.migrate_file(config_file)

    def migrate_file(self, config_file: str) -> bool:
        """Migrate one Daily JSON file in place when its contents are valid JSON."""
        values = read_json_file(config_file)
        if not isinstance(values, dict) or not self.migrate_values(values):
            return False
        write_json_file(config_file, values)
        return True

    def migrate_values(self, values: MutableMapping[str, Any]) -> bool:
        """Migrate an already loaded JSON object without replacing current values."""
        changed = self._migrate_legacy_namespaces(values)
        return self._migrate_unique_flat_keys(values) or changed

    def _migrate_legacy_namespaces(self, values: MutableMapping[str, Any]) -> bool:
        changed = False
        for schema in self.schemas:
            for legacy_name in self.legacy_names.get(schema.task_name, ()):
                if legacy_name == schema.task_name:
                    continue
                for config_name in schema.config_keys:
                    source_key = compose_config_key(legacy_name, config_name)
                    if source_key not in values:
                        continue
                    target_key = compose_config_key(schema.task_name, config_name)
                    if target_key not in values:
                        values[target_key] = values[source_key]
                    del values[source_key]
                    changed = True
        return changed

    def _migrate_unique_flat_keys(self, values: MutableMapping[str, Any]) -> bool:
        owners = defaultdict(list)
        for schema in self.schemas:
            for config_name in schema.config_keys:
                owners[config_name].append(schema)

        changed = False
        for config_name, schemas in owners.items():
            if config_name in self.reserved_keys or len(schemas) != 1 or config_name not in values:
                continue
            schema = schemas[0]
            target_key = compose_config_key(schema.task_name, config_name)
            if target_key not in values:
                values[target_key] = values[config_name]
            del values[config_name]
            changed = True
        return changed
