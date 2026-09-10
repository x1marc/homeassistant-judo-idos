"""Diagnostics support for the JUDO i-dos integration.

Lets a user download a redacted snapshot of the config entry + the last
coordinator data via Settings → Devices & Services → JUDO i-dos → ⋮ →
"Download diagnostics". Credentials and the serial number are stripped so the
file can be shared in a bug report safely.
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_SERIAL, DOMAIN
from .coordinator import MyJudoCoordinator

# Anything identifying the account or device is removed. CONF_SERIAL is
# "serial_number", which is also the key of the serial sensor in coordinator
# data, so this covers both places.
TO_REDACT = {"username", "password", CONF_SERIAL, "serial_number", "token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: MyJudoCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "entry": {
            "title": entry.title,
            "version": entry.version,
            "data": async_redact_data(entry.data, TO_REDACT),
            "options": dict(entry.options),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_seconds": (
                coordinator.update_interval.total_seconds()
                if coordinator.update_interval
                else None
            ),
            "data": async_redact_data(coordinator.data or {}, TO_REDACT),
        },
    }
