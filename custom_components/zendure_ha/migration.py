"""Migration helpers for Zendure integration."""

import logging
from functools import partial
from pathlib import Path

from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state as rs
from homeassistant.helpers.event import async_call_later

from .const import DOMAIN
from .entity import snakecase

_LOGGER = logging.getLogger(__name__)


class Migration:
    """Handles device/entity rename migrations."""

    _changes: list[tuple[str, str]] = []
    _update: CALLBACK_TYPE | None = None

    @staticmethod
    def check_device(hass: HomeAssistant, device_id: str, name: str, model: str, sn: str) -> None:
        """Check and migrate device identifiers for Zendure integration."""
        device_registry = dr.async_get(hass)

        fallback = f"{model.replace(' ', '').replace('SolarFlow', 'Sf')} {sn[-3:] if sn is not None else ''}".strip()
        unique = "".join(name.split())
        identifier = device_id or name
        if not identifier:
            return

        existing = device_registry.async_get_device(identifiers={(DOMAIN, identifier)})
        if existing is None:
            for ident in [name, name.lower(), unique, fallback, fallback.lower()]:
                existing = device_registry.async_get_device(identifiers={(DOMAIN, ident)})
                if existing is not None:
                    break

        if not existing:
            return

        # check for wrong identifier
        if next(iter(existing.identifiers))[1] != device_id:
            _LOGGER.warning("Migrating device '%s' -> name='%s' id='%s'", existing.name, name, device_id)
            device_registry.async_update_device(existing.id, new_identifiers={(DOMAIN, device_id)})

        # check for name change
        if name != existing.name:
            _LOGGER.warning("Migrating device '%s' -> name='%s' id='%s'", existing.name, name, device_id)
            device_registry.async_update_device(existing.id, name=name, name_by_user=None)
            entity_registry = er.async_get(hass)
            entities = er.async_entries_for_device(entity_registry, existing.id, True)
            data = rs.async_get(hass)
            changes: list[tuple[str, str]] = []
            for entity in entities:
                try:
                    uniqueid = snakecase(entity.translation_key)
                    if uniqueid.startswith("aggr") and uniqueid.endswith("total"):
                        uniqueid = uniqueid.replace("_total", "")
                    unique_id = snakecase(f"{name.lower()}_{uniqueid}")
                    entityid = f"{entity.domain}.{unique_id}"

                    if entity.entity_id != entityid or entity.unique_id != unique_id or entity.translation_key != uniqueid:
                        if entity.entity_id != entityid:
                            entity_registry.async_remove(entityid)
                        if (rstate := data.last_states.pop(entity.entity_id, None)) is not None:
                            data.last_states[entityid] = rstate

                        entity_registry.async_update_entity(
                            entity.entity_id,
                            new_unique_id=unique_id,
                            new_entity_id=entityid,
                            translation_key=uniqueid,
                        )

                        _LOGGER.debug("Updated entity %s unique_id to %s", entity.entity_id, uniqueid)
                        changes.append((entity.entity_id, entityid))
                except Exception as e:
                    _LOGGER.error("Failed to update entity %s: %s", entity.entity_id, e)
            if changes:
                if Migration._update is not None:
                    Migration._update()
                Migration._changes.extend(changes)
                Migration._update = async_call_later(hass, 60, partial(Migration._migrate_updater, hass))

    @staticmethod
    async def _migrate_updater(hass: HomeAssistant, _now) -> None:  # noqa: PLR0915
        """Update files who uses the old entity IDs."""
        changes = Migration._changes
        Migration._changes = []
        modified = 0
        try:
            for entry in hass.config_entries.async_entries():
                new_data = dict(entry.data or {})
                new_options = dict(entry.options or {})
                if len(new_data) == 0 and len(new_options) == 0:
                    continue

                def change_id(data: dict, oid: str, nid: str) -> bool:
                    changed = False
                    for key, value in data.items():
                        if isinstance(value, dict):
                            changed |= change_id(value, oid, nid)
                        elif isinstance(value, list):
                            for i, item in enumerate(value):
                                if isinstance(item, str) and oid in item:
                                    value[i] = item.replace(oid, nid)
                                    changed = True
                        elif isinstance(value, str) and oid in value:
                            data[key] = value.replace(oid, nid)
                            changed = True
                    return changed

                changed = False
                for oid, nid in changes:
                    changed |= change_id(new_data, oid, nid)
                    changed |= change_id(new_options, oid, nid)

                if changed:
                    hass.config_entries.async_update_entry(entry, data=new_data, options=new_options)
                    if entry.state.recoverable:
                        await hass.config_entries.async_reload(entry.entry_id)
                    modified += 1

            def _update_files() -> bool:
                file_modified = False

                def update_file(path: Path) -> None:
                    nonlocal file_modified
                    try:
                        content = path.read_text(encoding="utf-8")
                        updated = content
                        for old_id, new_id in changes:
                            updated = updated.replace(old_id, new_id)
                        if updated != content:
                            path.write_text(updated, encoding="utf-8")
                            file_modified = True
                    except Exception as e:
                        _LOGGER.error("Error migrating file %s: %s", path, e)

                storage_dir = Path(hass.config.path(".storage"))
                relevant_files = ["core.automation", "lovelace", "energy"]
                for path in storage_dir.iterdir():
                    if any(path.name.startswith(f) for f in relevant_files):
                        update_file(path)

                config_path = Path(hass.config.config_dir)
                for path in config_path.rglob("*"):
                    if path.is_dir():
                        continue
                    if any(part.startswith(".") for part in path.relative_to(config_path).parts):
                        continue
                    if path.suffix in (".yaml", ".json"):
                        update_file(path)

                return file_modified

            if await hass.async_add_executor_job(_update_files):
                await rs.RestoreStateData.async_save_persistent_states(hass)
        except Exception as e:
            _LOGGER.error("Error during migration: %s", e)
        _LOGGER.info("Migration completed: %d entity changes", len(changes))


