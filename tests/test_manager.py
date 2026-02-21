"""Unit tests for ZendureManager.power_discharge() operation state logic.

Covers the three combinations of setpoint / discharge-list that determine
whether the manager reports DISCHARGE or IDLE.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from custom_components.zendure_ha.const import DeviceState, ManagerState  # noqa: E402
from custom_components.zendure_ha.manager import ZendureManager  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────────────

class FakeManager:
    """Minimal fake ZendureManager for power_discharge() tests."""

    def __init__(self, *, discharge_devices: list | None = None) -> None:
        self.operationstate = MagicMock()
        self.discharge = discharge_devices or []
        self.charge = []
        self.idle = []
        self.charge_time = datetime.max
        self.pwr_low = 0
        self.discharge_produced = 0
        self.discharge_optimal = 0
        self.discharge_limit = 2000
        self.discharge_weight = (
            sum(d.pwr_max * d.electricLevel.asInt for d in self.discharge) or 1
        )
        self.idle_lvlmax = 80


def make_discharge_device(*, soc: int = 50) -> SimpleNamespace:
    """Minimal fake device that can participate in the discharge loop."""
    return SimpleNamespace(
        electricLevel=SimpleNamespace(asInt=soc),
        pwr_max=2000,
        pwr_produced=0,
        state=DeviceState.ACTIVE,
        discharge_start=200,
        discharge_optimal=500,
        pwr_offgrid=0,
        power_discharge=AsyncMock(return_value=0),
    )


# ══════════════════════════════════════════════════════════════════════════════
# power_discharge() — operation state
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_discharge_state_idle_when_no_discharge_devices():
    """setpoint > 0, discharge list empty → state is IDLE."""
    mgr = FakeManager(discharge_devices=[])

    await ZendureManager.power_discharge(mgr, setpoint=100)

    mgr.operationstate.update_value.assert_called_once_with(ManagerState.IDLE.value)


@pytest.mark.asyncio
async def test_discharge_state_discharge_when_devices_available():
    """Positive setpoint with at least one device able to discharge → DISCHARGE."""
    device = make_discharge_device(soc=50)
    mgr = FakeManager(discharge_devices=[device])

    await ZendureManager.power_discharge(mgr, setpoint=100)

    mgr.operationstate.update_value.assert_called_once_with(ManagerState.DISCHARGE.value)


@pytest.mark.asyncio
async def test_discharge_state_idle_when_setpoint_zero():
    """Setpoint == 0: state is IDLE regardless of available discharge devices."""
    device = make_discharge_device(soc=50)
    mgr = FakeManager(discharge_devices=[device])

    await ZendureManager.power_discharge(mgr, setpoint=0)

    mgr.operationstate.update_value.assert_called_once_with(ManagerState.IDLE.value)
