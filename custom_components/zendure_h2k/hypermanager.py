"""Zendure Integration manager using DataUpdateCoordinator."""

from curses import doupdate
from dataclasses import dataclass
from datetime import timedelta, datetime
from fileinput import lineno
import logging
import json

from typing import Any
from unittest import result
import av
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_SCAN_INTERVAL
from homeassistant.core import DOMAIN, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.core import Event, EventStateChangedData, callback
from paho.mqtt import client as mqtt_client
from sqlalchemy import true

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
        self._outpower = 0
        self._mqtt: mqtt_client.Client = None
        self.poll_interval = config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        self.consumed: str = config_entry.data[CONF_CONSUMED]
        self.produced: str = config_entry.data[CONF_PRODUCED]
        self.next_update = datetime.now() + timedelta(minutes=15)
        self._messageid = 0

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

        except Exception as err:
            _LOGGER.error(err)
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
            _LOGGER.info("_update_energy")
            if (new_state := event.data["new_state"]) is None:
                return

            # Get all active hypers
            outpower = 0
            outMax = 0
            gridpower = 0
            gridMax = 0
            active_out: list[Hyper2000] = []
            active_grid: list[Hyper2000] = []
            for h in self.hypers.values():
                if h.sensors["outputHomePower"].state > 0:
                    active_out.append(h)
                    # outpower += int(h.sensors["outputHomePower"].state)
                    outMax += int(h.sensors["outputHomePower"].state)
                elif h.sensors["soc"].state > 0:
                    active_grid.append(h)
                    # gridpower += int(h.sensors["gridInputPower"].state)

            # # Calculate the updated power
            power = int(float(new_state.state))
            # if event.data["entity_id"] == self.consumed:
            #     outpower += power
            # elif event.data["entity_id"] == self.produced:
            #     outpower -= power

            outpower = max(0, power)
            # gridpower = 0
            _LOGGER.info(f"Update power: {outpower}")

            # Update active hypers
            if self.next_update < datetime.now():
                active_out = []
                active_grid = []

            def update_power(h: Hyper2000, chargetype: int, chargepower: int, outpower: int) -> None:
                _LOGGER.info(f"update_power: {h.hid} {chargetype} {chargepower} {outpower}")
                self._messageid += 1
                power = json.dumps(
                    {
                        "arguments": [
                            {
                                "autoModelProgram": 1,
                                "autoModelValue": {"chargingType": chargetype, "chargingPower": chargepower, "outPower": outpower},
                                "msgType": 1,
                                "autoModel": 8,
                            }
                        ],
                        "deviceKey": h.hid,
                        "function": "deviceAutomation",
                        "messageId": self._messageid,
                        "timestamp": int(datetime.now().timestamp()),
                    },
                    default=lambda o: o.__dict__,
                )
                self._mqtt.publish(h.topic_function, power)

            if outpower > 0:
                if (len(active_out) > 1 and outpower < len(active_out) * 200) or (outpower > len(active_out) * 800):
                    # Get available hypers for discharging
                    _LOGGER.info("gt hypers")
                    avail = sorted(
                        [h for h in self.hypers.values() if (h.sensors["electricLevel"].state * 10) > float(h.sensors["minSoc"].state)],
                        key=lambda h: h.sensors["electricLevel"].state,
                        reverse=True,
                    )
                    _LOGGER.info(f"Available hypers: {len(avail)}")

                    while avail and len(active_out) * 800 < outpower:
                        h = avail.pop(0)
                        if h not in active_out:
                            active_out.append(h)

                    while len(active_out) > 1 and len(active_out) * 300 > outpower:
                        h = avail.pop()
                        if h in active_out:
                            active_out.remove(h)

                    # stop charging/discharging unused hypers
                    for h in self.hypers.values():
                        if h not in active_out:
                            update_power(h, 0, 0, 0)
                    _LOGGER.info(f"Used hypers: {len(active_out)}")

                for h in active_out:
                    update_power(h, 0, 0, int(outpower / len(active_out)))

            else:
                if (len(active_grid) > 1 and outpower < len(active_grid) * 200) or (outpower > len(active_grid) * 800):
                    # Get available hypers for charging
                    avail = sorted(
                        [h for h in self.hypers.values() if h.sensors["electricLevel"].state < (h.sensors["socSet"].state / 10)],
                        key=lambda h: h.sensors["electricLevel"].state,
                    )

                    while avail and len(active_grid) * 800 < outpower:
                        h = avail.pop(0)
                        if h not in active_grid:
                            active_grid.append(h)

                    while len(active_grid) > 1 and len(active_grid) * 200 > outpower:
                        h = avail.pop()
                        if h in active_grid:
                            active_grid.remove(h)

                    # stop charging/discharging unused hypers
                    for h in self.hypers.values():
                        if h not in active_grid:
                            update_power(h, 0, 0, 0)

                for h in active_grid:
                    update_power(h, 1, int(outpower / len(active_grid)), 0)

            _LOGGER.info(f"Update power: {outpower}")
        except Exception as err:
            _LOGGER.error(err)
            _LOGGER.error(traceback.format_exc())

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
                        self.hass.loop.call_soon_threadsafe(hyper.onAddSensor, key, value)
                    else:
                        _LOGGER.info(f"Found unknown state value:  {deviceid} {key} => {value}")

            parameter = msg.topic.split("/")[-1]
            if parameter == "report":
                if (properties := payload.get("properties", None)) or (properties := payload.get("cluster", None)):
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
