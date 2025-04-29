"""Constants for the Zendure Integration integration."""

from enum import Enum

DOMAIN = "zendure_ha"

CONF_P1METER = "p1meter"
CONF_MQTTLOG = "mqttlog"
CONF_MQTTLOCAL = "mqttlocal"
CONF_MQTTSERVER = "mqttserver"
CONF_MQTTPORT = "mqttport"
CONF_MQTTUSER = "mqttuser"
CONF_MQTTPSW = "mqttpsw"
CONF_WIFISSID = "wifissid"
CONF_WIFIPSW = "wifipsw"


class ManagerState(Enum):
    IDLE = 0
    CHARGING = 1
    DISCHARGING = 2


class SmartMode:
    NONE = 0
    MANUAL = 1
    MATCHING = 2
    FAST_UPDATE = 100
    MIN_POWER = 50
    START_POWER = 100
    TIMEFAST = 3
    TIMEZERO = 5
    TIMEIDLE = 10