# async def migrate_entities(hass: HomeAssistant, device_id: str, device_name: str) -> None:
#     """Migrate the device entities."""
#     entity_registry = er.async_get(hass)
#     entities = er.async_entries_for_device(entity_registry, device_id, True)
#     data = rs.async_get(hass)
#     changes: list[tuple[str, str]] = []
#     for entity in entities:
#         try:
#             uniqueid = snakecase(entity.translation_key)
#             if uniqueid.startswith("aggr") and uniqueid.endswith("total"):
#                 uniqueid = uniqueid.replace("_total", "")
#             unique_id = snakecase(f"{device_name.lower()}_{uniqueid}")
#             entityid = f"{entity.domain}.{unique_id}"

#             if entity.entity_id != entityid or entity.unique_id != unique_id or entity.translation_key != uniqueid:
#                 if entity.entity_id != entityid:
#                     entity_registry.async_remove(entityid)
#                 if (rstate := data.last_states.pop(entity.entity_id, None)) is not None:
#                     data.last_states[entityid] = rstate

#                 entity_registry.async_update_entity(
#                     entity.entity_id,
#                     new_unique_id=unique_id,
#                     new_entity_id=entityid,
#                     translation_key=uniqueid,
#                 )

#                 _LOGGER.debug("Updated entity %s unique_id to %s", entity.entity_id, uniqueid)
#                 changes.append((entity.entity_id, entityid))
#         except Exception as e:
#             _LOGGER.error("Failed to update entity %s: %s", entity.entity_id, e)

#     if len(changes) != 0:
#         await migrate_files(hass, changes)


# @staticmethod
# async def migrate_files(hass: HomeAssistant, changes: list[tuple[str, str]]) -> None:
#     """Update files who uses the old entity IDs."""
#     modified = 0
#     try:
#         for entry in hass.config_entries.async_entries():
#             new_data = dict(entry.data or {})
#             new_options = dict(entry.options or {})
#             if len(new_data) == 0 and len(new_options) == 0:
#                 continue

#             def change_id(data: dict, oid: str, nid: str) -> bool:
#                 changed = False
#                 for key, value in data.items():
#                     if isinstance(value, dict):
#                         change_id(value, oid, nid)
#                         changed = True
#                     elif isinstance(value, list):
#                         for i, item in enumerate(value):
#                             if isinstance(item, str) and oid in item:
#                                 value[i] = item.replace(oid, nid)
#                                 changed = True
#                     elif isinstance(value, str) and oid in value:
#                         data[key] = value.replace(oid, nid)
#                         changed = True
#                 return changed

