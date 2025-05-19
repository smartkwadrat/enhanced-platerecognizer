"""Enhanced PlateRecognizer - główny plik integracji."""

import asyncio
import logging
import os

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.const import ATTR_ENTITY_ID
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    DOMAIN,
    SERVICE_ADD_PLATE,
    SERVICE_REMOVE_PLATE,
    SERVICE_CLEAN_IMAGES,
    CONF_CAMERAS_CONFIG,
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
    """Konfiguracja integracji."""
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN]["global_save_folder"] = os.path.join(hass.config.path(), "www", "Tablice")
    hass.data[DOMAIN]["global_max_images"] = 10

    # Inicjalizacja PlateManager
    config_dir = hass.config.config_dir
    plate_manager = PlateManager(hass, config_dir)
    await plate_manager.async_initial_load()
    hass.data[DOMAIN]["plate_manager"] = plate_manager

    if "global_recognition_manager" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["global_recognition_manager"] = GlobalRecognitionManager(hass)

    # Tworzenie globalnych encji zarządzania
    if not hass.states.get("input_text.add_new_plate"):
        await _create_plate_management_entities(hass)
        await _update_remove_plate_options_async(hass, plate_manager)

    # --- Rejestracja usług (tylko raz na integrację) ---
    if not hass.services.has_service(DOMAIN, "scan"):
        async def scan_service_handler(service):
            if hass.data[DOMAIN].get("global_scan_in_progress", False):
                _LOGGER.warning("Inna operacja skanowania jest już w toku, pomijam żądanie.")
                return
            
            hass.data[DOMAIN]["global_scan_in_progress"] = True
            try:
                entity_ids_filter = service.data.get(ATTR_ENTITY_ID)
                entities_to_scan = []
                
                for entity_component in hass.data.get("image_processing", {}).values():
                    if hasattr(entity_component, "entities"):
                        for entity in entity_component.entities:
                            if getattr(entity.platform, "platform_name", None) == DOMAIN:
                                if not entity_ids_filter or entity.entity_id in entity_ids_filter:
                                    entities_to_scan.append(entity)
                
                if entities_to_scan:
                    _LOGGER.info(f"Scan service called for entities: {[e.entity_id for e in entities_to_scan]}")
                    await asyncio.gather(*[entity.async_scan_and_process() for entity in entities_to_scan])
                else:
                    _LOGGER.info("Scan service called, but no matching entities found to scan.")
            
            except Exception as e:
                _LOGGER.error(f"Błąd w scan_service_handler: {e}", exc_info=True)
            
            finally:
                hass.data[DOMAIN]["global_scan_in_progress"] = False
        
        hass.services.async_register(DOMAIN, "scan", scan_service_handler, schema=SERVICE_SCAN_SCHEMA)
        _LOGGER.info("Service 'scan' registered.")

    if not hass.services.has_service(DOMAIN, SERVICE_ADD_PLATE):
        async def add_plate_service_handler(service):
            try:
                plate = service.data.get("plate")
                owner = service.data.get("owner", "")
                if await plate_manager.async_add_plate(plate, owner):
                    await _update_remove_plate_options_async(hass, plate_manager)
                    _LOGGER.info(f"Dodano tablicę przez usługę: {plate} ({owner})")
                else:
                    _LOGGER.warning(f"Nieprawidłowy format tablicy przez usługę: {plate}")
            except Exception as e:
                _LOGGER.error(f"Błąd w add_plate_service_handler: {e}", exc_info=True)
        hass.services.async_register(DOMAIN, SERVICE_ADD_PLATE, add_plate_service_handler, schema=SERVICE_ADD_PLATE_SCHEMA)
        _LOGGER.info(f"Service '{SERVICE_ADD_PLATE}' registered.")

    if not hass.services.has_service(DOMAIN, SERVICE_REMOVE_PLATE):
        async def remove_plate_service_handler(service):
            try:
                plate = service.data.get("plate")
                if await plate_manager.async_remove_plate(plate):
                    await _update_remove_plate_options_async(hass, plate_manager)
                    _LOGGER.info(f"Usunięto tablicę przez usługę: {plate}")
                else:
                    _LOGGER.warning(f"Nie znaleziono tablicy przez usługę: {plate}")
            except Exception as e:
                _LOGGER.error(f"Błąd w remove_plate_service_handler: {e}", exc_info=True)
        hass.services.async_register(DOMAIN, SERVICE_REMOVE_PLATE, remove_plate_service_handler, schema=SERVICE_REMOVE_PLATE_SCHEMA)
        _LOGGER.info(f"Service '{SERVICE_REMOVE_PLATE}' registered.")

    if not hass.services.has_service(DOMAIN, SERVICE_CLEAN_IMAGES):
        async def clean_images_service_handler(service):
            try:
                folder = service.data.get("folder")
                max_images_from_service = service.data.get("max_images")
                if not folder:
                    folder = hass.data[DOMAIN].get("global_save_folder")
                    _LOGGER.info(f"Folder nie został podany, używam globalnego: {folder}")
                final_max_images = max_images_from_service
                if final_max_images is None:
                    final_max_images = hass.data[DOMAIN].get("global_max_images")
                    _LOGGER.info(f"Max_images nie zostało podane, używam globalnego: {final_max_images}")
                if folder and final_max_images is not None:
                    _LOGGER.info(f"Usługa clean_images wywołana dla folderu: {folder}, max_images: {final_max_images}")
                    await async_clean_old_images(hass, folder, final_max_images)
                else:
                    _LOGGER.warning(f"Nieprawidłowy folder lub max_images do czyszczenia zdjęć: folder='{folder}', max_images='{final_max_images}'")
            except Exception as e:
                _LOGGER.error(f"Błąd w clean_images_service_handler: {e}", exc_info=True)
        hass.services.async_register(DOMAIN, SERVICE_CLEAN_IMAGES, clean_images_service_handler, schema=SERVICE_CLEAN_IMAGES_SCHEMA)
        _LOGGER.info(f"Service '{SERVICE_CLEAN_IMAGES}' registered.")

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Konfiguracja z config entry."""
    hass.data.setdefault(DOMAIN, {})
    plate_manager = hass.data[DOMAIN]["plate_manager"]
    if not plate_manager:
        _LOGGER.error("PlateManager not initialized in async_setup. Aborting entry setup.")
        return False

    if "global_recognition_manager" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["global_recognition_manager"] = GlobalRecognitionManager(hass)

    # Przechowuj tylko kamery z config_entry (bez ustawień globalnych)
    active_config = {**entry.data, **entry.options}
    hass.data[DOMAIN][entry.entry_id] = active_config

    if "first_entry_id" not in hass.data[DOMAIN]:
        hass.data[DOMAIN]["first_entry_id"] = entry.entry_id

    _LOGGER.info(f"Setting up Enhanced PlateRecognizer entry: {entry.title} ({entry.entry_id})")
    _LOGGER.debug(f"Active config for entry {entry.entry_id}: {active_config}")

    # Tworzenie globalnych encji zarządzania (jeśli nie istnieją)
    if not hass.states.get("input_text.add_new_plate"):
        await _create_plate_management_entities(hass)
        await _update_remove_plate_options_async(hass, plate_manager)

    # Listenery do obsługi input_text/input_select
    if not hass.data[DOMAIN].get("add_plate_listener_registered", False):
        @callback
        def handle_add_plate_input(event):
            new_state = event.data.get("new_state")
            if new_state and new_state.state:
                plate = new_state.state.strip().upper()
                if plate_manager.is_valid_plate(plate):
                    owner = ""
                    owner_entity = hass.states.get("input_text.add_plate_owner")
                    if owner_entity:
                        owner = owner_entity.state.strip()
                    async def add_and_update():
                        if await plate_manager.async_add_plate(plate, owner):
                            _LOGGER.info(f"Dodano tablicę przez input: {plate} ({owner})")
                            hass.states.async_set("input_text.add_new_plate", "")
                            hass.states.async_set("input_text.add_plate_owner", "")
                            await _update_remove_plate_options_async(hass, plate_manager)
                        else:
                            _LOGGER.warning(f"Nie udało się dodać tablicy przez input: {plate}")
                            hass.states.async_set("input_text.add_new_plate", "")
                    hass.async_create_task(add_and_update())
                else:
                    _LOGGER.warning(f"Próba dodania nieprawidłowej tablicy przez input: {plate}")
                    hass.states.async_set("input_text.add_new_plate", "")
        async_track_state_change_event(hass, "input_text.add_new_plate", handle_add_plate_input)
        hass.data[DOMAIN]["add_plate_listener_registered"] = True
        _LOGGER.info("Listener for 'input_text.add_new_plate' registered.")

    if not hass.data[DOMAIN].get("remove_plate_listener_registered", False):
        @callback
        def handle_remove_plate_select(event):
            new_state = event.data.get("new_state")
            if (new_state and new_state.state and
                new_state.state != "Wybierz tablicę do usunięcia" and
                new_state.state != "Brak tablic"):
                plate_to_remove = new_state.state.split(' - ')[0].strip().upper()
                async def remove_and_update():
                    if await plate_manager.async_remove_plate(plate_to_remove):
                        _LOGGER.info(f"Usunięto tablicę przez input_select: {plate_to_remove}")
                        hass.services.async_call(
                            "input_select", "select_option",
                            {"entity_id": "input_select.remove_plate", "option": "Wybierz tablicę do usunięcia"},
                            blocking=False
                        )
                        await _update_remove_plate_options_async(hass, plate_manager)
                    else:
                        _LOGGER.warning(f"Nie udało się usunąć tablicy przez input_select: {plate_to_remove}")
                hass.async_create_task(remove_and_update())
        async_track_state_change_event(hass, "input_select.remove_plate", handle_remove_plate_select)
        hass.data[DOMAIN]["remove_plate_listener_registered"] = True
        _LOGGER.info("Listener for 'input_select.remove_plate' registered.")

    # Przekazanie konfiguracji do platform
    platforms = ["button"]
    await hass.config_entries.async_forward_entry_setups(entry, platforms)
    _LOGGER.debug(f"Forwarding setup for platforms: {', '.join(platforms)} for entry {entry.entry_id}")

    # Listener do reloadu po zmianie opcji
    entry.async_on_unload(entry.add_update_listener(update_listener))
    _LOGGER.info(f"Update listener added for entry {entry.entry_id}")

    _LOGGER.info(f"Enhanced PlateRecognizer entry {entry.title} ({entry.entry_id}) setup complete.")
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Wyładowanie wpisu konfiguracyjnego."""
    platforms_to_unload = ["button"]
    unload_ok = all(
        await asyncio.gather(
            *[hass.config_entries.async_forward_entry_unload(entry, platform) for platform in platforms_to_unload]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        # Jeśli to ostatni wpis, usuń globalne menedżery
        active_entries = [
            e_id for e_id, e_data in hass.data[DOMAIN].items()
            if isinstance(e_data, dict) and CONF_CAMERAS_CONFIG in e_data
        ]
        if not active_entries:
            hass.data[DOMAIN].pop("plate_manager", None)
            hass.data[DOMAIN].pop("global_recognition_manager", None)
            _LOGGER.info("Removed global managers for Enhanced PlateRecognizer.")
            await _remove_plate_management_entities(hass)
    return unload_ok

async def _create_plate_management_entities(hass):
    """Tworzy input_text, input_select i sensory do zarządzania."""
    try:
        if not hass.states.get("input_text.add_new_plate"):
            hass.states.async_set(
                "input_text.add_new_plate", "", {
                    "friendly_name": "Dodaj nowe tablice rejestracyjne",
                    "pattern": "^[a-zA-Z0-9]{2,10}$",
                }
            )
        if not hass.states.get("input_text.add_plate_owner"):
            hass.states.async_set(
                "input_text.add_plate_owner", "", {
                    "friendly_name": "Podaj właściciela tablic",
                }
            )
        if not hass.states.get("input_select.remove_plate"):
            hass.states.async_set(
                "input_select.remove_plate", "Wybierz tablicę do usunięcia", {
                    "friendly_name": "Usuń tablice",
                    "options": ["Wybierz tablicę do usunięcia", "Brak tablic"],
                }
            )
        if not hass.states.get("sensor.formatted_car_plates"):
            hass.states.async_set(
                "sensor.formatted_car_plates", "Znane tablice rejestracyjne", {
                    "friendly_name": "Znane tablice rejestracyjne",
                    "formatted_list": "Brak zapisanych tablic",
                }
            )
        if not hass.states.get("sensor.recognized_car"):
            hass.states.async_set(
                "sensor.recognized_car", "Brak rozpoznanych tablic", {
                    "friendly_name": "Rozpoznany samochód (Wszystkie kamery)",
                }
            )
        if not hass.states.get("sensor.last_recognized_car"):
            hass.states.async_set(
                "sensor.last_recognized_car", "Brak", {
                    "friendly_name": "Ostatnio rozpoznane tablice (Wszystkie kamery)",
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
                {"entity_id": "input_select.remove_plate", "options": options},
                blocking=True
            )
        except Exception as e:
            _LOGGER.error(f"Błąd aktualizacji input_select.remove_plate: {e}")
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
    """Usuwa stare zdjęcia, zostawiając tylko max_images najnowszych."""
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

class GlobalRecognitionManager:
    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._last_recognized_by_camera = {}
        self.camera_specific_sensor_prefix = "sensor.recognized_car_"

    def report_recognition(self, camera_friendly_name: str, plates_str: str, recognized_msg: str, is_known: bool):
        sane_camera_friendly_name = camera_friendly_name.lower().replace(" ", "_")
        self._last_recognized_by_camera[sane_camera_friendly_name] = (plates_str, recognized_msg, is_known)
        self._update_global_sensors()

    def _update_global_sensors(self):
        all_last_plates_parts = []
        all_recognized_msgs_parts = []
        for cam_name_slug, (plates_str, rec_msg, is_known) in self._last_recognized_by_camera.items():
            cam_display_name = cam_name_slug.replace("_", " ").title()
            if plates_str and plates_str != "Brak":
                all_last_plates_parts.append(f"{cam_display_name}: {plates_str}")
            if is_known and rec_msg:
                all_recognized_msgs_parts.append(f"{cam_display_name}: {rec_msg.replace('Rozpoznane tablice ', '').replace(' znajdują się na liście', '')}")
        final_last_plates = "; ".join(all_last_plates_parts) if all_last_plates_parts else "Brak"
        final_recognized_msg = "; ".join(all_recognized_msgs_parts) if all_recognized_msgs_parts else "Brak rozpoznanych tablic"
        self.hass.states.async_set(
            "sensor.last_recognized_car", final_last_plates,
            {"friendly_name": "Ostatnio rozpoznane tablice (Wszystkie kamery)"}
        )
        self.hass.states.async_set(
            "sensor.recognized_car", final_recognized_msg,
            {"friendly_name": "Rozpoznany samochód (Wszystkie kamery)"}
        )
        self.hass.async_create_task(self._clear_global_recognized_car_sensor(20))

    async def _clear_global_recognized_car_sensor(self, wait_time: int):
        await asyncio.sleep(wait_time)
        current_state = self.hass.states.get("sensor.recognized_car")
        if current_state and current_state.state != "Brak rozpoznanych tablic":
            self.hass.states.async_set(
                "sensor.recognized_car", "Brak rozpoznanych tablic",
                {"friendly_name": "Rozpoznany samochód (Wszystkie kamery)"}
            )

    def remove_camera_data(self, camera_friendly_name: str):
        sane_camera_friendly_name = camera_friendly_name.lower().replace(" ", "_")
        if sane_camera_friendly_name in self._last_recognized_by_camera:
            del self._last_recognized_by_camera[sane_camera_friendly_name]
            self._update_global_sensors()

    def get_camera_specific_sensor_id(self, camera_friendly_name: str) -> str:
        sane_camera_name = camera_friendly_name.lower().replace(" ", "_").replace(".", "_")
        return f"{self.camera_specific_sensor_prefix}{sane_camera_name}"

async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Obsługa aktualizacji opcji."""
    _LOGGER.info(f"Enhanced PlateRecognizer ({entry.title}) options updated, reloading integration.")
    await hass.config_entries.async_reload(entry.entry_id)

async def _remove_plate_management_entities(hass):
    """Usuwa encje zarządzania."""
    to_remove = [
        "input_text.add_new_plate",
        "input_text.add_plate_owner",
        "input_select.remove_plate",
        "sensor.formatted_car_plates",
        "sensor.recognized_car",
        "sensor.last_recognized_car",
    ]
    for entity_id in to_remove:
        try:
            hass.states.async_remove(entity_id)
        except Exception:
            pass
