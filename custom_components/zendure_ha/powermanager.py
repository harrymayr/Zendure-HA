"""Power manager."""

from __future__ import annotations
from dataclasses import dataclass
from datetime import timedelta, datetime
import logging
from typing import Any
from paho.mqtt import client as mqtt_client
from .sensor import ZendureSensor
from .hyper2000 import Hyper2000
import numpy as np

_LOGGER = logging.getLogger(__name__)


class PowerManager:
    """The Power manager."""

    def __init__(self) -> None:
        """Initialize PowerManager."""
        self.next_update = datetime.now()
        self.hypers: list[Hyper2000] = []
        self.phases: list[PhaseData] = []
        self.last_power = 0
        self.use_one = True

        self.charge_max: int = 0
        self.charge_min: int = 0
        self.charge_capacity = 0
        self._charge_device: PhaseDevice | None = None

        self.discharge_max: int = 0
        self.discharge_min: int = 0
        self.discharge_capacity = 0
        self._discharge_device: PhaseDevice | None = None

    def update_manual(self, client: mqtt_client.Client, power: int, total: ZendureSensor, delta: ZendureSensor) -> None:
        _LOGGER.info(f"update_manual {power}")
        self.update_settings()
        for h in self.hypers:
            if "Phase" in h.sensors and h.busy > 0:
                h.busy -= 1
                _LOGGER.info(f"update_matching {h.name} busy")
                return

        self.last_power = power
        currpower = sum(h.last_power for h in self.hypers)
        total.update_value(currpower)
        delta.update_value(abs(power) - currpower)
        _LOGGER.info(f"update_manual {power} {power - currpower} {currpower}")
        if currpower == power:
            return

        if power < 0:
            self._update_discharge(client, abs(power))
        else:
            self._update_charge(client, power)

    def update_matching(self, client: mqtt_client.Client, power: int, total: ZendureSensor, delta: ZendureSensor) -> None:
        self.update_settings()
        if not self.hypers:
            _LOGGER.info("update_matching => no hypers")
            return

        discharge = 0
        charge = 0
        for h in self.hypers:
            if "Phase" in h.sensors and h.busy > 0:
                h.busy -= 1
                _LOGGER.info(f"update_matching {h.name} busy =>  {power}")
                return
            discharge += h.sensors["packInputPower"].as_int
            charge += h.sensors["outputPackPower"].as_int

        _LOGGER.info(f"update_matching {power} {discharge} {charge}")
        delta.update_value(power)

        if discharge > 0:
            discharge += power
            total.update_value(discharge)
            self._update_discharge(client, discharge)
        elif charge > 0:
            charge -= power
            total.update_value(charge)
            self._update_charge(client, charge)
        elif power < 0:
            self._update_charge(client, abs(power))
        else:
            self._update_discharge(client, power)

    def _update_charge(self, client: mqtt_client.Client, power: int) -> None:
        _LOGGER.info(f"Charging: {power} of {self.charge_max}")

        if power == 0:
            for p in self.phases:
                for d in p.devices:
                    d.hyper.update_power(client, 0, 0, 0)

        elif power > self.charge_max:
            for p in self.phases:
                _LOGGER.info(f"Phase {p.phase} charging max: {p.charge_max} total max: {self.charge_max}")
                for d in p.devices:
                    d.hyper.update_power(client, 1, d.charge_max, 0)

        elif (power < 330 and not self.use_one) or (power < 400 and self.use_one):
            self.use_one = True
            for p in self.phases:
                _LOGGER.info(f"Phase {p.phase} discharging max: {p.discharge_max} total max: {self.discharge_max}")
                for d in p.devices:
                    d.hyper.update_power(client, 1, power if d == self._charge_device else 0, 0)
        else:
            self.use_one = False
            power_square = power * power
            for p in self.phases:
                if p.charge_max == 0:
                    continue
                phase_power = int(power_square * p.charge_facta + power * p.charge_factb + p.charge_factc)
                phase_square = phase_power * phase_power
                for d in p.devices:
                    dev_power = int(phase_square * d.charge_facta + phase_power * d.charge_factb + d.charge_factc)
                    d.hyper.update_power(client, 1, max(0, dev_power), 0)

    def _update_discharge(self, client: mqtt_client.Client, power: int) -> None:
        _LOGGER.info(f"Discharging: {power} of {self.discharge_max}")
        power_square = power * power

        if power == 0:
            for p in self.phases:
                for d in p.devices:
                    d.hyper.update_power(client, 0, 0, 0)

        elif power > self.discharge_max:
            for p in self.phases:
                _LOGGER.info(f"Phase {p.phase} discharging max: {p.discharge_max} total max: {self.discharge_max}")
                for d in p.devices:
                    d.hyper.update_power(client, 0, 0, d.discharge_max)

        elif (power < 330 and not self.use_one) or (power < 400 and self.use_one):
            self.use_one = True
            for p in self.phases:
                _LOGGER.info(f"Phase {p.phase} discharging max: {p.discharge_max} total max: {self.discharge_max}")
                for d in p.devices:
                    d.hyper.update_power(client, 0, 0, power if d == self._discharge_device else 0)
        else:
            self.use_one = False
            for p in self.phases:
                if p.discharge_max == 0:
                    continue
                phase_power = int(power_square * p.discharge_facta + power * p.discharge_factb + p.discharge_factc)
                _LOGGER.info(f"Phase {p.phase} discharging: {phase_power}  phase max: {p.discharge_max} total max: {self.discharge_max}")

                phase_square = phase_power * phase_power
                for d in p.devices:
                    dev_power = int(phase_square * d.discharge_facta + phase_power * d.discharge_factb + d.discharge_factc)
                    d.hyper.update_power(client, 0, 0, max(0, dev_power))

    def update_settings(self) -> None:
        if self.next_update > datetime.now():
            return

        self.next_update = datetime.now() + timedelta(minutes=2)
        self.charge_max: int = 0
        self.charge_min: int = 0
        self.charge_capacity = 0
        self._charge_device = None

        self.discharge_max: int = 0
        self.discharge_min: int = 0
        self.discharge_capacity = 0
        self._discharge_device = None
        self.phases = [PhaseData(0, []), PhaseData(1, []), PhaseData(2, [])]
        for h in self.hypers:
            if "Phase" not in h.sensors:
                continue
            # get device settings
            level = h.sensors["electricLevel"].as_int
            batcount = h.sensors["packNum"].as_int
            levelmin = h.sensors["minSoc"].as_float
            levelmax = h.sensors["socSet"].as_float
            phase_id = h.sensors["Phase"].as_int
            phase = self.phases[int(phase_id) if phase_id else 0]
            d = PhaseDevice(h)
            phase.devices.append(d)

            # get charge settings
            d.charge_max = 1200 if level < levelmax else 0
            if d.charge_max > 0:
                d.charge_capacity = int(batcount * max(0, levelmax - level))
                phase.charge_max += d.charge_max
                phase.charge_capacity += d.charge_capacity
                self.charge_capacity += d.charge_capacity
                if self._charge_device is None or d.charge_capacity > self._charge_device.charge_capacity:
                    self._charge_device = d

            # get discharge settings
            d.discharge_max = 800 if level > levelmin else 0
            if d.discharge_max > 0:
                d.discharge_capacity = int(batcount * max(0, level - levelmin))
                phase.discharge_max += d.discharge_max
                phase.discharge_capacity += d.discharge_capacity
                self.discharge_capacity += d.discharge_capacity
                if self._discharge_device is None or d.discharge_capacity > self._discharge_device.discharge_capacity:
                    self._discharge_device = d

        # update the charge/discharge per phase
        for p in self.phases:
            p.charge_total = p.charge_max
            p.charge_max = min(p.charge_max, p.charge_allow)
            self.charge_max += p.charge_max
            p.discharge_total = p.discharge_max
            p.discharge_max = min(p.discharge_max, p.discharge_allow)
            self.discharge_max += p.discharge_max
        for p in self.phases:
            p.update_settings(self)

        # update the charge/discharge devices
        _LOGGER.info(f"Valid charging: {self.charge_max}")
        _LOGGER.info(f"Valid discharging: {self.discharge_max}")


