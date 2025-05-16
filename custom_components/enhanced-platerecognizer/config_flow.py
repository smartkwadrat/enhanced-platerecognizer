"""Config flow for Enhanced PlateRecognizer."""
import os
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.const import CONF_NAME, CONF_SOURCE
from homeassistant.core import callback
from homeassistant.helpers import entity_registry

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_REGION,
    CONF_CONSECUTIVE_CAPTURES,
    CONF_CAPTURE_INTERVAL,
    CONF_SAVE_FILE_FOLDER,
    CONF_SAVE_TIMESTAMPED_FILE,
    CONF_ALWAYS_SAVE_LATEST_FILE,
    CONF_MAX_IMAGES,
    CONF_TOLERATE_ONE_MISTAKE,
)

REGIONS = [
    "al", "ar", "au", "ba", "br", "ca-qc", "ch", "cl", "cn",
    "co", "cr", "cz", "de", "dk", "do", "ec", "es", "eu",
    "fi", "fr", "gb", "gr", "hr", "hu", "in", "it", "kr",
    "kw", "ky", "lb", "ma", "md", "me", "mn", "mt", "mx",
    "my", "nl", "no", "nz", "pa", "pe", "pl", "pr", "pt",
    "py", "qa", "ro", "rs", "ru", "sa", "se", "sg", "sk",
    "th", "tn", "tr", "tw", "ua", "us", "us-ca", "uy", "uz",
    "vn", "za"
]


class EnhancedPlateRecognizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Enhanced PlateRecognizer."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EnhancedPlateRecognizerOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        errors = {}
        registry = entity_registry.async_get(self.hass)
        camera_entities = [
            entity.entity_id for entity in registry.entities.values()
            if entity.domain == CAMERA_DOMAIN
        ]
        camera_options = {camera: camera for camera in sorted(camera_entities)}

        if not camera_options:
            return self.async_abort(reason="no_cameras")

        if user_input is not None:

            camera = user_input[CONF_SOURCE]
            await self.async_set_unique_id(f"{DOMAIN}_{camera}")
            self._abort_if_unique_id_configured()

            if not errors:
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, f"PlateRecognizer {camera}"),
                    data=user_input,
                )

        schema = vol.Schema({
            vol.Required(CONF_NAME, default="Enhanced PlateRecognizer"): str,
            vol.Required(CONF_API_KEY): str,
            vol.Required(CONF_SOURCE): vol.In(camera_options),
            vol.Optional(CONF_REGION, default="pl"): vol.In(REGIONS),
            vol.Optional(CONF_SAVE_TIMESTAMPED_FILE, default=True): bool,
            vol.Optional(CONF_ALWAYS_SAVE_LATEST_FILE, default=True): bool,
            vol.Optional(CONF_CONSECUTIVE_CAPTURES, default=1): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=5)
            ),
            vol.Optional(CONF_CAPTURE_INTERVAL, default=1.2): vol.All(
                vol.Coerce(float), vol.Range(min=1.0, max=2.0)
            ),
            vol.Optional(CONF_MAX_IMAGES, default=10): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=30)
            ),
            vol.Optional(CONF_TOLERATE_ONE_MISTAKE, default=False): bool,
        })

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )


class EnhancedPlateRecognizerOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Enhanced PlateRecognizer."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            save_folder = user_input.get(CONF_SAVE_FILE_FOLDER)
            if save_folder and not os.path.isdir(save_folder):
                try:
                    os.makedirs(save_folder, exist_ok=True)
                except (OSError, PermissionError):
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._get_options_schema(),
                        errors={CONF_SAVE_FILE_FOLDER: "invalid_folder"}
                    )
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._get_options_schema(),
        )

    def _get_options_schema(self):
        options = self.config_entry.options
        data = self.config_entry.data

        return vol.Schema({
            vol.Optional(
                CONF_REGION,
                default=options.get(CONF_REGION, data.get(CONF_REGION, "pl"))
            ): vol.In(REGIONS),
            vol.Optional(
                CONF_SAVE_TIMESTAMPED_FILE,
                default=options.get(CONF_SAVE_TIMESTAMPED_FILE, data.get(CONF_SAVE_TIMESTAMPED_FILE, True))
            ): bool,
            vol.Optional(
                CONF_ALWAYS_SAVE_LATEST_FILE,
                default=options.get(CONF_ALWAYS_SAVE_LATEST_FILE, data.get(CONF_ALWAYS_SAVE_LATEST_FILE, True))
            ): bool,
            vol.Optional(
                CONF_CONSECUTIVE_CAPTURES,
                default=options.get(CONF_CONSECUTIVE_CAPTURES, data.get(CONF_CONSECUTIVE_CAPTURES, 1))
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
            vol.Optional(
                CONF_CAPTURE_INTERVAL,
                default=options.get(CONF_CAPTURE_INTERVAL, data.get(CONF_CAPTURE_INTERVAL, 1.2))
            ): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=2.0)),
            vol.Optional(
                CONF_MAX_IMAGES,
                default=options.get(CONF_MAX_IMAGES, data.get(CONF_MAX_IMAGES, 10))
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
            vol.Optional(
                CONF_TOLERATE_ONE_MISTAKE,
                default=options.get(CONF_TOLERATE_ONE_MISTAKE, data.get(CONF_TOLERATE_ONE_MISTAKE, False))
            ): bool,
        })
