from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from homeassistant.components import persistent_notification
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import judo_get
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Connection-failure notification handling
_FAIL_THRESHOLD = 3
_NOTIF_ID_ERROR = "myjudo_connection_error"
_NOTIF_ID_OK = "myjudo_connection_restored"

# i-dos error/warning codes (from the JUDO portal: optisoftWarnings["dos"]).
_ERROR_STATES: dict[int, str] = {
    0:  "OK",
    1:  "Störung! Pumpenantrieb defekt",
    2:  "Störung! Minerallösungserkennung defekt",
    3:  "Minerallösungsbehälter leer",
    15: "Minerallösungsvorrat gering",
    16: "Reichweite des Minerallösungsbehälters überschritten",
    17: "Mindesthaltbarkeitsdatum der Minerallösung überschritten",
}


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
        # Track consecutive failures for notification handling
        self._consecutive_failures = 0
        self._error_notified = False
        # Cached entity_id for logbook entries (resolved lazily)
        self._logbook_entity_id: str | None = None

    def _resolve_logbook_entity(self) -> str | None:
        """Find a real entity_id of this device for logbook entries (cached)."""
        if self._logbook_entity_id:
            return self._logbook_entity_id
        registry = er.async_get(self.hass)
        prefix = f"myjudo_{self._serial}_"
        for entity in registry.entities.values():
            if entity.platform == DOMAIN and entity.unique_id.startswith(prefix):
                self._logbook_entity_id = entity.entity_id
                return self._logbook_entity_id
        return None

    async def _login_and_connect(self) -> str:
        """Login + connect, returns a valid token. Raises UpdateFailed on error."""
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

        conn = await judo_get({
            "token": token,
            "group": "register",
            "command": "connect",
            "parameter": "i-dos",
            "serial number": self._serial,
        })
        if not conn:
            raise UpdateFailed("JUDO server not responding on connect (timeout).")
        if conn.get("status") != "ok":
            raise UpdateFailed(f"Connect rejected: {conn.get('data')}")
        _LOGGER.debug("JUDO connect ok")
        await asyncio.sleep(0.3)
        return token

    async def async_set_concentration(self, value: str) -> None:
        """Set dosing concentration (minimal/normal/maximal), then refresh."""
        token = await self._login_and_connect()
        resp = await judo_get({
            "token": token,
            "group": "settings",
            "command": "concentration adjustment",
            "parameter": value,
        })
        if not resp or resp.get("status") != "ok":
            raise UpdateFailed(f"Set concentration failed: {resp.get('data') if resp else 'no response'}")
        _LOGGER.info("JUDO dosing concentration set to '%s'", value)
        await self.async_request_refresh()

    async def _async_update_data(self) -> dict:
        """Wraps the actual fetch with failure-counting + notification handling."""
        try:
            data = await self._fetch_data()
        except UpdateFailed as err:
            self._consecutive_failures += 1
            _LOGGER.debug(
                "JUDO update failed (%d in a row): %s",
                self._consecutive_failures, err,
            )
            if self._consecutive_failures >= _FAIL_THRESHOLD and not self._error_notified:
                self._error_notified = True
                # Clear any "restored" note, raise the error note
                persistent_notification.async_dismiss(self.hass, _NOTIF_ID_OK)
                persistent_notification.async_create(
                    self.hass,
                    title="⚠️ JUDO i-dos – Datenabruf gestört",
                    message=(
                        f"Der Datenabruf ist {self._consecutive_failures}× in Folge "
                        f"fehlgeschlagen.\n\nLetzter Fehler: {err}\n\n"
                        "Die Integration versucht es beim nächsten Intervall erneut."
                    ),
                    notification_id=_NOTIF_ID_ERROR,
                )
            raise

        # Success: if we were in an error state, clear it and notify recovery
        if self._error_notified:
            self._error_notified = False
            persistent_notification.async_dismiss(self.hass, _NOTIF_ID_ERROR)
            persistent_notification.async_create(
                self.hass,
                title="✅ JUDO i-dos – wieder erreichbar",
                message="Der Datenabruf funktioniert wieder. Alle Werte sind aktuell.",
                notification_id=_NOTIF_ID_OK,
            )
        self._consecutive_failures = 0

        # Log successful fetch into the integration's logbook/activity
        entity_id = self._resolve_logbook_entity()
        if entity_id:
            self.hass.bus.async_fire(
                "logbook_entry",
                {
                    "name": "JUDO i-dos",
                    "message": "Daten erfolgreich abgerufen",
                    "entity_id": entity_id,
                    "domain": DOMAIN,
                },
            )
        return data

    async def _fetch_data(self) -> dict:
        now = datetime.now()

        token = await self._login_and_connect()

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

        # Mineral solution (i-dos specific)
        dilution   = await _get("info", "dilution quantity")      # remaining ml
        tanktype   = await _get("info", "rfid tank type")         # tank capacity ml
        concentr   = await _get("settings", "concentration adjustment")  # e.g. "normal"
        errstate   = await _get("state", "error state")           # 0 = ok
        dil_range  = await _get("consumption", "dilution range")  # remaining range
        dil_type   = await _get("info", "rfid dilution type")     # e.g. "jul-c"
        dil_expiry = await _get("state", "dilution expiry state") # 0 = ok
        dil_qstate = await _get("state", "dilution quantity state")  # 0 = ok
        ec_conn    = await _get("state", "electrical control connection state")  # 0 = ok

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

        # Mineral solution level: remaining / tank capacity -> percent
        mineral_ml   = _int(dilution.get("data"))
        tank_ml      = _int(tanktype.get("data"))
        mineral_pct  = None
        if mineral_ml is not None and tank_ml:
            mineral_pct = round(min(100.0, mineral_ml / tank_ml * 100), 1)

        # Error state -> human readable (i-dos warning codes)
        err = _int(errstate.get("data"))
        error_text = _ERROR_STATES.get(err, f"Code {err}") if err is not None else None

        # Binary-ish state values: 0 = ok, anything else = problem
        def _ok_state(raw, ok="OK", problem="Warnung") -> str | None:
            v = _int(raw)
            if v is None:
                return None
            return ok if v == 0 else f"{problem} ({v})"

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
            # mineral solution (i-dos)
            "mineral_level":      mineral_pct,                 # %
            "mineral_remaining":  mineral_ml,                  # ml
            "mineral_capacity":   tank_ml,                     # ml
            "mineral_range":      _int(dil_range.get("data")), # remaining range
            "mineral_type":       _str(dil_type.get("data")),  # e.g. "jul-c"
            "dosing_setting":     _str(concentr.get("data")),  # e.g. "normal"
            "error_state":        error_text,                  # "OK" / warning text
            "mineral_expiry_state":  _ok_state(dil_expiry.get("data"), problem="MHD-Warnung"),
            "mineral_quantity_state": _ok_state(dil_qstate.get("data"), problem="Menge niedrig"),
            "ec_connection_state":   _ok_state(ec_conn.get("data"), problem="getrennt"),
            # device info / diagnostics
            "devcomm_version":  _str(devcomm.get("data")),
            "init_date":        init_date,
            "service_date":     service_date,
            "device_age":       device_age,
            "serial_number":    self._serial,
        }
