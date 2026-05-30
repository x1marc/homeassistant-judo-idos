from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .api import judo_get
from .const import DOMAIN, CONF_SERIAL, DEFAULT_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required("username"): str,
        vol.Required("password"): str,
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
    _LOGGER.debug("JUDO login: %s", login)

    if login.get("status") != "ok" or "token" not in login:
        _LOGGER.warning("JUDO login failed: %s", login.get("data"))
        return "invalid_auth"

    token = login["token"]

    # Step 2: Connect to verify serial
    conn = await judo_get({
        "token": token,
        "group": "register",
        "command": "connect",
        "parameter": "i-dos",
        "serial number": serial,
    })
    _LOGGER.debug("JUDO connect: %s", conn)

    if conn.get("status") != "ok":
        _LOGGER.warning("JUDO connect failed: %s", conn.get("data"))
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
        return MyJudoOptionsFlow(config_entry)


class MyJudoOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.data.get("scan_interval", DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("scan_interval", default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=5, max=60)
                ),
            }),
        )
