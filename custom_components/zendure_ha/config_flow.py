"""Config flow for Zendure Integration integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector
from paho.mqtt import client as mqtt_client

from .api import Api
from .const import CONF_MQTTLOCAL, CONF_MQTTLOG, CONF_MQTTPORT, CONF_MQTTPSW, CONF_MQTTSERVER, CONF_MQTTUSER, CONF_P1METER, CONF_WIFIPSW, CONF_WIFISSID, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ZendureConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Zendure Integration."""

    VERSION = 1
    _input_data: dict[str, Any]
    data_schema = vol.Schema({
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): selector.TextSelector(
            selector.TextSelectorConfig(
                type=selector.TextSelectorType.PASSWORD,
            ),
        ),
        vol.Required(CONF_P1METER, description={"suggested_value": "sensor.power_actual"}): str,
        vol.Required(CONF_MQTTLOG): bool,
        vol.Required(CONF_MQTTLOCAL): bool,
    })
    mqtt_schema = vol.Schema({
        vol.Required(CONF_MQTTSERVER): str,
        vol.Required(CONF_MQTTPORT, default=1883): int,
        vol.Required(CONF_MQTTUSER): str,
        vol.Required(CONF_MQTTPSW): selector.TextSelector(
            selector.TextSelectorConfig(
                type=selector.TextSelectorType.PASSWORD,
            ),
        ),
        vol.Required(CONF_WIFISSID): str,
        vol.Required(CONF_WIFIPSW): selector.TextSelector(
            selector.TextSelectorConfig(
                type=selector.TextSelectorType.PASSWORD,
            ),
        ),
    })

    def __init__(self) -> None:
        """Initialize."""
        self._user_input: dict[str, Any] | None = None

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry: ConfigEntry) -> ZendureOptionsFlowHandler:
        """Get the options flow for this handler."""
        return ZendureOptionsFlowHandler()

    async def validate_input(self) -> None:
        """Create the manager."""
        _LOGGER.debug("Create manager")
        user_input = self._user_input
        if user_input is None:
            raise Exception("User input is empty")

        # Check if we can connect to the Zendure API
        api = Api(self.hass, user_input)
        if not await api.connect():
            raise ZendureConnectionError

        # mqttlocal = user_input.get(CONF_MQTTLOCAL, False)
        # if mqttlocal:
        #     mqtt = mqtt_client.Client(clean_session=False, userdata=True)
        #     mqtt.username_pw_set(username=user_input.get(CONF_MQTTUSER), password=user_input.get(CONF_MQTTPSW))
        #     mqtt.connect(user_input.get(CONF_MQTTSERVER, ""), user_input.get(CONF_MQTTPORT, 1883))
        #     mqtt.disconnect()

    async def create_manager(self) -> ConfigFlowResult:
        if self._user_input is None:
            self._user_input = {}
        await self.validate_input()
        await self.async_set_unique_id("Zendure")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title="Zendure", data=self._user_input)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Step when user initializes a integration."""
        errors: dict[str, str] = {}
        if user_input is not None:
            self._user_input = user_input
            use_mqtt = user_input[CONF_MQTTLOCAL]
            if use_mqtt:
                return await self.async_step_mqtt()

            try:
                return await self.create_manager()
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.error(f"Unexpected exception: {err}")
                errors["base"] = f"invalid input {err}"

        return self.async_show_form(step_id="user", data_schema=self.data_schema, errors=errors)

    async def async_step_mqtt(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and user_input.get(CONF_MQTTSERVER, None) is not None:
            try:
                self._user_input = self._user_input | user_input if self._user_input else user_input
                return await self.create_manager()
            except Exception as err:  # pylint: disable=broad-except
                _LOGGER.error(f"Unexpected exception: {err}")
                errors["base"] = f"invalid input {err}"

        return self.async_show_form(step_id="user", data_schema=self.mqtt_schema, errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add reconfigure step to allow to reconfigure a config entry."""
        errors: dict[str, str] = {}
        config_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        schema = self.data_schema
        if user_input is not None:
            self._user_input = self._user_input | user_input if self._user_input else user_input
            use_mqtt = user_input.get(CONF_MQTTLOCAL, False)
            if use_mqtt:
                schema = self.mqtt_schema
            else:
                try:
                    await self.validate_input()
                except Exception as err:  # pylint: disable=broad-except
                    _LOGGER.error(f"Unexpected exception: {err}")
                    errors["base"] = f"invalid input {err}"
                else:
                    return self.async_update_reload_and_abort(
                        config_entry,
                        unique_id=config_entry.unique_id,
                        data={**config_entry.data, **self._user_input},
                        reason="reconfigure_successful",
                    )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                data_schema=schema,
                suggested_values=config_entry.data | (user_input or {}),
            ),
            errors=errors,
        )


class ZendureOptionsFlowHandler(OptionsFlow):
    """Handles the options flow."""

    async def async_step_init(self, user_input: Any = None) -> ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            options = self.config_entry.options | user_input
            return self.async_create_entry(title="", data=options)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_P1METER, description={"suggested_value": "sensor.power_actual"}): str,
                vol.Required(CONF_MQTTLOG): bool,
            }),
        )


class ZendureConnectionError(HomeAssistantError):
    """Error to indicate there is a connection issue with Zendure Integration."""

    def __init__(self) -> None:
        """Initialize the connection error."""
        super().__init__("Zendure Integration")