@dataclass
class PhaseData:
    """Data for each phase."""

    phase: int
    devices: list[PhaseDevice]
    charge_capacity: int = 0
    charge_allow: int = 1200
    charge_total: int = 0
    charge_max: int = 0
    charge_min: int = 0
    charge_facta: float = 0
    charge_factb: float = 0
    charge_factc: float = 0
    discharge_allow: int = 800
    discharge_total: int = 0
    discharge_capacity: int = 0
    discharge_max: int = 0
    discharge_min: int = 0
    discharge_facta: float = 0
    discharge_factb: float = 0
    discharge_factc: float = 0

    def update_settings(self, manager: PowerManager) -> None:
        if not self.devices:
            return

        percent = self.charge_capacity / manager.charge_capacity
        x = np.array([0, manager.charge_max * 0.25, manager.charge_max * 0.5, manager.charge_max])
        y = np.array([0, percent * manager.charge_max * 0.25, percent * manager.charge_max * 0.5, self.charge_allow])
        z = np.polyfit(x, y, 2)
        self.charge_facta = z[0]
        self.charge_factb = z[1]
        self.charge_factc = z[2]
        _LOGGER.info(f"charging phase:{self.phase} pct: {int(percent * 100)} a: {self.charge_facta} b: {self.charge_factb}")

        percent = self.discharge_capacity / manager.discharge_capacity
        x = np.array([0, manager.discharge_max * 0.25, manager.discharge_max * 0.5, manager.discharge_max])
        y = np.array([0, percent * manager.discharge_max * 0.25, percent * manager.discharge_max * 0.5, self.discharge_allow])
        z = np.polyfit(x, y, 2)
        self.discharge_facta = z[0]
        self.discharge_factb = z[1]
        self.discharge_factc = z[2]
        _LOGGER.info(f"discharging phase:{self.phase} pct: {int(percent * 100)} a: {self.discharge_facta} b: {self.discharge_factb}")

        for d in self.devices:
            if self.charge_total > 0:
                d.charge_max = int(d.charge_max * d.charge_max / self.charge_total)
                _LOGGER.info(f"max phase:{d.charge_max} max hyper: {self.charge_max}")

                percent = d.charge_capacity / self.charge_capacity
                x = np.array([0, self.charge_max * 0.25, self.charge_max * 0.5, self.charge_max])
                y = np.array([0, percent * self.charge_max * 0.25, percent * self.charge_max * 0.5, d.charge_max])
                z = np.polyfit(x, y, 2)
                d.charge_facta = z[0]
                d.charge_factb = z[1]
                d.charge_factc = z[2]
                _LOGGER.info(f"charging phase:{x}")
                _LOGGER.info(f"charging phase:{y}")
                _LOGGER.info(
                    f"charging h:{self.phase} pct: {int(percent * 100)} cap:{d.charge_capacity} a: {d.charge_facta} b: {d.charge_factb}"
                )
            else:
                d.charge_facta = 0
                d.charge_factb = 0
                d.charge_factc = 0

            if self.discharge_total > 0:
                d.discharge_max = int(d.discharge_max * d.discharge_max / self.discharge_total)
                _LOGGER.info(f"max phase:{d.discharge_max} max hyper: {self.discharge_max}")
                percent = d.discharge_capacity / self.discharge_capacity
                x = np.array([0, self.discharge_max * 0.25, self.discharge_max * 0.5, self.discharge_max])
                y = np.array([0, percent * self.discharge_max * 0.25, percent * self.discharge_max * 0.5, d.discharge_max])
                z = np.polyfit(x, y, 2)
                d.discharge_facta = z[0]
                d.discharge_factb = z[1]
                d.discharge_factc = z[2]
            else:
                d.discharge_facta = 0
                d.discharge_factb = 0
                d.discharge_factc = 0
            _LOGGER.info(f"charging phase:{x}")
            _LOGGER.info(f"charging phase:{y}")
            _LOGGER.info(
                f"discharge d:{self.phase} pct: {int(percent * 100)} cap:{d.discharge_capacity} / {self.discharge_capacity} a: {d.discharge_facta} b: {d.discharge_factb}"
            )


@dataclass
class PhaseDevice:
    """Class to hold phase data."""

    hyper: Hyper2000
    charge_max: int = 0
    charge_min: int = 0
    charge_capacity: int = 0
    charge_facta: float = 0
    charge_factb: float = 0
    charge_factc: float = 0

    discharge_max: int = 0
    discharge_min: int = 0
    discharge_capacity: int = 0
    discharge_facta: float = 0
    discharge_factb: float = 0
    discharge_factc: float = 0