#             changed = False
#             for oid, nid in changes:
#                 changed |= change_id(new_data, oid, nid)
#                 changed |= change_id(new_options, oid, nid)

#             if changed:
#                 hass.config_entries.async_update_entry(entry, data=new_data, options=new_options)
#                 if entry.state.recoverable:
#                     await hass.config_entries.async_reload(entry.entry_id)
#                 modified += 1

#         def update_file(path: Path) -> None:
#             try:
#                 content = path.read_text(encoding="utf-8")
#                 modified = content
#                 for old_id, new_id in changes:
#                     modified = modified.replace(old_id, new_id)
#                 if modified != content:
#                     modified += 1
#                     path.write_text(modified, encoding="utf-8")
#             except Exception as e:
#                 _LOGGER.error("Error migrating file %s: %s", path, e)

#         modified = 0
#         storage_dir = Path(hass.config.path(".storage"))
#         relevant_files = ["core.automation", "lovelace", "energy"]
#         for path in storage_dir.iterdir():  # noqa: ASYNC240
#             if any(path.name.startswith(f) for f in relevant_files):
#                 update_file(path)

#         config_path = Path(hass.config.config_dir)
#         for path in config_path.rglob("*"):  # noqa: ASYNC240
#             if path.is_dir() and path.name.startswith("."):
#                 continue
#             if path.suffix in (".yaml", ".json"):
#                 update_file(path)

#         if modified != 0:
#             await rs.RestoreStateData.async_save_persistent_states(hass)
#             hass.async_create_task(hass.config_entries.async_reload(entry.entry_id))
#     except Exception as e:
#         _LOGGER.error("Error during migration: %s", e)
#     _LOGGER.info("Migration completed: %d entity changes", len(changes))


# class Migration:
#     """Handles device/entity rename migrations."""

#     def __init__(self, hass: HomeAssistant, entry_id: str, domain: str) -> None:
#         """Initialize with registries and existing devices."""
#         self.hass = hass
#         self.domain = domain
#         self.device_registry = dr.async_get(hass)
#         self.entity_registry = er.async_get(hass)
#         self.existing_devices = dr.async_entries_for_config_entry(self.device_registry, entry_id)
#         self.changes: list[tuple[str, str]] = []

#     def check_rename(self, device_id: str, name: str, model: str, sn: str) -> None:

#         # Use sn as stable device identifier; migrate from old name-based identifiers
#         fallback = f"{model.replace(' ', '').replace('SolarFlow', 'Sf')} {sn[-3:] if sn is not None else ''}".strip()
#         unique = "".join(name.split())
#         identifier = device_id or name
#         if not identifier:
#             return

#         existing = self.device_registry.async_get_device(identifiers={(DOMAIN, identifier)})
#         if existing is None:
#             for ident in [name, name.lower(), unique, fallback, fallback.lower()]:
#                 existing = self.device_registry.async_get_device(identifiers={(DOMAIN, ident)})
#                 if existing is not None:
#                     break

#         # check for rename
#         if existing is not None and next(iter(existing.identifiers))[1] != device_id:
#             _LOGGER.warning("Migrating device '%s' -> name='%s' id='%s'", existing.name, name, device_id)
#             self.device_registry.async_update_device(existing.id, name=name, new_identifiers={(DOMAIN, device_id)})
#             self._migrate_entities(existing.id, name)

#             children = [device for device in self.device_registry.devices.values() if device.via_device_id == device_id]
#             for child in children:
#                 _LOGGER.warning("Migrating child device '%s' -> name='%s' id='%s'", child.name, name, device_id)
#                 self.device_registry.async_update_device(child.id, name=name, new_identifiers={(DOMAIN, device_id)})

#     def _migrate_entities(self, deviceid: str, device_name: str) -> None:
#         """Rename all entities for a device to match the new device name."""
#         entities = er.async_entries_for_device(self.entity_registry, deviceid, True)
#         data = rs.async_get(self.hass)
#         for entity in entities:
#             try:
#                 if entity.platform != self.domain:
#                     continue

