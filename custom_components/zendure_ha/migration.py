"""Migration helpers for Zendure integration."""

import logging
from pathlib import Path

from homeassistant.components.persistent_notification import async_create
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import restore_state as rs

from .const import DOMAIN
from .entity import snakecase

_LOGGER = logging.getLogger(__name__)


class Migration:
    """Handles device/entity rename migrations."""

    @staticmethod
    def check_device(hass: HomeAssistant, device_id: str, name: str, model: str, sn: str) -> None:
        """Track cloud-side device renames via name_by_user for the next migration."""
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

        if name != existing.name and existing.name_by_user is None:
            _LOGGER.info("Device '%s' renamed to '%s' in cloud, storing for next migration", existing.name, name)
            device_registry.async_update_device(existing.id, name_by_user=name)

    @staticmethod
    def _update_files(hass: HomeAssistant, changes: list[tuple[str, str]]) -> bool:
        """Replace old entity IDs with new ones in storage and config files."""
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
        for path in storage_dir.iterdir():
            if any(path.name.startswith(f) for f in ["core.automation", "lovelace", "energy"]):
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

    @staticmethod
    async def async_migrate(hass: HomeAssistant) -> None:
        """One-time migration run via async_migrate_entry: fix device identifiers and entity IDs."""
        device_registry = dr.async_get(hass)
        entity_registry = er.async_get(hass)
        data = rs.async_get(hass)
        changes: list[tuple[str, str]] = []

        for device in list(device_registry.devices.values()):
            if not any(ident[0] == DOMAIN for ident in device.identifiers):
                continue

            name = device.name_by_user or device.name
            if not name:
                continue

            if device.name_by_user:
                _LOGGER.info("Promoting device name '%s' -> '%s'", device.name, device.name_by_user)
                device_registry.async_update_device(device.id, name=device.name_by_user, name_by_user=None)

            if device.hw_version:
                new_identifiers = set(device.identifiers) | {(DOMAIN, device.hw_version)}
                if new_identifiers != set(device.identifiers):
                    device_registry.async_update_device(device.id, new_identifiers=new_identifiers)

            for entity in er.async_entries_for_device(entity_registry, device.id, True):
                try:
                    if entity.translation_key is None:
                        entity_registry.async_remove(entity.entity_id)
                        _LOGGER.debug("Removed orphan entity %s", entity.entity_id)
                        continue

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
                        _LOGGER.debug("Migrated entity %s -> %s", entity.entity_id, entityid)
                        changes.append((entity.entity_id, entityid))
                except Exception as e:
                    _LOGGER.error("Failed to migrate entity %s: %s", entity.entity_id, e)

        if changes:
            if await hass.async_add_executor_job(Migration._update_files, hass, changes):
                await rs.RestoreStateData.async_save_persistent_states(hass)
                async_create(
                    hass,
                    f"Zendure migration updated {len(changes)} entities. "
                    "Please restart Home Assistant to ensure all automations and dashboards use the new entity IDs.",
                    title="Zendure Migration",
                    notification_id="zendure_migration",
                )
        _LOGGER.info("Zendure async_migrate complete: %d entity changes", len(changes))
