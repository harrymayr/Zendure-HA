"""Interfaces with the Zendure Integration binairy sensors."""
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .hyper2000 import Hyper2000

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
):
    Hyper2000.addBinarySensors = async_add_entities
