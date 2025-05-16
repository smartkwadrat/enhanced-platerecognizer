"""Enhanced PlateRecognizer - główny plik integracji."""

import asyncio
import logging
import os
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import ATTR_ENTITY_ID
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    SERVICE_ADD_PLATE,
    SERVICE_REMOVE_PLATE,
    SERVICE_CLEAN_IMAGES,
    CONF_SAVE_FILE_FOLDER,
    CONF_MAX_IMAGES,
)
from .platemanager import PlateManager

_LOGGER = logging.getLogger(__name__)

# Schematy usług
SERVICE_SCAN_SCHEMA = vol.Schema({
    vol.Optional(ATTR_ENTITY_ID): cv.entity_ids,
})

SERVICE_ADD_PLATE_SCHEMA = vol.Schema({
    vol.Required("plate"): cv.string,
    vol.Optional("owner", default=""): cv.string,
})

SERVICE_REMOVE_PLATE_SCHEMA = vol.Schema({
    vol.Required("plate"): cv.string,
})

SERVICE_CLEAN_IMAGES_SCHEMA = vol.Schema({
    vol.Optional("folder"): cv.string,
    vol.Optional("max_images"): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
})

async def async_setup(hass: HomeAssistant, config) -> bool:
    """Konfiguracja z configuration.yaml (nieużywana, tylko config entries)."""
    hass.data.setdefault(DOMAIN, {})

    # Inicjalizacja PlateManager
    config_dir = hass.config.config_dir
    plate_manager = PlateManager(hass, config_dir)
    hass.data[DOMAIN]["plate_manager"] = plate_manager

    await _create_plate_management_entities(hass)
    await _update_remove_plate_options_async(hass, plate_manager)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Konfiguracja z config entry."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = entry

    # Inicjalizacja PlateManager jeśli jeszcze nie istnieje
    if "plate_manager" not in hass.data[DOMAIN]:
        config_dir = hass.config.config_dir
        plate_manager = PlateManager(hass, config_dir)
        hass.data[DOMAIN]["plate_manager"] = plate_manager
    else:
        plate_manager = hass.data[DOMAIN]["plate_manager"]

    # Rejestracja usług tylko raz
    if not hass.services.has_service(DOMAIN, "scan"):
        # Usługa skanowania
        async def scan_service_handler(service):
            try:
                entity_ids = service.data.get(ATTR_ENTITY_ID)
                entities = []
                
                for entity_component in hass.data.get("image_processing", {}).values():
                    if hasattr(entity_component, "entities"):
                        for entity in entity_component.entities:
                            if getattr(entity.platform, "platform_name", None) == DOMAIN:
                                entities.append(entity)
                
                tasks = []
                for entity in entities:
                    if not entity_ids or entity.entity_id in entity_ids:
                        tasks.append(entity.async_scan_and_process())
                
                if tasks:
                    await asyncio.gather(*tasks)
            except Exception as e:
                _LOGGER.error(f"Błąd w scan_service_handler: {e}")

        hass.services.async_register(
            DOMAIN, "scan", scan_service_handler, schema=SERVICE_SCAN_SCHEMA
        )

        # Usługa dodawania tablicy
        async def add_plate_service_handler(service):
            try:
                plate = service.data.get("plate")
                owner = service.data.get("owner", "")
                
                if await plate_manager.async_add_plate(plate, owner):
                    await _update_remove_plate_options_async(hass, plate_manager)
                    _LOGGER.info(f"Dodano tablicę: {plate} ({owner})")
                else:
                    _LOGGER.warning(f"Nieprawidłowy format tablicy: {plate}")
            except Exception as e:
                _LOGGER.error(f"Błąd w add_plate_service_handler: {e}")

        hass.services.async_register(
            DOMAIN, SERVICE_ADD_PLATE, add_plate_service_handler, schema=SERVICE_ADD_PLATE_SCHEMA
        )

        # Usługa usuwania tablicy
        async def remove_plate_service_handler(service):
            try:
                plate = service.data.get("plate")
                if await plate_manager.async_remove_plate(plate):
                    await _update_remove_plate_options_async(hass, plate_manager)
                    _LOGGER.info(f"Usunięto tablicę: {plate}")
                else:
                    _LOGGER.warning(f"Nie znaleziono tablicy: {plate}")
            except Exception as e:
                _LOGGER.error(f"Błąd w remove_plate_service_handler: {e}")

        hass.services.async_register(
            DOMAIN, SERVICE_REMOVE_PLATE, remove_plate_service_handler, schema=SERVICE_REMOVE_PLATE_SCHEMA
        )

        # Usługa czyszczenia zdjęć
        async def clean_images_service_handler(service):
            try:
                folder = service.data.get("folder")
                max_images = service.data.get("max_images")
                
                # Jeśli nie podano folderu, użyj domyślnego z konfiguracji
                if not folder:
                    for entry_id, entry_data in hass.data[DOMAIN].items():
                        if isinstance(entry_data, ConfigEntry):
                            folder = entry_data.data.get(CONF_SAVE_FILE_FOLDER) or entry_data.options.get(CONF_SAVE_FILE_FOLDER)
                            if folder:
                                break
                
                # Jeśli nie podano max_images, użyj domyślnego z konfiguracji
                if max_images is None:
                    for entry_id, entry_data in hass.data[DOMAIN].items():
                        if isinstance(entry_data, ConfigEntry):
                            max_images = entry_data.data.get(CONF_MAX_IMAGES) or entry_data.options.get(CONF_MAX_IMAGES, 10)
                            break
                
                if folder:
                    await async_clean_old_images(hass, folder, max_images)
                    _LOGGER.info(f"Usunięto stare zdjęcia w {folder}, pozostawiono {max_images} najnowszych")
                else:
                    _LOGGER.warning(f"Nieprawidłowy folder do czyszczenia zdjęć: {folder}")
            except Exception as e:
                _LOGGER.error(f"Błąd w clean_images_service_handler: {e}")

        hass.services.async_register(
            DOMAIN, SERVICE_CLEAN_IMAGES, clean_images_service_handler, schema=SERVICE_CLEAN_IMAGES_SCHEMA
        )

    # Tworzenie encji input i sensorów do zarządzania tablicami (raz)
    await _create_plate_management_entities(hass)
    await _update_remove_plate_options_async(hass, plate_manager)

    # Listener: dodawanie tablicy przez input_text.add_new_plate
    @callback
    def handle_add_plate_input(entity_id, old_state, new_state):
        if new_state and new_state.state:
            plate = new_state.state.strip()
            if plate_manager.is_valid_plate(plate):
                owner = ""
                owner_entity = hass.states.get("input_text.add_plate_owner")
                if owner_entity:
                    owner = owner_entity.state
                
                hass.async_create_task(plate_manager.async_add_plate(plate, owner))
                
                # Reset input fields
                hass.states.async_set("input_text.add_new_plate", "")
                hass.states.async_set("input_text.add_plate_owner", "")
                
                hass.async_create_task(_update_remove_plate_options_async(hass, plate_manager))

    hass.helpers.event.async_track_state_change(
        "input_text.add_new_plate", handle_add_plate_input
    )

    # Listener: usuwanie tablicy przez input_select.remove_plate
    @callback
    def handle_remove_plate_select(entity_id, old_state, new_state):
        if (new_state and new_state.state and
                new_state.state != "Wybierz tablicę do usunięcia" and
                new_state.state != "Brak tablic"):
            plate = new_state.state.split(' - ')[0].strip()
            hass.async_create_task(plate_manager.async_remove_plate(plate))
            
            hass.services.async_call(
                "input_select", "select_option",
                {
                    "entity_id": "input_select.remove_plate",
                    "option": "Wybierz tablicę do usunięcia"
                }
            )
            
            hass.async_create_task(_update_remove_plate_options_async(hass, plate_manager))

    hass.helpers.event.async_track_state_change(
        "input_select.remove_plate", handle_remove_plate_select
    )

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, "image_processing")
    )

    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Wyładowanie wpisu konfiguracyjnego."""
    unload_ok = await hass.config_entries.async_forward_entry_unload(entry, "image_processing")
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok

async def _create_plate_management_entities(hass):
    """Tworzy input_text, input_select i sensory do zarządzania tablicami."""
    try:
        # input_text.add_new_plate
        if not hass.states.get("input_text.add_new_plate"):
            hass.states.async_set(
                "input_text.add_new_plate", "", {
                    "friendly_name": "Dodaj nowe tablice rejestracyjne",
                    "pattern": "^[a-zA-Z0-9]{2,10}$"
                }
            )

        # input_text.add_plate_owner
        if not hass.states.get("input_text.add_plate_owner"):
            hass.states.async_set(
                "input_text.add_plate_owner", "", {
                    "friendly_name": "Podaj właściciela tablic"
                }
            )

        # input_select.remove_plate
        if not hass.states.get("input_select.remove_plate"):
            hass.states.async_set(
                "input_select.remove_plate", "Wybierz tablicę do usunięcia", {
                    "friendly_name": "Usuń tablice",
                    "options": ["Wybierz tablicę do usunięcia", "Brak tablic"]
                }
            )

        # sensor.formatted_car_plates
        if not hass.states.get("sensor.formatted_car_plates"):
            hass.states.async_set(
                "sensor.formatted_car_plates", "Znane tablice rejestracyjne", {
                    "friendly_name": "Znane tablice rejestracyjne",
                    "formatted_list": "Brak zapisanych tablic"
                }
            )

        # sensor.recognized_car
        if not hass.states.get("sensor.recognized_car"):
            hass.states.async_set(
                "sensor.recognized_car", "Brak rozpoznanych tablic", {
                    "friendly_name": "Rozpoznany samochód"
                }
            )

        # sensor.last_recognized_car
        if not hass.states.get("sensor.last_recognized_car"):
            hass.states.async_set(
                "sensor.last_recognized_car", "Brak", {
                    "friendly_name": "Ostatnio rozpoznane tablice"
                }
            )
    except Exception as e:
        _LOGGER.error(f"Błąd podczas tworzenia encji: {e}")

async def _update_remove_plate_options_async(hass, plate_manager):
    """Aktualizuje opcje w input_select.remove_plate oraz sensor.formatted_car_plates."""
    try:
        plates = await plate_manager.async_get_formatted_plates()
        options = ["Wybierz tablicę do usunięcia"] + plates
        if not plates:
            options.append("Brak tablic")

        try:
            await hass.services.async_call(
                "input_select", "set_options",
                {
                    "entity_id": "input_select.remove_plate",
                    "options": options
                },
                blocking=True
            )
        except Exception as e:
            _LOGGER.error(f"Błąd aktualizacji input_select.remove_plate: {e}")

        # sensor.formatted_car_plates
        formatted_list = ""
        for i, plate in enumerate(plates, 1):
            formatted_list += f"{i}. {plate}\n"
        if not formatted_list:
            formatted_list = "Brak zapisanych tablic"
        
        hass.states.async_set(
            "sensor.formatted_car_plates",
            "Znane tablice rejestracyjne",
            {"formatted_list": formatted_list}
        )
    except Exception as e:
        _LOGGER.error(f"Błąd w _update_remove_plate_options_async: {e}")

async def async_clean_old_images(hass, folder, max_images):
    """Usuwa stare zdjęcia asynchronicznie, zostawiając tylko max_images najnowszych."""
    
    def clean_files():
        try:
            if not os.path.isdir(folder):
                _LOGGER.warning(f"Folder {folder} nie istnieje")
                return False
                
            files = sorted(
                (os.path.join(folder, f) for f in os.listdir(folder) if os.path.isfile(os.path.join(folder, f))),
                key=os.path.getmtime,
                reverse=True
            )
            
            for f in files[max_images:]:
                try:
                    os.remove(f)
                except (OSError, IOError) as e:
                    _LOGGER.error(f"Błąd podczas usuwania pliku {f}: {e}")
            
            return True
        except Exception as e:
            _LOGGER.error(f"Błąd podczas czyszczenia zdjęć: {e}")
            return False
    
    return await hass.async_add_executor_job(clean_files)
