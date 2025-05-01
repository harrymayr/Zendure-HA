"""Module for Zendure API integration with Home Assistant."""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass
from typing import Any

from aiohttp import ClientSession
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

SF_AUTH_PATH = "/auth/app/token"
SF_DEVICELIST_PATH = "/productModule/device/queryDeviceListByConsumerId"
SF_DEVICEDETAILS_PATH = "/device/solarFlow/detail"


class Api:
    """Class for Zendure API."""

    def __init__(self, hass: HomeAssistant, data: dict[str, Any]) -> None:
        """Initialize the API."""
        self.hass = hass
        self.username = data[CONF_USERNAME]
        self.password = data[CONF_PASSWORD]
        self.session: ClientSession | None
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
                self.mqttUrl = json["iotUrl"]
                if self.zen_api.endswith("eu"):
                    self.mqttinfo = "SDZzJGo5Q3ROYTBO"
                else:
                    self.zen_api = "https://app.zendure.tech/v2"
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

    async def _get_detail(self, deviceId: str) -> Any:
        payload = {"deviceId": deviceId}
        url = f"{self.zen_api}{SF_DEVICEDETAILS_PATH}"
        _LOGGER.info(f"Getting device details for [{deviceId}] ...")
        response = await self.session.post(url=url, json=payload, headers=self.headers)
        if response.ok:
            respJson = await response.json()
            _LOGGER.info(f"Got data for [{deviceId}] {len(respJson)}...")
            return respJson["data"]

            raise SessionNotInitializedError()
        _LOGGER.error(response.text)
        return None

    async def getDevices(self) -> dict[str, ZendureDeviceDefinition]:
        if not self.session:
            raise SessionNotInitializedError

        devices: dict[str, ZendureDeviceDefinition] = {}
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
                        _LOGGER.info(f"Adding device: {deviceId} {prodName}")
                        devices[deviceId] = ZendureDeviceDefinition(
                            productKey=dev["productKey"],
                            deviceId=deviceId,
                            deviceName=dev["deviceName"],
                            snNumber=dev["snNumber"],
                            productName=prodName,
                        )
                        _LOGGER.info(f"Data: {dev}")

                    except Exception as e:
                        _LOGGER.error(traceback.format_exc())
                        _LOGGER.error(e)

            else:
                _LOGGER.error(f"Fetching device list failed: {response.text}")
        except Exception as e:
            _LOGGER.error(e)

        return devices


class SessionNotInitializedError(Exception):
    """Exception raised when the session is not initialized."""

    def __init__(self) -> None:
        """Initialize the exception."""
        super().__init__("Session is not initialized!")


@dataclass
class ZendureDeviceDefinition:
    """Class to hold zendure device properties."""

    productKey: str
    deviceId: str
    deviceName: str
    productName: str
    snNumber: str