#                 uniqueid = snakecase(entity.translation_key)
#                 if uniqueid.startswith("aggr") and uniqueid.endswith("total"):
#                     uniqueid = uniqueid.replace("_total", "")
#                 unique_id = snakecase(f"{device_name.lower()}_{uniqueid}")
#                 entityid = f"{entity.domain}.{unique_id}"

#                 if entity.entity_id != entityid or entity.unique_id != unique_id or entity.translation_key != uniqueid:
#                     if entity.entity_id != entityid:
#                         self.entity_registry.async_remove(entityid)
#                     if (rstate := data.last_states.pop(entity.entity_id, None)) is not None:
#                         data.last_states[entityid] = rstate

#                     self.entity_registry.async_update_entity(
#                         entity.entity_id,
#                         new_unique_id=unique_id,
#                         new_entity_id=entityid,
#                         translation_key=uniqueid,
#                     )

#                     _LOGGER.debug("Updated entity %s unique_id to %s", entity.entity_id, uniqueid)
#                     self.changes.append((entity.entity_id, entityid))
#             except Exception as e:
#                 _LOGGER.error("Failed to update entity %s: %s", entity.entity_id, e)

#         # update template config entries
#         modified = 0
#         for entry in self.hass.config_entries.async_entries():
#             new_data = dict(entry.data or {})
#             new_options = dict(entry.options or {})
#             if len(new_data) == 0 and len(new_options) == 0:
#                 continue

#             def change_id(data: dict, oid: str, nid: str) -> bool:
#                 changed = False
#                 for key, value in data.items():
#                     if isinstance(value, dict):
#                         change_id(value, oid, nid)
#                         changed = True
#                     elif isinstance(value, list):
#                         for i, item in enumerate(value):
#                             if isinstance(item, str) and oid in item:
#                                 value[i] = item.replace(oid, nid)
#                                 changed = True
#                     elif isinstance(value, str) and oid in value:
#                         data[key] = value.replace(oid, nid)
#                         changed = True
#                 return changed

#             changed = False
#             for oid, nid in self.changes:
#                 changed |= change_id(new_data, oid, nid)
#                 changed |= change_id(new_options, oid, nid)

#             if changed:
#                 self.hass.config_entries.async_update_entry(entry, data=new_data, options=new_options)
#                 if entry.state.recoverable:
#                     self.hass.async_create_task(self.hass.config_entries.async_reload(entry.entry_id))
#                 modified += 1
#         _LOGGER.info("Modified %i template entities", modified)

#     def migrate_files(self) -> None:
#         """Migrate entity IDs in .storage and YAML config files."""
#         storage_dir = Path(self.hass.config.path(".storage"))
#         relevant_files = ["core.automation", "lovelace", "energy"]

#         for path in storage_dir.iterdir():
#             try:
#                 if any(path.name.startswith(f) for f in relevant_files):
#                     content = path.read_text(encoding="utf-8")
#                     modified = content
#                     for old_id, new_id in self.changes:
#                         modified = modified.replace(old_id, new_id)
#                     if modified != content:
#                         path.write_text(modified, encoding="utf-8")
#             except Exception as e:
#                 _LOGGER.error("Error migrating file %s: %s", path, e)

#         config_path = Path(self.hass.config.config_dir)
#         for path in config_path.rglob("*"):
#             if path.is_dir() and path.name.startswith("."):
#                 continue
#             if path.suffix not in (".yaml", ".json"):
#                 continue
#             try:
#                 content = path.read_text(encoding="utf-8")
#                 modified = content
#                 for old_id, new_id in self.changes:
#                     modified = modified.replace(old_id, new_id)
#                 if modified != content:
#                     path.write_text(modified, encoding="utf-8")
#             except Exception as e:
#                 _LOGGER.error("Error migrating file %s: %s", path, e)

#     async def done(self) -> None:
#         """Persist state and migrate files if any changes occurred."""
#         if not self.changes:
#             return

#         await rs.RestoreStateData.async_save_persistent_states(self.hass)
#         await self.hass.async_add_executor_job(self.migrate_files)
#         _LOGGER.info("Migration completed: %d entity changes", len(self.changes))
