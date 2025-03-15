import json
import logging
import traceback
from base64 import b64decode
from typing import Any, Callable

from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform, service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from paho.mqtt import client as mqtt_client

from .hyper2000 import Hyper2000
from .solarflow800 import SolarFlow800
from .zenduredevice import ZendureDevice

_LOGGER = logging.getLogger(__name__)

SF_API_BASE_URL = "https://app.zendure.tech"


class Api:
    """Class for Zendure API."""

    def __init__(self, hass: HomeAssistant, data) -> None:
        """Initialize the API."""
        self.hass = hass
        self.baseUrl = f"{SF_API_BASE_URL}"
        self.zen_api = data[CONF_HOST]
        self.username = data[CONF_USERNAME]
        self.password = data[CONF_PASSWORD]
        self.session = None
        self.token: str | None = None
        self.mqttUrl: str | None = None

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
            url = f"{self.zen_api}{SF_AUTH_PATH}"
            response = await self.session.post(url=url, json=authBody, headers=self.headers)
            if response.ok:
                respJson = await response.json()
                json = respJson["data"]
                self.token = json["accessToken"]
                self.mqttUrl = json["iotUrl"]
                self.headers["Blade-Auth"] = f"bearer {self.token}"
            else:
                _LOGGER.error("Authentication failed!")
                _LOGGER.error(response.text)
                return False

        except Exception as e:
            _LOGGER.exception(e)
            _LOGGER.error(f"Unable to connected to Zendure! {self.zen_api}")
            return False

        _LOGGER.info("Connected to Zendure!")
        return True

    def disconnect(self) -> None:
        self.session.close()
        self.session = None

    def get_mqtt(self, onMessage) -> mqtt_client.Client:
        try:
            return self.mqtt(self.token, "zenApp", b64decode("SDZzJGo5Q3ROYTBO".encode()).decode("latin-1"), onMessage)
        except Exception as e:
            _LOGGER.exception(e)

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
                    _LOGGER.info(f"prodname: {deviceId} {prodName}")
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
                            case _:
                                _LOGGER.info(f"Device {prodName} is not supported!")

                        _LOGGER.info(f"Data: {data}")
                    except Exception as e:
                        _LOGGER.error(traceback.format_exc())
                        _LOGGER.error(e)
            else:
                _LOGGER.error("Fetching device list failed!")
                _LOGGER.error(response.text)
        except Exception as e:
            _LOGGER.error(e)

        return devices

    @property
    def controller_name(self) -> str:
        """Return the name of the controller."""
        return self.username

    def mqtt(self, clientId: str, username: str, password: str, onMessage: Callable) -> mqtt_client.Client:
        _LOGGER.info(f"Create mqtt client!! {clientId}")
        client = mqtt_client.Client(client_id=clientId, clean_session=False)
        client.username_pw_set(username=username, password=password)
        client.on_connect = self.onConnect
        client.on_disconnect = self.onDisconnect
        client.on_message = onMessage
        client.connect(self.mqttUrl, 1883, 120)

        client.suppress_exceptions = True
        client.loop()
        client.loop_start()
        return client

    def onConnect(self, _client, userdata, flags, rc) -> None:
        _LOGGER.info("Client has been connected")

    def onDisconnect(self, _client, userdata, rc) -> None:
        _LOGGER.info("Client has been disconnected")
