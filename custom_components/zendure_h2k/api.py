import logging
import json
from enum import StrEnum
from typing import Any
from paho.mqtt import client as mqtt_client
from base64 import b64decode

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, entity_platform, service
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME

from .hyper2000 import Hyper2000

_LOGGER = logging.getLogger(__name__)

SF_API_BASE_URL = "https://app.zendure.tech"


class API:
    """Class for Zendure API."""

    def __init__(self, hass: HomeAssistant, data):
        self.hass = hass
        self.baseUrl = f"{SF_API_BASE_URL}"
        self.zen_api = data[CONF_HOST]
        self.username = data[CONF_USERNAME]
        self.password = data[CONF_PASSWORD]
        self.session = None
        self.token: str = None
        self.mqttUrl: str = None

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
            _LOGGER.info("Unable to connected to Zendure!")
            return False

        _LOGGER.info("Connected to Zendure!")
        return True

    def disconnect(self):
        self.session.close()
        self.session = None

    def get_mqtt(self, onMessage) -> mqtt_client.Client:
        try:
            return self.mqtt(self.token, "zenApp", b64decode("SDZzJGo5Q3ROYTBO".encode()).decode("latin-1"), onMessage)
        except Exception as e:
            _LOGGER.exception(e)

    async def getHypers(self, hass: HomeAssistant) -> dict[str, Hyper2000]:
        SF_DEVICELIST_PATH = "/productModule/device/queryDeviceListByConsumerId"
        SF_DEVICEDETAILS_PATH = "/device/solarFlow/detail"

        hypers: dict[str, Hyper2000] = {}
        try:
            url = f"{self.zen_api}{SF_DEVICELIST_PATH}"
            _LOGGER.info("Getting device list ...")

            response = await self.session.post(url=url, headers=self.headers)
            if response.ok:
                respJson = await response.json()
                devices = respJson["data"]
                for dev in devices:
                    _LOGGER.debug(f"prodname: {dev['productName']}")
                    if dev["productName"] == "Hyper 2000":
                        try:
                            h: Hyper2000 = None
                            payload = {"deviceId": dev["id"]}
                            url = f"{self.zen_api}{SF_DEVICEDETAILS_PATH}"
                            _LOGGER.info(f"Getting device details for [{dev['id']}] ...")
                            response = await self.session.post(url=url, json=payload, headers=self.headers)
                            if response.ok:
                                respJson = await response.json()
                                data = respJson["data"]
                                h = Hyper2000(
                                    hass,
                                    data["deviceKey"],
                                    data["productKey"],
                                    data["deviceName"],
                                    data,
                                )
                                if h.hid:
                                    _LOGGER.info(f"Hyper: [{h.hid}]")
                                    hypers[data["deviceKey"]] = h
                                    _LOGGER.info(f"Data: {data}")
                                else:
                                    _LOGGER.info(f"Hyper: [??]")
                            else:
                                _LOGGER.error("Fetching device details failed!")
                                _LOGGER.error(response.text)
                        except Exception as e:
                            _LOGGER.exception(e)
            else:
                _LOGGER.error("Fetching device list failed!")
                _LOGGER.error(response.text)
        except Exception as e:
            _LOGGER.exception(e)

        return hypers

    @property
    def controller_name(self) -> str:
        """Return the name of the controller."""
        return self.zen_api.replace(".", "_")

    def mqtt(self, client, username, password, onMessage) -> mqtt_client.Client:
        _LOGGER.info(f"Create mqtt client!! {client}")
        client = mqtt_client.Client(client_id=client, clean_session=False)
        client.username_pw_set(username=username, password=password)
        client.on_connect = self.onConnect
        client.on_disconnect = self.onDisconnect
        client.on_message = onMessage
        client.connect(self.mqttUrl, 1883, 120)

        client.suppress_exceptions = True
        client.loop()
        client.loop_start()
        return client

    def onConnect(self, _client, userdata, flags, rc):
        _LOGGER.info(f"Client has been connected")

    def onDisconnect(self, _client, userdata, rc):
        _LOGGER.info(f"Client has been disconnected")
