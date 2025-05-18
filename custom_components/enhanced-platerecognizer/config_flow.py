"""Config flow for Enhanced PlateRecognizer."""
import os
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.camera import DOMAIN as CAMERA_DOMAIN
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import entity_registry

from .const import (
    DOMAIN, CONF_API_KEY, CONF_REGION, CONF_SAVE_FILE_FOLDER,
    CONF_MAX_IMAGES, CONF_CONSECUTIVE_CAPTURES, CONF_CAPTURE_INTERVAL,
    CONF_SAVE_TIMESTAMPED_FILE, CONF_ALWAYS_SAVE_LATEST_FILE,
    CONF_TOLERATE_ONE_MISTAKE, CONF_CAMERAS_CONFIG,
    CONF_CAMERA_ENTITY_ID, CONF_CAMERA_FRIENDLY_NAME, MAX_CAMERAS
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
    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EnhancedPlateRecognizerOptionsFlow(config_entry)

    async def async_step_user(self, user_input=None):
        errors = {}
        registry = entity_registry.async_get(self.hass)
        available_camera_entities = [
            entity.entity_id for entity in registry.entities.values()
            if entity.domain == CAMERA_DOMAIN
        ]
        camera_options = {cam: cam for cam in sorted(available_camera_entities)}

        if not camera_options:
            return self.async_abort(reason="no_cameras")

        if user_input is not None:
            # Walidacja przynajmniej jednej kamery
            cameras_config = []
            has_at_least_one_camera = False
            for i in range(1, MAX_CAMERAS + 1):
                cam_entity_id = user_input.get(f"camera_{i}_entity_id")
                cam_friendly_name = user_input.get(f"camera_{i}_friendly_name")
                if cam_entity_id:
                    has_at_least_one_camera = True
                    if not cam_friendly_name: # Użyj ID kamery jako domyślnej nazwy, jeśli nie podano
                        cam_friendly_name = cam_entity_id.split('.')[-1]
                    cameras_config.append({
                        CONF_CAMERA_ENTITY_ID: cam_entity_id,
                        CONF_CAMERA_FRIENDLY_NAME: cam_friendly_name
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
                    CONF_API_KEY: user_input[CONF_API_KEY],
                    CONF_REGION: user_input[CONF_REGION],
                    CONF_SAVE_FILE_FOLDER: user_input[CONF_SAVE_FILE_FOLDER], # Dodane
                    CONF_MAX_IMAGES: user_input[CONF_MAX_IMAGES],
                    CONF_CONSECUTIVE_CAPTURES: user_input[CONF_CONSECUTIVE_CAPTURES],
                    CONF_CAPTURE_INTERVAL: user_input[CONF_CAPTURE_INTERVAL],
                    CONF_SAVE_TIMESTAMPED_FILE: user_input[CONF_SAVE_TIMESTAMPED_FILE],
                    CONF_ALWAYS_SAVE_LATEST_FILE: user_input[CONF_ALWAYS_SAVE_LATEST_FILE],
                    CONF_TOLERATE_ONE_MISTAKE: user_input[CONF_TOLERATE_ONE_MISTAKE],
                    CONF_CAMERAS_CONFIG: cameras_config
                }
                return self.async_create_entry(
                    title=user_input.get(CONF_NAME, "Enhanced PlateRecognizer"),
                    data=final_data,
                )

        # Definicja schematu dla kroku 'user'
        schema_fields = {
            vol.Required(CONF_NAME, default="Enhanced PlateRecognizer"): str,
            vol.Required(CONF_API_KEY): str,
            vol.Required(CONF_REGION, default="pl"): vol.In(REGIONS),
            vol.Required(CONF_SAVE_FILE_FOLDER, default=os.path.join(self.hass.config.path(), "www", "Tablice")): str, # Dodane
            vol.Optional(CONF_MAX_IMAGES, default=10): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=30)
            ),
            vol.Optional(CONF_CONSECUTIVE_CAPTURES, default=1): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=5)
            ),
            vol.Optional(CONF_CAPTURE_INTERVAL, default=1.2): vol.All(
                vol.Coerce(float), vol.Range(min=1.0, max=2.0)
            ),
            vol.Optional(CONF_SAVE_TIMESTAMPED_FILE, default=True): bool,
            vol.Optional(CONF_ALWAYS_SAVE_LATEST_FILE, default=True): bool,
            vol.Optional(CONF_TOLERATE_ONE_MISTAKE, default=False): bool,
        }

        # Dodaj pola dla kamer dynamicznie
        for i in range(1, MAX_CAMERAS + 1):
            schema_fields[vol.Optional(f"camera_{i}_entity_id")]= vol.In(camera_options)
            schema_fields[vol.Optional(f"camera_{i}_friendly_name")]= str
        
        data_schema = vol.Schema(schema_fields)

        return self.async_show_form(
            step_id="user", data_schema=data_schema, errors=errors
        )


