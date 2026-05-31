from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import judo_get
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


def _sum_values(raw) -> int | None:
    """Sum a space-separated value string, ignoring -1 (no data) entries.

    Example: " 46 75 53 180 82 51 -1" -> 487
    """
    if raw is None:
        return None
    try:
        total = 0
        found = False
        for part in str(raw).strip().split():
            v = int(part)
            if v >= 0:
                total += v
                found = True
        return total if found else 0
    except (ValueError, TypeError):
        return None


class MyJudoCoordinator(DataUpdateCoordinator):
    def __init__(
        self,
        hass: HomeAssistant,
        username: str,
        password: str,
        serial: str,
        scan_interval_minutes: int,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=scan_interval_minutes),
        )
        self._username = username
        self._password = password
        self._serial = serial

    async def _async_update_data(self) -> dict:
        now = datetime.now()

        # --- Login ---
        login = await judo_get({
            "group": "register",
            "command": "login",
            "msgnumber": "1",
            "name": "login",
            "user": self._username,
            "password": self._password,
            "role": "customer",
        })
        if not login:
            raise UpdateFailed(
                "JUDO server not responding (timeout) — likely a server-side "
                "outage at my-judo.com. Will retry next interval."
            )
        if login.get("status") != "ok" or "token" not in login:
            raise UpdateFailed(f"Login rejected: {login.get('data')} "
                               "(check username/password)")
        token = login["token"]
        _LOGGER.debug("JUDO login ok")
        await asyncio.sleep(0.3)

        # --- Connect to device ---
        conn = await judo_get({
            "token": token,
            "group": "register",
            "command": "connect",
            "parameter": "i-dos",
            "serial number": self._serial,
        })
        if not conn:
            raise UpdateFailed(
                "JUDO server not responding on connect (timeout). "
                "Will retry next interval."
            )
        if conn.get("status") != "ok":
            raise UpdateFailed(f"Connect rejected: {conn.get('data')} "
                               "(check serial number / device online?)")
        _LOGGER.debug("JUDO connect ok")
        await asyncio.sleep(0.3)

        # --- Fetch sensors SEQUENTIALLY ---
        # The device relay can only handle one request at a time. Parallel
        # requests (asyncio.gather) overload it and all time out. A small
        # delay between calls keeps the relay stable.
        async def _get(group: str, command: str, **extra) -> dict:
            params = {"token": token, "group": group, "command": command}
            params.update({k: str(v) for k, v in extra.items()})
            result = await judo_get(params)
            await asyncio.sleep(0.3)
            return result

        # Live / status values
        wt       = await _get("consumption", "water total")
        wc       = await _get("consumption", "water current")
        wa       = await _get("consumption", "water average")
        salt     = await _get("consumption", "salt quantity")
        actual   = await _get("consumption", "actual quantity")
        hardness = await _get("info", "natural hardness")

        # Consumption time series — summed to single totals
        daily   = await _get("consumption", "water daily",
                             year=now.year, month=now.month, day=now.day)
        weekly  = await _get("consumption", "water weekly",
                             year=now.year, month=now.month, day=now.day)
        monthly = await _get("consumption", "water monthly",
                             year=now.year, month=now.month)
        yearly  = await _get("consumption", "water yearly", year=now.year)

        # Static device info (rarely changes, but cheap to fetch)
        devcomm    = await _get("version", "devcomm version")
        init_dt    = await _get("contract", "init date")
        service_dt = await _get("contract", "service date")

        def _m3(raw) -> float | None:
            try:
                return round(int(str(raw).strip().split()[0]) / 1000, 3)
            except Exception:
                return None

        def _int(val) -> int | None:
            try:
                return int(str(val).strip())
            except Exception:
                return None

        # Total water in liters (first value of "water total" is already liters)
        def _total_l(raw) -> int | None:
            try:
                return int(str(raw).strip().split()[0])
            except Exception:
                return None

        def _ts(raw) -> datetime | None:
            """Unix timestamp string -> timezone-aware datetime (for HA timestamp sensors)."""
            try:
                return datetime.fromtimestamp(int(str(raw).strip()), tz=timezone.utc)
            except Exception:
                return None

        def _str(val) -> str | None:
            s = str(val).strip() if val is not None else ""
            return s or None

        total_l = _total_l(wt.get("data"))
        today_l = _sum_values(daily.get("data"))
        week_l  = _sum_values(weekly.get("data"))
        month_l = _sum_values(monthly.get("data"))
        year_l  = _sum_values(yearly.get("data"))

        init_date = _ts(init_dt.get("data"))
        service_date = _ts(service_dt.get("data"))

        # Device age in years (from commissioning date)
        device_age = None
        if init_date is not None:
            delta = datetime.now(timezone.utc) - init_date
            device_age = round(delta.days / 365.25, 1)

        return {
            # m³ values
            "water_total":      round(total_l / 1000, 3) if total_l is not None else None,
            "water_month":      round(month_l / 1000, 3) if month_l is not None else None,
            "water_year":       round(year_l / 1000, 3) if year_l is not None else None,
            # same values in liters (easier to read)
            "water_total_l":    total_l,
            "water_month_l":    month_l,
            "water_year_l":     year_l,
            # liter values
            "water_current":    _int(wc.get("data")),
            "water_average":    _int(wa.get("data")),
            "water_today":      today_l,
            "water_week":       week_l,
            # other
            "salt_quantity":    _int(salt.get("data")),
            "actual_quantity":  _int(actual.get("data")),
            "natural_hardness": _int(hardness.get("data")),
            # device info / diagnostics
            "devcomm_version":  _str(devcomm.get("data")),
            "init_date":        init_date,
            "service_date":     service_date,
            "device_age":       device_age,
            "serial_number":    self._serial,
        }
