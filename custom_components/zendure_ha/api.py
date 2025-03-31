"""Module for Zendure API integration with Home Assistant."""

import logging
import traceback
from base64 import b64decode
from collections.abc import Callable
from typing import Any

from aiohttp import ClientSession
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from paho.mqtt import client as mqtt_client

from .devices.ace1500 import ACE1500
from .devices.aio2400 import AIO2400
from .devices.hub1200 import Hub1200
from .devices.hub2000 import Hub2000
from .devices.hyper2000 import Hyper2000
from .devices.solarflow800 import SolarFlow800
from .zenduredevice import ZendureDevice

_LOGGER = logging.getLogger(__name__)


class Api:
    """Class for Zendure API."""

    def __init__(self, hass: HomeAssistant, data: dict) -> None:
        """Initialize the API."""
        self.hass = hass
        self.username = data[CONF_USERNAME]
        self.password = data[CONF_PASSWORD]
        self.session: ClientSession
        self.token: str = ""
        self.mqttUrl = ""
        self.zen_api = ""
        self.mqttinfo = ""

    async def connect(self) -> bool:
        _LOGGER.info("Connecting to Zendure")
        self.session = async_get_clientsession(self.hass)
        self.headers = {
            "Content-Type": "application/json",
            "Accept-Language": "en-EN",
            "appVersion": "4.3.1",
            "User-Agent": "Zendure/4.3.1 (iPhone; iOS 14.4.2; Scale/3.00)",
            "Accept": "*/*",
            "Blade-Auth": "bearer (null)",
        }

        SF_AUTH_PATH = "/auth/app/token"
        authBody = {
            "password": self.password,
            "account": self.username,
            "appId": "121c83f761305d6cf7e",
            "appType": "iOS",
            "grantType": "password",
            "tenantId": "",
        }

        try:
            url = f"https://app.zendure.tech/v2{SF_AUTH_PATH}"
            response = await self.session.post(url=url, json=authBody, headers=self.headers)

            if response.ok:
                respJson = await response.json()
                json = respJson["data"]
                self.zen_api = json["serverNodeUrl"]
                if self.zen_api.endswith("eu"):
                    self.mqttUrl = json["iotUrl"]
                    self.mqttinfo = "SDZzJGo5Q3ROYTBO"
                else:
                    self.zen_api = "https://app.zendure.tech/v2"
                    self.mqttUrl = "mqtt.zen-iot.com"
                    self.mqttinfo = "b0sjUENneTZPWnhk"

                self.token = json["accessToken"]
                self.headers["Blade-Auth"] = f"bearer {self.token}"
                _LOGGER.info(f"Connected to {self.zen_api} => Mqtt: {self.mqttUrl}")
                return True

        except Exception as e:
            _LOGGER.error(f"Unable to connect to Zendure {self.zen_api} {e}!")
            return False

        _LOGGER.error(f"Unable to connect to Zendure {self.zen_api}!")
        return False

    def disconnect(self) -> None:
        self.session.close()
        self.session = None

    def get_mqtt(self, onMessage: Callable) -> mqtt_client.Client:
        return self.mqtt(self.token, "zenApp", b64decode(self.mqttinfo.encode()).decode("latin-1"), onMessage)

    async def getDevices(self, hass: HomeAssistant) -> dict[str, ZendureDevice]:
        SF_DEVICELIST_PATH = "/productModule/device/queryDeviceListByConsumerId"
        SF_DEVICEDETAILS_PATH = "/device/solarFlow/detail"

        async def get_detail(deviceId: str) -> Any:
            payload = {"deviceId": deviceId}
            url = f"{self.zen_api}{SF_DEVICEDETAILS_PATH}"
            _LOGGER.info(f"Getting device details for [{deviceId}] ...")
            response = await self.session.post(url=url, json=payload, headers=self.headers)
            if response.ok:
                respJson = await response.json()
                _LOGGER.info(f"Got data for [{deviceId}] {len(respJson)}...")
                return respJson["data"]

            _LOGGER.error("Fetching device details failed!")
            _LOGGER.error(response.text)
            return None

        devices: dict[str, ZendureDevice] = {}
        try:
            url = f"{self.zen_api}{SF_DEVICELIST_PATH}"
            _LOGGER.info("Getting device list ...")

            response = await self.session.post(url=url, headers=self.headers)
            if response.ok:
                respJson = await response.json()
                deviceInfo = respJson["data"]
                for dev in deviceInfo:
                    if (deviceId := dev["id"]) is None or (prodName := dev["productName"]) is None:
                        continue
                    try:
                        if not (data := await get_detail(deviceId)) or (deviceKey := data.get("deviceKey", None)) is None:
                            _LOGGER.debug(f"Unable to get details for: {deviceId} {prodName}")
                            continue
                        _LOGGER.info(f"Adding device: {deviceKey} {prodName}")

                        match prodName:
                            case "Hyper 2000":
                                devices[deviceKey] = Hyper2000(hass, deviceKey, data["productKey"], data["deviceName"])
                            case "SolarFlow 800":
                                devices[deviceKey] = SolarFlow800(hass, deviceKey, data["productKey"], data["deviceName"])
                            case "Hub 1200":
                                devices[deviceKey] = Hub1200(hass, deviceKey, data["productKey"], data["deviceName"])
                            case "SolarFlow Hub 2000":
                                devices[deviceKey] = Hub2000(hass, deviceKey, data["productKey"], data["deviceName"])
                            case "SolarFlow AIO ZY":
                                devices[deviceKey] = AIO2400(hass, deviceKey, data["productKey"], data["deviceName"])
                            case "Ace 1500":
                                devices[deviceKey] = ACE1500(hass, deviceKey, data["productKey"], data["deviceName"])
                            case _:
                                _LOGGER.info(f"Device {prodName} is not supported!")

                        _LOGGER.info(f"Data: {data}")
                    except Exception as e:
                        _LOGGER.error(traceback.format_exc())
                        _LOGGER.error(e)
            else:
                _LOGGER.error(f"Fetching device list failed: {response.text}")
        except Exception as e:
            _LOGGER.error(e)

        return devices

    def mqtt(self, clientId: str, username: str, password: str, onMessage: Callable) -> mqtt_client.Client:
        _LOGGER.info(f"Create mqtt client!! {clientId}")
        client = mqtt_client.Client(client_id=clientId, clean_session=False)
        client.username_pw_set(username=username, password=password)
        client.on_connect = self.onConnect
        client.on_disconnect = self.onDisconnect
        client.on_message = onMessage
        client.connect(self.mqttUrl, 1883)

        client.suppress_exceptions = True
        client.loop()
        client.loop_start()
        return client

    def onConnect(self, _client: Any, _userdata: Any, _flags: Any, _rc: Any) -> None:
        _LOGGER.info("Client has been connected")

    def onDisconnect(self, _client: Any, _userdata: Any, _rc: Any) -> None:
        _LOGGER.info("Client has been disconnected; trying to restart")
        _client.reconnect()
        _client.loop_start()
