"""Config flow for AlleycaTV."""
from __future__ import annotations

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from . import DOMAIN


class AlleycaTVConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the config flow for AlleycaTV."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Handle initial setup step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            return self.async_create_entry(title="AlleycaTV", data=user_input)

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Optional("topic_prefix", default="alleycatv"): str,
                vol.Optional("server_url",   default="http://192.168.1.100"): str,
            }),
            description_placeholders={
                "mqtt_info": "Ensure the MQTT integration is configured before proceeding.",
                "server_info": "Enter the HTTP base URL of the AlleycaTV server (e.g. http://192.168.1.100).",
            },
        )
