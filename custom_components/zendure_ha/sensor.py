"""Interfaces with the Zendure Integration api sensors."""

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.template import Template
from homeassistant.components.sensor import SensorEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    ZendureSensor.addSensors = async_add_entities


class ZendureSensor(SensorEntity):
    addSensors: AddEntitiesCallback

    def __init__(
        self,
        deviceinfo: DeviceInfo,
        uniqueid: str,
        name: str,
        template: Template | None = None,
        uom: str = None,
        deviceclass=None,
    ) -> None:
        """Initialize a Zendure entity."""
        self._attr_available = True
        self._attr_device_info = deviceinfo
        self._attr_name = name
        self._attr_unique_id = uniqueid
        self._attr_should_poll = False
        self._value_template: Template | None = template
        self._attr_native_unit_of_measurement = uom
        self._attr_device_class = deviceclass

    def update_value(self, value):
        try:
            new_value = (
                self._value_template.async_render_with_possible_json_value(value, None) if self._value_template is not None else int(value)
            )

            if new_value != self._attr_native_value:
                _LOGGER.info(f"Update state: {self._attr_unique_id} => {new_value}")
                self._attr_native_value = new_value
                if self.hass:
                    self.schedule_update_ha_state()

        except Exception as err:
            _LOGGER.exception(f"Error {err} setting state: {self._attr_unique_id} => {value}")

    @property
    def as_int(self) -> int:
        """Return sensor value as int."""
        return 0 if self._attr_native_value is None else int(self._attr_native_value)

    @property
    def as_float(self) -> float:
        """Return sensor value as int."""
        return 0 if self._attr_native_value is None else float(self._attr_native_value)
