"""Constants for Zendure."""

from datetime import timedelta
from enum import Enum

DOMAIN = "zendure_ha"

CONF_APPTOKEN = "token"
CONF_P1METER = "p1meter"
CONF_PRICE = "price"
CONF_MQTTLOG = "mqttlog"
CONF_MQTTLOCAL = "mqttlocal"
CONF_MQTTSERVER = "mqttserver"
CONF_SIM = "simulation"
CONF_MQTTPORT = "mqttport"
CONF_MQTTUSER = "mqttuser"
CONF_MQTTPSW = "mqttpsw"
CONF_WIFISSID = "wifissid"
CONF_WIFIPSW = "wifipsw"

CONF_HAKEY = "C*dafwArEOXK"


class AcMode:
    INPUT = 1
    OUTPUT = 2


class DeviceState(Enum):
    OFFLINE = 0
    SOCEMPTY = 1
    SOCFULL = 2
    INACTIVE = 3
    STARTING = 4
    ACTIVE = 5


class ManagerState(Enum):
    IDLE = 0
    CHARGING = 1
    DISCHARGING = 2
    WAITING = 3


class SmartMode:
    NONE = 0
    MANUAL = 1
    MATCHING = 2
    MATCHING_DISCHARGE = 3
    MATCHING_CHARGE = 4

    SOCFULL = 1
    SOCEMPTY = 2
    ZENSDK = 2
    CONNECTED = 10

    TIMEFAST = 2.2  # Fast update interval after significant change
    TIMEZERO = 4  # Normal update interval

    # Standard deviation thresholds for detecting significant changes
    P1_STDDEV_FACTOR = 3.5  # Multiplier for P1 meter stddev calculation
    P1_STDDEV_MIN = 15  # Minimum stddev value for P1 changes (watts)
    SETPOINT_STDDEV_FACTOR = 3.5  # Multiplier for power average stddev calculation
    SETPOINT_STDDEV_MIN = 20  # Minimum stddev value for power average (watts)

    P1_MIN_UPDATE = timedelta(milliseconds=400)

    POWER_START = 40  # Minimum Power (W) for starting a device
    POWER_TOLERANCE = 5  # Device-level power tolerance (W) before updating
