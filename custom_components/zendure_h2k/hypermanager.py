"""Zendure Integration manager using DataUpdateCoordinator."""

from dataclasses import dataclass
from datetime import timedelta, datetime
import logging
import json

from typing import Any
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import DOMAIN, HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.components.select import SelectEntity
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.core import Event, EventStateChangedData, callback
from paho.mqtt import client as mqtt_client

from .api import API, Hyper2000
from .const import DEFAULT_SCAN_INTERVAL, CONF_CONSUMED, CONF_PRODUCED

_LOGGER = logging.getLogger(__name__)


@dataclass
class ZendureAPIData:
    """Class to hold integration entry name."""

    controller_name: str


class HyperManager(DataUpdateCoordinator[int]):
    """The Zendure manager."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""
        self._hass = hass
        self.hypers: dict[str, Hyper2000] = {}
        self._mqtt: mqtt_client.Client = None
        self.poll_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self.consumed: str = config_entry.data[CONF_CONSUMED]
        self.produced: str = config_entry.data[CONF_PRODUCED]
        self.next_update = datetime.now() + timedelta(minutes=15)
        self.operation = 0
        self._hypers_charge: list[Hyper2000] = []
        self._hypers_discharge: list[Hyper2000] = []

        # Initialise DataUpdateCoordinator
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} ({config_entry.unique_id})",
            update_method=self._refresh_data,
            update_interval=timedelta(seconds=self.poll_interval),
            always_update=True,
        )

        # Set sensors from values entered in config flow setup
        if self.consumed and self.produced:
            _LOGGER.info(f"Energy sensors: {self.consumed} - {self.produced} to _update_energy")
            async_track_state_change_event(self._hass, [self.consumed, self.produced], self._update_energy)

        # Create the api
        self.api = API(self._hass, config_entry.data)

    async def initialize(self) -> bool:
        """Initialize the manager."""
        try:
            if not await self.api.connect():
                return False
            self.hypers = await self.api.getHypers(self._hass)
            self._mqtt = self.api.get_mqtt(self.onMessage)

            try:
                for h in self.hypers.values():
                    h.create_sensors()
                    self._mqtt.subscribe(f"/{h.prodkey}/{h.hid}/#")
                    self._mqtt.subscribe(f"iot/{h.prodkey}/{h.hid}/#")

            except Exception as err:
                _LOGGER.exception(err)

            _LOGGER.info(f"Found: {len(self.hypers)} hypers")

            # Add HyperManager sensors
            _LOGGER.info(f"Adding sensors Hyper2000 {self.name}")
            selects = [
                HyperManagerSelect(
                    self,
                    "status",
                    "Status",
                    options=[
                        "off",
                        "manual power operation",
                        "smart power matching",
                    ],
                ),
            ]
            Hyper2000.addSelects(selects)

        except Exception as err:
            _LOGGER.exception(err)
            return False
        return True

    async def _refresh_data(self) -> None:
        """Refresh the data of all hyper2000's."""
        _LOGGER.info("refresh hypers")
        try:
            if self._mqtt:
                for h in self.hypers.values():
                    self._mqtt.publish(h._topic_read, '{"properties": ["getAll"]}')
        except Exception as err:
            _LOGGER.error(err)
        self._schedule_refresh()

    @callback
    def _update_energy(self, event: Event[EventStateChangedData]) -> None:
        """Update the battery input/output."""
        try:
            # check for smart matching mode
            match self.operation:
                case 1:
                    # manual power operation
                    return
                case 2:
                    # Update sorted list of hypers based on electricLevel
                    if (not self._hypers_charge and not self._hypers_charge) or (self.next_update < datetime.now()):
                        self.next_update = datetime.now() + timedelta(minutes=5)
                        self._hypers_discharge = sorted(
                            [h for h in self.hypers.values() if (h.sensors["electricLevel"].state) > float(h.sensors["minSoc"].state)],
                            key=lambda h: h.sensors["electricLevel"].state,
                            reverse=True,
                        )
                        self._hypers_charge = sorted(
                            [h for h in self.hypers.values() if h.sensors["electricLevel"].state < float(h.sensors["socSet"].state)],
                            key=lambda h: h.sensors["electricLevel"].state,
                        )
                        _LOGGER.info(f"Valid charging: {len(self._hypers_charge)}")
                        _LOGGER.info(f"Valid discharging: {len(self._hypers_discharge)}")

                    # smart power matching
                    if (power := int(float(event.data["new_state"].state))) == 0:
                        return
                    _LOGGER.info(f"update energy {power}")

                    if (discharge := sum(h.sensors["outputHomePower"].state for h in self._hypers_discharge)) > 0:
                        self.updDischarging(discharge + power * (1 if event.data["entity_id"] == self.consumed else -1))
                    elif (charge := sum(h.sensors["gridInputPower"].state for h in self._hypers_charge)) > 0:
                        self.updCharging(charge + power * (-1 if event.data["entity_id"] == self.consumed else 1))
                    elif event.data["entity_id"] == self.produced:
                        self.updCharging(power)
                    else:
                        self.updDischarging(power)

                    return
                case _:
                    # nothing to do
                    return
        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

    def updCharging(self, charge: int) -> None:
        """Update the battery input/output."""
        _LOGGER.info(f"update energy Charging: {charge}")
        if not self._hypers_charge:
            return

        if charge < 400:
            self._hypers_charge[0].update_power(self._mqtt, 1, charge, 0)
            if len(self._hypers_charge) > 1:
                for h in self._hypers_charge[1:]:
                    h.update_power(self._mqtt, 0, 0, 0)
        else:
            for h in self._hypers_charge:
                h.update_power(self._mqtt, 1, int(charge / len(self._hypers_charge)), 0)

    def updDischarging(self, discharge: int) -> None:
        """Update the battery input/output."""
        _LOGGER.info(f"update energy Discharging: {discharge}")

        if not self._hypers_discharge:
            return

        if discharge < 400:
            self._hypers_discharge[0].update_power(self._mqtt, 0, 0, discharge)
            if len(self._hypers_discharge) > 1:
                for h in self._hypers_discharge[1:]:
                    h.update_power(self._mqtt, 0, 0, 0)
        else:
            for h in self._hypers_discharge:
                h.update_power(self._mqtt, 0, 0, int(discharge / len(self._hypers_discharge)))

    def onMessage(self, client, userdata, msg):
        try:
            # check for valid device in payload
            payload = json.loads(msg.payload.decode())
            if not (deviceid := payload.get("deviceId", None)) or not (hyper := self.hypers.get(deviceid, None)):
                return

            def handle_properties(properties: Any) -> None:
                for key, value in properties.items():
                    if sensor := hyper.sensors.get(key, None):
                        sensor.update_value(value)
                    elif isinstance(value, (int | float)):
                        self.hass.loop.call_soon_threadsafe(hyper.add_sensor, key, value)
                    else:
                        _LOGGER.info(f"Found unknown state value:  {deviceid} {key} => {value}")

            parameter = msg.topic.split("/")[-1]
            if parameter == "report":
                if properties := payload.get("properties", None):
                    handle_properties(properties)
                else:
                    _LOGGER.info(f"Found unknown topic: {deviceid} {msg.topic} {payload}")
            elif parameter == "log" and payload["logType"] == 2:
                # battery information
                deviceid = payload["deviceId"]
                if hyper := self.hypers.get(deviceid, None):
                    data = payload["log"]["params"]
                    hyper.update_battery(data)
            else:
                _LOGGER.info(f"Receive: {msg.topic} => {payload}")
        except Exception as err:
            _LOGGER.error(err)


class HyperManagerSelect(SelectEntity):
    """Representation of a HyperManager select entity."""

    def __init__(
        self,
        manager: HyperManager,
        uniqueid: str,
        name: str,
        options: list[str],
    ) -> None:
        """Initialize a HyperManager select entity."""
        self.name = name
        self.manager = manager
        self._attr_unique_id = f"HyperManager-{uniqueid}"
        self._attr_name = f"HyperManager {name}"
        self._attr_should_poll = False
        self._attr_options = options
        self._attr_current_option = options[0]
        self._attr_translation_key = uniqueid
        self._attr_device_info = self.attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "HyperManager")},
            name="Hyper Manager",
            manufacturer="Fireson",
        )

    async def async_select_option(self, option: str) -> None:
        """Update the current selected option."""
        self._attr_current_option = option
        self.async_write_ha_state()
        self.manager.operation = self._attr_options.index(option)
