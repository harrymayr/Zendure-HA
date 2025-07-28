"""Initialize the Zendure component."""

import logging

from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .api import Api
from .const import CONF_MQTTLOG, CONF_P1METER
from .manager import ZendureConfigEntry, ZendureManager

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.NUMBER, Platform.SELECT, Platform.SENSOR, Platform.SWITCH]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ZendureConfigEntry) -> bool:
    """Set up Zendure as config entry."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    Api.mqttLogging = entry.options.get(CONF_MQTTLOG, False)
    manager = ZendureManager(hass, entry)
    await manager.loadDevices()
    entry.runtime_data = manager
    await manager.async_config_entry_first_refresh()
    entry.async_on_unload(entry.add_update_listener(update_listener))
    return True


async def update_listener(_hass: HomeAssistant, entry: ZendureConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.debug("Updating Zendure config entry: %s", entry.entry_id)
    Api.mqttLogging = entry.options.get(CONF_MQTTLOG, False)
    entry.runtime_data.update_p1meter(entry.options.get(CONF_P1METER, "sensor.power_actual"))
    _hass.config_entries.async_update_entry(entry, data=entry.data, options=entry.options)


async def async_unload_entry(hass: HomeAssistant, entry: ZendureConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Zendure config entry: %s", entry.entry_id)
    result = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if result:
        manager = entry.runtime_data
        for c in Api.mqttClients.values():
            if c.is_connected():
                c.disconnect()
        manager.update_p1meter(None)
        manager.clusters.clear()
        manager.devices.clear()
    return result
