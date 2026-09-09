from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import judo_get
from .const import DOMAIN, CONF_SERIAL, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
        vol.Required(CONF_SERIAL): str,
        vol.Optional(
            "scan_interval", default=DEFAULT_SCAN_INTERVAL
        ): vol.All(vol.Coerce(int), vol.Range(min=5, max=60)),
    }
)


async def _try_login(username: str, password: str, serial: str) -> str | None:
    """Returns error key on failure, None on success."""
    # Step 1: Login
    login = await judo_get({
        "group": "register",
        "command": "login",
        "msgnumber": "1",
        "name": "login",
        "user": username,
        "password": password,
        "role": "customer",
    })
    # Do NOT log the full response — it carries the session token (see below).
    _LOGGER.debug("JUDO login status: %s", login.get("status"))

    if not login:
        # Empty = no/invalid response from server (timeout, outage)
        _LOGGER.warning("JUDO server not responding during login")
        return "cannot_connect"
    if login.get("status") != "ok" or "token" not in login:
        _LOGGER.warning("JUDO login rejected: %s", login.get("data"))
        return "invalid_auth"

    token = login["token"]

    # Step 2: Resolve the device model. register/show lists the account's
    # devices with their model id, e.g.
    #   [{"wtuType": "i-dos", "serial number": "NNNNN"}]
    # connect needs that model id as its "parameter" — hardcoding "i-dos" fails
    # on other models (e.g. i-dos eco) with "not connected: no electrical
    # control found". If show is unavailable we fall back to "i-dos".
    show = await judo_get({"token": token, "group": "register", "command": "show"})
    # DIAGNOSTIC (v1.14.2): dump the raw device list at WARNING level so it
    # surfaces without debug logging. For other models (i-dos eco, i-soft Pro)
    # this reveals the exact field names and model id that register/show returns
    # — needed to fix model detection. The session token is never in this data.
    _LOGGER.warning(
        "JUDO register/show diagnostic — status=%s data=%s",
        show.get("status"), show.get("data"),
    )
    wtu_type: str | None = None
    if show.get("status") == "ok":
        devices = show.get("data") or []
        match = next(
            (d for d in devices if str(d.get("serial number")).strip() == serial),
            None,
        )
        if match is not None:
            wtu_type = match.get("wtuType")
            _LOGGER.debug("JUDO device model for %s: %s", serial, wtu_type)
        elif devices:
            _LOGGER.warning(
                "JUDO serial %s not on this account (have: %s)",
                serial, [d.get("serial number") for d in devices],
            )
            return "serial_not_found"
    else:
        _LOGGER.debug(
            "JUDO register/show unavailable (%s); using default model",
            show.get("status"),
        )

    # Step 3: Connect to verify the device is reachable, using the model id.
    # DIAGNOSTIC (v1.14.2): show which parameter we actually send to connect.
    _LOGGER.warning(
        "JUDO connect diagnostic — parameter=%s serial=%s",
        wtu_type or "i-dos", serial,
    )
    conn = await judo_get({
        "token": token,
        "group": "register",
        "command": "connect",
        "parameter": wtu_type or "i-dos",
        "serial number": serial,
    })
    _LOGGER.debug("JUDO connect status: %s", conn.get("status"))

    if not conn:
        _LOGGER.warning("JUDO server not responding during connect")
        return "cannot_connect"
    if conn.get("status") != "ok":
        detail = str(conn.get("data") or "")
        _LOGGER.warning("JUDO connect rejected: %s", detail)
        if "no electrical control" in detail.lower():
            # Server + module reachable, but the module reports no link to the
            # device electronics (device offline/unpaired at the device end).
            return "no_electrical_control"
        return "cannot_connect"

    return None


class MyJudoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input["username"].strip()
            password = user_input["password"].strip()
            serial = user_input[CONF_SERIAL].strip()
            scan_interval = user_input.get("scan_interval", DEFAULT_SCAN_INTERVAL)

            try:
                error_key = await _try_login(username, password, serial)
            except Exception as exc:
                _LOGGER.warning("JUDO setup error: %s – %s", type(exc).__name__, exc)
                error_key = "cannot_connect"

            if error_key:
                errors["base"] = error_key
            else:
                await self.async_set_unique_id(f"myjudo_{serial}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"JUDO i-dos ({serial})",
                    data={
                        "username": username,
                        "password": password,
                        CONF_SERIAL: serial,
                        "scan_interval": scan_interval,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> MyJudoOptionsFlow:
        # OptionsFlow gets `self.config_entry` from the base class automatically
        # (HA 2024.11+); do not pass it into the constructor.
        return MyJudoOptionsFlow()


class MyJudoOptionsFlow(config_entries.OptionsFlow):
    # Note: do NOT define __init__ and store config_entry yourself — since
    # HA 2024.11 `self.config_entry` is provided automatically by the base
    # class. Storing it manually is deprecated/removed in newer versions.

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        # Show the value that is actually in effect: options take precedence,
        # falling back to the original setup value in data.
        current = self.config_entry.options.get(
            "scan_interval",
            self.config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("scan_interval", default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=60)
                ),
            }),
        )
