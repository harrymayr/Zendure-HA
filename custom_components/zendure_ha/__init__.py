"""The Zendure Integration integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.device_registry import DeviceEntry

from .zendurermanager import ZendureManager

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

type MyConfigEntry = ConfigEntry[RuntimeData]


@dataclass
class RuntimeData:
    """Class to hold your data."""

    manager: ZendureManager


async def async_setup_entry(hass: HomeAssistant, config_entry: MyConfigEntry) -> bool:
    """Set up Zendure Integration from a config entry."""
    manager = ZendureManager(hass, config_entry)
    config_entry.runtime_data = RuntimeData(manager)
    await hass.config_entries.async_forward_entry_setups(config_entry, PLATFORMS)

    _LOGGER.debug("Open API connection")
    if not await manager.load():
        raise ConfigEntryNotReady

    await manager.async_config_entry_first_refresh()

    config_entry.async_on_unload(config_entry.add_update_listener(_async_update_listener))

    # Return true to denote a successful setup.
    return True


async def _async_update_listener(hass: HomeAssistant, config_entry: MyConfigEntry) -> None:
    """Handle config options update."""
    # Reload the integration when the options change.
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_remove_config_entry_device(_hass: HomeAssistant, _config_entry: ConfigEntry, _device_entry: DeviceEntry) -> bool:
    """Handle removal of a device entry."""
    return False


async def async_unload_entry(hass: HomeAssistant, config_entry: MyConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(config_entry, PLATFORMS)
    if unload_ok:
        # Unload platforms and return result
        data = config_entry.runtime_data
        manager = data.manager
        if manager:
            await manager.unload()
        return True

    # If unloading failed, return false
    _LOGGER.error("async_unload_entry call to hass.config_entries.async_unload_platforms returned False")
    return False


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate an old entry."""
    if entry.version == 1 and entry.minor_version < 1:
        new_data = entry.data.copy()
        hass.config_entries.async_update_entry(entry, data=new_data, minor_version=2)
        _LOGGER.info(f"Migration to configuration version %s.%s successful {entry.version}, {entry.minor_version}")
    return True