class EnhancedPlateRecognizerOptionsFlow(config_entries.OptionsFlow):
    """Options flow for Enhanced PlateRecognizer."""

    def __init__(self, config_entry: config_entries.ConfigEntry):
        self.config_entry = config_entry
        # Przechowujemy aktualną konfigurację kamer do edycji
        self.current_cameras_config = list(self.config_entry.options.get(CONF_CAMERAS_CONFIG, 
                                          self.config_entry.data.get(CONF_CAMERAS_CONFIG, [])))


    async def async_step_init(self, user_input=None):
        errors = {}
        registry = entity_registry.async_get(self.hass)
        available_camera_entities = [
            entity.entity_id for entity in registry.entities.values()
            if entity.domain == CAMERA_DOMAIN
        ]
        # Kamery już skonfigurowane nie powinny być na liście do dodania
        configured_camera_ids = {cam[CONF_CAMERA_ENTITY_ID] for cam in self.current_cameras_config}
        camera_options_to_add = {
            cam: cam for cam in sorted(available_camera_entities) if cam not in configured_camera_ids
        }


        if user_input is not None:
            updated_cameras_config = []
            # Przetwarzanie istniejących kamer (czy mają być usunięte lub zmieniona nazwa)
            for i, existing_cam_conf in enumerate(self.current_cameras_config):
                keep_camera = user_input.get(f"keep_camera_{i}", True)
                if keep_camera:
                    new_friendly_name = user_input.get(f"camera_{existing_cam_conf[CONF_CAMERA_ENTITY_ID].replace('.', '_')}_friendly_name", 
                                                       existing_cam_conf[CONF_CAMERA_FRIENDLY_NAME])
                    updated_cameras_config.append({
                        CONF_CAMERA_ENTITY_ID: existing_cam_conf[CONF_CAMERA_ENTITY_ID],
                        CONF_CAMERA_FRIENDLY_NAME: new_friendly_name
                    })
            
            # Dodawanie nowej kamery, jeśli wybrano i jest miejsce
            if len(updated_cameras_config) < MAX_CAMERAS:
                new_camera_id = user_input.get("new_camera_entity_id")
                if new_camera_id:
                    new_camera_friendly_name = user_input.get("new_camera_friendly_name")
                    if not new_camera_friendly_name:
                        new_camera_friendly_name = new_camera_id.split('.')[-1]
                    
                    # Sprawdzenie czy ID nowej kamery nie jest już na liście
                    if any(cam[CONF_CAMERA_ENTITY_ID] == new_camera_id for cam in updated_cameras_config):
                        errors["base"] = "camera_already_configured"
                    else:
                        updated_cameras_config.append({
                            CONF_CAMERA_ENTITY_ID: new_camera_id,
                            CONF_CAMERA_FRIENDLY_NAME: new_camera_friendly_name
                        })

            # Walidacja (przynajmniej jedna kamera, unikalne nazwy)
            if not updated_cameras_config:
                errors["base"] = "at_least_one_camera_options"
            else:
                friendly_names = [cam[CONF_CAMERA_FRIENDLY_NAME] for cam in updated_cameras_config]
                if len(friendly_names) != len(set(friendly_names)):
                    errors["base"] = "duplicate_camera_friendly_name_options"

            if not errors:
                # Aktualizacja globalnych opcji
                updated_options_data = {
                    CONF_REGION: user_input.get(CONF_REGION),
                    CONF_SAVE_FILE_FOLDER: user_input.get(CONF_SAVE_FILE_FOLDER),
                    CONF_MAX_IMAGES: user_input.get(CONF_MAX_IMAGES),
                    CONF_CONSECUTIVE_CAPTURES: user_input.get(CONF_CONSECUTIVE_CAPTURES),
                    CONF_CAPTURE_INTERVAL: user_input.get(CONF_CAPTURE_INTERVAL),
                    CONF_SAVE_TIMESTAMPED_FILE: user_input.get(CONF_SAVE_TIMESTAMPED_FILE),
                    CONF_ALWAYS_SAVE_LATEST_FILE: user_input.get(CONF_ALWAYS_SAVE_LATEST_FILE),
                    CONF_TOLERATE_ONE_MISTAKE: user_input.get(CONF_TOLERATE_ONE_MISTAKE),
                    CONF_CAMERAS_CONFIG: updated_cameras_config
                }
                # Usuń klucze, które są None (nie zostały zmienione w formularzu opcji dla ustawień globalnych)
                # lub zachowaj stare wartości jeśli nie podano nowych
                final_options = {}
                for key, value in updated_options_data.items():
                    if value is not None or key == CONF_CAMERAS_CONFIG: # Zawsze aktualizuj listę kamer
                        final_options[key] = value
                    else: # Zachowaj starą wartość opcji globalnej jeśli nie podano nowej
                        final_options[key] = self.config_entry.options.get(key, self.config_entry.data.get(key))


                return self.async_create_entry(title="", data=final_options)

        # Budowanie schematu dla OptionsFlow
        options_schema_fields = {}
        # Pola dla globalnych ustawień (jak w _get_options_schema poprzednio, ale bierzemy pod uwagę data i options)
        current_options = self.config_entry.options
        current_data = self.config_entry.data
        default_save_folder_path = os.path.join(self.hass.config.path(), "www", "Tablice")

        options_schema_fields[vol.Optional(
            CONF_REGION, 
            default=current_options.get(CONF_REGION, current_data.get(CONF_REGION, "pl"))
        )] = vol.In(REGIONS)

        options_schema_fields[vol.Optional(
            CONF_SAVE_FILE_FOLDER, 
            default=current_options.get(CONF_SAVE_FILE_FOLDER, current_data.get(CONF_SAVE_FILE_FOLDER, default_save_folder_path))
        )] = str

        options_schema_fields[vol.Optional(
            CONF_MAX_IMAGES, 
            default=current_options.get(CONF_MAX_IMAGES, current_data.get(CONF_MAX_IMAGES, 10))
        )] = vol.All(vol.Coerce(int), vol.Range(min=1, max=30))

        options_schema_fields[vol.Optional(
            CONF_SAVE_TIMESTAMPED_FILE, 
            default=current_options.get(CONF_SAVE_TIMESTAMPED_FILE, current_data.get(CONF_SAVE_TIMESTAMPED_FILE, True))
        )] = bool

        options_schema_fields[vol.Optional(
            CONF_ALWAYS_SAVE_LATEST_FILE, 
            default=current_options.get(CONF_ALWAYS_SAVE_LATEST_FILE, current_data.get(CONF_ALWAYS_SAVE_LATEST_FILE, True))
        )] = bool

        options_schema_fields[vol.Optional(
            CONF_CONSECUTIVE_CAPTURES, 
            default=current_options.get(CONF_CONSECUTIVE_CAPTURES, current_data.get(CONF_CONSECUTIVE_CAPTURES, 1))
        )] = vol.All(vol.Coerce(int), vol.Range(min=1, max=5))

        options_schema_fields[vol.Optional(
            CONF_CAPTURE_INTERVAL, 
            default=current_options.get(CONF_CAPTURE_INTERVAL, current_data.get(CONF_CAPTURE_INTERVAL, 1.2))
        )] = vol.All(vol.Coerce(float), vol.Range(min=1.0, max=2.0))

        options_schema_fields[vol.Optional(
            CONF_TOLERATE_ONE_MISTAKE, 
            default=current_options.get(CONF_TOLERATE_ONE_MISTAKE, current_data.get(CONF_TOLERATE_ONE_MISTAKE, False))
        )] = bool

        # Pola do zarządzania istniejącymi kamerami
        for i, cam_conf in enumerate(self.current_cameras_config):
            options_schema_fields[vol.Optional(f"keep_camera_{i}", default=True)] = bool # Checkbox do usunięcia
            options_schema_fields[vol.Optional(f"camera_{cam_conf[CONF_CAMERA_ENTITY_ID].replace('.', '_')}_friendly_name", default=cam_conf[CONF_CAMERA_FRIENDLY_NAME])] = str
        
        # Pole do dodania nowej kamery, jeśli jest miejsce
        if len(self.current_cameras_config) < MAX_CAMERAS and camera_options_to_add:
            options_schema_fields[vol.Optional("new_camera_entity_id")] = vol.In(camera_options_to_add)
            options_schema_fields[vol.Optional("new_camera_friendly_name")] = str
        
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(options_schema_fields),
            errors=errors,
            description_placeholders={"max_cameras": MAX_CAMERAS, "current_cameras": len(self.current_cameras_config)}
        )
