"""Config flow for Zendure Integration integration."""

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import selector

from .api import Api
from .const import CONF_BROKER, CONF_BROKERPSW, CONF_BROKERUSER, CONF_P1METER, CONF_WIFIPSW, CONF_WIFISSID, DOMAIN

_LOGGER = logging.getLogger(__name__)


class ZendureOptionsFlowHandler(OptionsFlow):
    """Handles the options flow."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self._conf_app_id: str | None = None

    async def async_step_init(self, user_input: Any = None) -> ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            options = self.config_entry.options | user_input
            return self.async_create_entry(title="", data=options)

        data_schema = vol.Schema({vol.Required(CONF_P1METER, description={"suggested_value": "sensor.power_actual"}): str})

        return self.async_show_form(step_id="init", data_schema=data_schema)


class ZendureConnectionError(HomeAssistantError):
    """Error to indicate there is a connection issue with Zendure Integration."""

    def __init__(self) -> None:
        """Initialize the connection error."""
        super().__init__("Zendure Integration")


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    _LOGGER.debug("Check API connection")
    api = Api(hass, data)
    if not await api.connect():
        raise ZendureConnectionError

    return {"title": f"Zendure Integration - {data[CONF_USERNAME]}"}


class ZendureConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Zendure Integration."""

    VERSION = 1
    _input_data: dict[str, Any]

    @staticmethod
    @callback
    def async_get_options_flow(_config_entry: ConfigEntry) -> ZendureOptionsFlowHandler:
        """Get the options flow for this handler."""
        return ZendureOptionsFlowHandler()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # The form has been filled in and submitted, so process the data provided.
            try:
                # Validate that the setup data is valid and if not handle errors.
                # The errors["base"] values match the values in your strings.json and translation files.
                info = await validate_input(self.hass, user_input)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "cannot_connect"

            if "base" not in errors:
                # Validation was successful, so create a unique id for this instance of your integration
                # and create the config entry.
                await self.async_set_unique_id(info.get("title"))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        # Show initial form.
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD,
                    ),
                ),
                vol.Required(CONF_P1METER, description={"suggested_value": "sensor.power_actual"}): str,
                # vol.Optional(CONF_BROKER): str,
                # vol.Optional(CONF_BROKERUSER): str,
                # vol.Optional(CONF_BROKERPSW): selector.TextSelector(
                #     selector.TextSelectorConfig(
                #         type=selector.TextSelectorType.PASSWORD,
                #     ),
                # ),
                # vol.Optional(CONF_WIFISSID): str,
                # vol.Optional(CONF_WIFIPSW): selector.TextSelector(
                #     selector.TextSelectorConfig(
                #         type=selector.TextSelectorType.PASSWORD,
                #     ),
                # ),
            }),
            errors=errors,
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add reconfigure step to allow to reconfigure a config entry."""
        errors: dict[str, str] = {}
        config_entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])

        if user_input is dict[str, Any]:
            try:
                user_input[CONF_P1METER] = config_entry.data.get(CONF_P1METER, None)
                # user_input[CONF_BROKER] = config_entry.data.get(CONF_BROKER, None)
                # user_input[CONF_BROKERUSER] = config_entry.data.get(CONF_BROKERUSER, None)
                # user_input[CONF_BROKERPSW] = config_entry.data.get(CONF_BROKERPSW, None)
                # user_input[CONF_WIFISSID] = config_entry.data.get(CONF_WIFISSID, None)
                # user_input[CONF_WIFIPSW] = config_entry.data.get(CONF_WIFIPSW, None)
                await validate_input(self.hass, user_input)
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    config_entry,
                    unique_id=config_entry.unique_id,
                    data={**config_entry.data, **user_input},
                    reason="reconfigure_successful",
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Required(CONF_USERNAME, default=config_entry.data[CONF_USERNAME]): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_P1METER, description={"suggested_value": "sensor.power_actual"}): str,
                # vol.Optional(CONF_BROKER): str,
                # vol.Optional(CONF_BROKERUSER): str,
                # vol.Optional(CONF_BROKERPSW): selector.TextSelector(
                #     selector.TextSelectorConfig(
                #         type=selector.TextSelectorType.PASSWORD,
                #     ),
                # ),
                # vol.Optional(CONF_WIFISSID): str,
                # vol.Optional(CONF_WIFIPSW): selector.TextSelector(
                #     selector.TextSelectorConfig(
                #         type=selector.TextSelectorType.PASSWORD,
                #     ),
                # ),
            }),
            errors=errors,
        )
