"""Config flow for Enhanced PlateRecognizer (kamery tylko przez config flow, ustawienia globalne przez YAML)."""

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.core import callback
from homeassistant.helpers import entity_registry

from .const import (
    DOMAIN,
    CONF_CAMERAS_CONFIG,
    CONF_CAMERA_ENTITY_ID,
    CONF_CAMERA_FRIENDLY_NAME,
    MAX_CAMERAS,
    CONF_NAME,
)

class EnhancedPlateRecognizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Config flow for Enhanced PlateRecognizer."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EnhancedPlateRecognizerOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        errors = {}

        registry = entity_registry.async_get(self.hass)
        available_camera_entities = [
            entity.entity_id
            for entity in registry.entities.values()
            if entity.domain == CAMERA_DOMAIN
        ]

        camera_options = {cam: cam for cam in sorted(available_camera_entities)}
        if not camera_options:
            return self.async_abort(reason="no_cameras")

        # Przygotuj pola formularza dla kamer
        schema_fields = {
            vol.Required(CONF_NAME, default="Enhanced PlateRecognizer"): str,
        }
        for i in range(1, MAX_CAMERAS + 1):
            schema_fields[vol.Optional(f"camera_{i}_entity_id")] = vol.In(camera_options)
            schema_fields[vol.Optional(f"camera_{i}_friendly_name")] = str

        if user_input is not None:
            cameras_config = []
            has_at_least_one_camera = False
            for i in range(1, MAX_CAMERAS + 1):
                cam_entity_id = user_input.get(f"camera_{i}_entity_id")
                cam_friendly_name = user_input.get(f"camera_{i}_friendly_name")
                if cam_entity_id:
                    has_at_least_one_camera = True
                    if not cam_friendly_name:
                        cam_friendly_name = cam_entity_id.split('.')[-1]
                    cameras_config.append({
                        CONF_CAMERA_ENTITY_ID: cam_entity_id,
                        CONF_CAMERA_FRIENDLY_NAME: cam_friendly_name,
                    })
            if not has_at_least_one_camera:
                errors["base"] = "at_least_one_camera"

            # Sprawdzenie unikalności nazw przyjaznych dla kamer
            friendly_names = [cam[CONF_CAMERA_FRIENDLY_NAME] for cam in cameras_config]
            if len(friendly_names) != len(set(friendly_names)):
                errors["base"] = "duplicate_camera_friendly_name"

            if not errors:
                self._abort_if_unique_id_configured()
                final_data = {
                    CONF_CAMERAS_CONFIG: cameras_config
                }
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, "Enhanced PlateRecognizer"),
                    data=final_data,
                )

        data_schema = vol.Schema(schema_fields)
        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={"max_cameras": MAX_CAMERAS}
        )


class EnhancedPlateRecognizerOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Enhanced PlateRecognizer."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self.config_entry = config_entry
        self.current_cameras_config = list(config_entry.options.get(
            CONF_CAMERAS_CONFIG,
            config_entry.data.get(CONF_CAMERAS_CONFIG, [])
        ))

    async def async_step_init(self, user_input=None):
        errors = {}

        registry = entity_registry.async_get(self.hass)
        available_camera_entities = [
            entity.entity_id
            for entity in registry.entities.values()
            if entity.domain == CAMERA_DOMAIN
        ]
        configured_camera_ids = {cam[CONF_CAMERA_ENTITY_ID] for cam in self.current_cameras_config}
        camera_options_to_add = {
            cam: cam for cam in sorted(available_camera_entities) if cam not in configured_camera_ids
        }

        if user_input is not None:
            updated_cameras_config = []
            # Edycja istniejących kamer
            for i, existing_cam_conf in enumerate(self.current_cameras_config):
                keep_camera = user_input.get(f"keep_camera_{i}", True)
                if keep_camera:
                    new_friendly_name = user_input.get(
                        f"camera_{existing_cam_conf[CONF_CAMERA_ENTITY_ID].replace('.', '_')}_friendly_name",
                        existing_cam_conf[CONF_CAMERA_FRIENDLY_NAME]
                    )
                    updated_cameras_config.append({
                        CONF_CAMERA_ENTITY_ID: existing_cam_conf[CONF_CAMERA_ENTITY_ID],
                        CONF_CAMERA_FRIENDLY_NAME: new_friendly_name
                    })
            # Dodanie nowej kamery
            if len(updated_cameras_config) < MAX_CAMERAS:
                new_camera_id = user_input.get("new_camera_entity_id")
                if new_camera_id:
                    new_camera_friendly_name = user_input.get("new_camera_friendly_name")
                    if not new_camera_friendly_name:
                        new_camera_friendly_name = new_camera_id.split('.')[-1]
                    if any(cam[CONF_CAMERA_ENTITY_ID] == new_camera_id for cam in updated_cameras_config):
                        errors["base"] = "camera_already_configured"
                    else:
                        updated_cameras_config.append({
                            CONF_CAMERA_ENTITY_ID: new_camera_id,
                            CONF_CAMERA_FRIENDLY_NAME: new_camera_friendly_name
                        })
            # Walidacja
            if not updated_cameras_config:
                errors["base"] = "at_least_one_camera_options"
            else:
                friendly_names = [cam[CONF_CAMERA_FRIENDLY_NAME] for cam in updated_cameras_config]
                if len(friendly_names) != len(set(friendly_names)):
                    errors["base"] = "duplicate_camera_friendly_name_options"

            if not errors:
                final_options = {
                    CONF_CAMERAS_CONFIG: updated_cameras_config
                }
                return self.async_create_entry(title="", data=final_options)

        # Budowanie schematu formularza opcji
        options_schema_fields = {}
        # Pola do zarządzania istniejącymi kamerami
        for i, cam_conf in enumerate(self.current_cameras_config):
            options_schema_fields[vol.Optional(f"keep_camera_{i}", default=True)] = bool  # Checkbox do usunięcia
            options_schema_fields[vol.Optional(
                f"camera_{cam_conf[CONF_CAMERA_ENTITY_ID].replace('.', '_')}_friendly_name",
                default=cam_conf[CONF_CAMERA_FRIENDLY_NAME]
            )] = str
        # Pole do dodania nowej kamery, jeśli jest miejsce
        if len(self.current_cameras_config) < MAX_CAMERAS and camera_options_to_add:
            options_schema_fields[vol.Optional("new_camera_entity_id")] = vol.In(camera_options_to_add)
            options_schema_fields[vol.Optional("new_camera_friendly_name")] = str

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options_schema_fields),
            errors=errors,
            description_placeholders={
                "max_cameras": MAX_CAMERAS,
                "current_cameras": len(self.current_cameras_config)
            }
        )
