"""Enhanced PlateRecognizer image_processing platform."""

import asyncio
import datetime
import logging
import os
import aiohttp

from homeassistant.components.image_processing import ImageProcessingEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME, CONF_SOURCE
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_REGION,
    CONF_CONSECUTIVE_CAPTURES,
    CONF_CAPTURE_INTERVAL,
    CONF_SAVE_TIMESTAMPED_FILE,
    CONF_ALWAYS_SAVE_LATEST_FILE,
    CONF_MAX_IMAGES,
    CONF_TOLERATE_ONE_MISTAKE,
    SERVICE_CLEAN_IMAGES,
    CONF_CAMERAS_CONFIG,
    CONF_CAMERA_ENTITY_ID,
    CONF_CAMERA_FRIENDLY_NAME 
)

_LOGGER = logging.getLogger(__name__)

PLATE_READER_URL = "https://api.platerecognizer.com/v1/plate-reader/"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Enhanced PlateRecognizer from a config entry for multiple cameras."""
    
    # Pobierz konfigurację z hass.data, która zawiera już scalone dane i opcje
    entry_config = hass.data[DOMAIN][entry.entry_id]
    
    plate_manager = hass.data[DOMAIN]["plate_manager"]
    global_manager = hass.data[DOMAIN].get("global_recognition_manager")

    if not global_manager:
        _LOGGER.error("GlobalRecognitionManager not found in hass.data. Cannot setup image processing entities.")
        return

    save_file_folder_base = entry_config.get(CONF_SAVE_FILE_FOLDER, os.path.join(hass.config.path(), "www", "Tablice"))

    # Sprawdzamy czy katalog istnieje - asynchronicznie
    async def ensure_directory_exists(directory):
        def create_dir():
            try:
                os.makedirs(directory, exist_ok=True)
                _LOGGER.info("Created directory: %s", directory)
                return True
            except OSError as err:
                _LOGGER.warning("Failed to create directory %s: %s", directory, err)
                return False
        
        return await hass.async_add_executor_job(create_dir)

    await ensure_directory_exists(save_file_folder)

    entities_to_add = []
    cameras_config = entry_config.get(CONF_CAMERAS_CONFIG, [])

    for camera_conf in cameras_config:
        camera_entity_id = camera_conf[CONF_CAMERA_ENTITY_ID]
        # Nazwa przyjazna dla tej konkretnej instancji kamery, używana też do ID sensora
        camera_friendly_name = camera_conf[CONF_CAMERA_FRIENDLY_NAME] 
        
        # Użyj globalnych ustawień z entry_config
        api_key = entry_config[CONF_API_KEY]
        region = entry_config.get(CONF_REGION)
        save_timestamped_file = entry_config.get(CONF_SAVE_TIMESTAMPED_FILE, True)
        always_save_latest_file = entry_config.get(CONF_ALWAYS_SAVE_LATEST_FILE, True)
        consecutive_captures = entry_config.get(CONF_CONSECUTIVE_CAPTURES, 1)
        capture_interval = entry_config.get(CONF_CAPTURE_INTERVAL, 1.2)
        max_images = entry_config.get(CONF_MAX_IMAGES, 10)
        tolerate_one_mistake = entry_config.get(CONF_TOLERATE_ONE_MISTAKE, False)

        entity = EnhancedPlateRecognizer(
            hass,
            camera_entity_id,
            camera_friendly_name, # To będzie używane jako część `name` encji i do ID sensora
            api_key,
            region,
            save_file_folder_base, # Wspólny folder
            save_timestamped_file,
            always_save_latest_file,
            consecutive_captures,
            capture_interval,
            max_images,
            plate_manager,
            tolerate_one_mistake,
            global_manager # Przekaż global_manager
        )
        entities_to_add.append(entity)

        # Utwórz dedykowany sensor dla tej kamery (stan początkowy)
        # Jego ID będzie np. sensor.recognized_car_kamera_brama
        sensor_id = global_manager.get_camera_specific_sensor_id(camera_friendly_name)
        hass.states.async_set(
            sensor_id, "Brak danych",
            {"friendly_name": f"Rozpoznany samochód ({camera_friendly_name})"}
        )


    if entities_to_add:
        async_add_entities(entities_to_add)

# image_processing.py

import asyncio
import datetime
import logging
import os
import aiohttp

from homeassistant.components.image_processing import (
    ImageProcessingEntity,
    PLATFORM_SCHEMA as IMAGE_PROCESSING_PLATFORM_SCHEMA # Jeśli potrzebujesz dla YAML
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er # Do usuwania encji z rejestru

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
    SERVICE_CLEAN_IMAGES, # Potrzebne dla wywołania z encji
    CONF_CAMERAS_CONFIG,   # Klucz do listy konfiguracji kamer
    CONF_CAMERA_ENTITY_ID, # Klucz do ID encji kamery w konfiguracji
    CONF_CAMERA_FRIENDLY_NAME # Klucz do przyjaznej nazwy kamery w konfiguracji
)

_LOGGER = logging.getLogger(__name__)

PLATE_READER_URL = "https://api.platerecognizer.com/v1/plate-reader/"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Enhanced PlateRecognizer from a config entry for multiple cameras."""
    
    # Pobierz aktywną konfigurację (połączenie data i options) z hass.data
    # Zakładamy, że init.py już to przygotował w hass.data[DOMAIN][entry.entry_id]
    entry_config = hass.data[DOMAIN].get(entry.entry_id)
    if not entry_config:
        _LOGGER.error(f"Config for entry {entry.entry_id} not found in hass.data. Cannot setup image processing entities.")
        return

    plate_manager = hass.data[DOMAIN].get("plate_manager")
    global_manager = hass.data[DOMAIN].get("global_recognition_manager")

    if not plate_manager:
        _LOGGER.error("PlateManager not found in hass.data. Critical for setup.")
        return # Nie można kontynuować bez PlateManager
    if not global_manager:
        _LOGGER.error("GlobalRecognitionManager not found in hass.data. Critical for setup.")
        return # Nie można kontynuować bez GlobalRecognitionManager

    # Bazowy folder zapisu, jeśli zdefiniowany globalnie w konfiguracji wpisu
    # Wcześniej ustaliliśmy, że to będzie stała wartość, ale na wszelki wypadek
    # można dać użytkownikowi opcję globalnego folderu w config flow.
    # Na razie trzymamy się stałego folderu dla uproszczenia, zgodnie z poprzednią wersją.
    save_file_folder_base = entry_config.get(CONF_SAVE_FILE_FOLDER, os.path.join(hass.config.path(), "www", "Tablice"))

    async def ensure_directory_exists(directory):
        def create_dir():
            try:
                os.makedirs(directory, exist_ok=True)
                _LOGGER.info("Created directory: %s", directory)
                return True
            except OSError as err:
                _LOGGER.warning("Failed to create directory %s: %s", directory, err)
                return False
        return await hass.async_add_executor_job(create_dir)

    # Upewnij się, że bazowy folder istnieje
    await ensure_directory_exists(save_file_folder_base)

    entities_to_add = []
    cameras_config_list = entry_config.get(CONF_CAMERAS_CONFIG, [])

    _LOGGER.debug(f"Setting up image_processing entities for entry {entry.entry_id} with cameras: {cameras_config_list}")

    for camera_conf in cameras_config_list:
        camera_entity_id = camera_conf.get(CONF_CAMERA_ENTITY_ID)
        camera_friendly_name = camera_conf.get(CONF_CAMERA_FRIENDLY_NAME)

        if not camera_entity_id or not camera_friendly_name:
            _LOGGER.warning(f"Skipping camera config due to missing entity_id or friendly_name: {camera_conf}")
            continue
        
        # Użyj globalnych ustawień z entry_config (które jest już scalone z data i options)
        api_key = entry_config.get(CONF_API_KEY) # API Key jest wymagany, powinien być w entry_config
        if not api_key:
            _LOGGER.error(f"API Key not found for camera {camera_friendly_name}. Skipping this camera.")
            continue

        region = entry_config.get(CONF_REGION, "pl") # Domyślnie "pl"
        save_timestamped_file = entry_config.get(CONF_SAVE_TIMESTAMPED_FILE, True)
        always_save_latest_file = entry_config.get(CONF_ALWAYS_SAVE_LATEST_FILE, True)
        consecutive_captures = entry_config.get(CONF_CONSECUTIVE_CAPTURES, 1)
        capture_interval = entry_config.get(CONF_CAPTURE_INTERVAL, 1.2)
        max_images = entry_config.get(CONF_MAX_IMAGES, 10)
        tolerate_one_mistake = entry_config.get(CONF_TOLERATE_ONE_MISTAKE, False)

        # Folder zapisu dla tej konkretnej kamery - można by to rozbudować o podfoldery
        # Na razie wszystkie kamery zapisują do tego samego `save_file_folder_base`
        # Można dodać opcję w config_flow: CONF_SUBFOLDER_PER_CAMERA
        # if entry_config.get(CONF_SUBFOLDER_PER_CAMERA, False):
        #     camera_slug = camera_friendly_name.lower().replace(" ", "_").replace(".", "_")
        #     specific_save_folder = os.path.join(save_file_folder_base, camera_slug)
        #     await ensure_directory_exists(specific_save_folder)
        # else:
        specific_save_folder = save_file_folder_base


        entity = EnhancedPlateRecognizer(
            hass=hass,
            config_entry_id=entry.entry_id, # Przekaż ID wpisu konfiguracyjnego
            camera_entity_id=camera_entity_id,
            camera_friendly_name=camera_friendly_name,
            api_key=api_key,
            region=region,
            save_file_folder=specific_save_folder, # Użyj folderu dla tej kamery
            save_timestamped_file=save_timestamped_file,
            always_save_latest_file=always_save_latest_file,
            consecutive_captures=consecutive_captures,
            capture_interval=capture_interval,
            max_images=max_images,
            plate_manager=plate_manager,
            tolerate_one_mistake=tolerate_one_mistake,
            global_manager=global_manager
        )
        entities_to_add.append(entity)

        # Utwórz dedykowany sensor dla tej kamery (stan początkowy)
        # Jego ID będzie np. sensor.recognized_car_kamera_brama
        # Ten sensor będzie żył tak długo, jak ta encja image_processing
        sensor_id = global_manager.get_camera_specific_sensor_id(camera_friendly_name)
        if not hass.states.get(sensor_id): # Twórz tylko jeśli nie istnieje (ważne przy reload)
            hass.states.async_set(
                sensor_id, "Brak danych",
                {"friendly_name": f"Rozpoznany samochód ({camera_friendly_name})"}
            )
            _LOGGER.debug(f"Created camera-specific sensor: {sensor_id}")
        else:
            _LOGGER.debug(f"Camera-specific sensor {sensor_id} already exists.")

    if entities_to_add:
        _LOGGER.info(f"Adding {len(entities_to_add)} image processing entities for Enhanced PlateRecognizer.")
        async_add_entities(entities_to_add)
    else:
        _LOGGER.info("No image processing entities to add for Enhanced PlateRecognizer.")


class EnhancedPlateRecognizer(ImageProcessingEntity):
    """Representation of an Enhanced PlateRecognizer entity for a specific camera."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry_id: str, # ID wpisu konfiguracyjnego do którego należy ta encja
        camera_entity_id: str,
        camera_friendly_name: str,
        api_key: str,
        region: str,
        save_file_folder: str,
        save_timestamped_file: bool,
        always_save_latest_file: bool,
        consecutive_captures: int,
        capture_interval: float,
        max_images: int,
        plate_manager, # Instancja PlateManager
        tolerate_one_mistake: bool,
        global_manager # Instancja GlobalRecognitionManager
    ):
        super().__init__()
        self.hass = hass
        self._config_entry_id = config_entry_id # Ważne dla device_info
        self._camera_entity_id = camera_entity_id
        self._camera_friendly_name = camera_friendly_name # Używane do logów, ID sensorów itp.
        
        # Nazwa tej encji image_processing - musi być unikalna w ramach HA
        # Używamy przyjaznej nazwy kamery, aby zapewnić unikalność jeśli użytkownik
        # skonfiguruje tę samą fizyczną kamerę pod różnymi nazwami w integracji.
        self._attr_name = f"PlateRecognizer {self._camera_friendly_name}"
        
        # Unikalne ID dla tej encji - na podstawie ID encji kamery, aby było stabilne
        self._attr_unique_id = f"{DOMAIN}_{self._camera_entity_id.replace('.', '_')}_epr"

        self._api_key = api_key
        self._region = region
        self._save_file_folder = save_file_folder
        self._save_timestamped_file = save_timestamped_file
        self._always_save_latest_file = always_save_latest_file
        self._consecutive_captures = consecutive_captures
        self._capture_interval = capture_interval
        self._max_images = max_images
        self._plate_manager = plate_manager
        self._tolerate_one_mistake = tolerate_one_mistake
        self._global_manager = global_manager
        
        self._attr_unit_of_measurement = "plates" # Zmieniono z "plate" na "plates" (liczba mnoga)
        self._vehicles = []
        self._statistics = None
        self._last_detection = None
        self._orientation = []
        self._processing = False # Flaga zapobiegająca wielokrotnemu przetwarzaniu
        self._attr_state = 0 # Stan encji: liczba wykrytych tablic

        self._regions_for_api = [region] if region else None # Dla API PlateRecognizer

        # ID dedykowanego sensora dla tej kamery
        self._camera_specific_recognized_sensor_id = self._global_manager.get_camera_specific_sensor_id(self._camera_friendly_name)
        
        # ID dla binarnego sensora wykrycia znanej tablicy dla tej kamery
        # Używamy _attr_unique_id (który jest już unikalny) jako bazę
        sane_binary_sensor_base_id = self._attr_unique_id.replace(f"{DOMAIN}_", "") 
        self._detect_known_plate_sensor_id = f"binary_sensor.{DOMAIN}_{sane_binary_sensor_base_id}_known_plate_detected"

        # Device Info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self._attr_unique_id)}, # Użyj unique_id encji jako identyfikatora urządzenia
            name=self._attr_name, # Nazwa urządzenia taka sama jak encji image_processing
            manufacturer="SmartKwadrat (Custom Integration)",
            model="Enhanced PlateRecognizer Camera Processor",
            sw_version=self.hass.data[DOMAIN].get("version", "0.1.6"), # Pobierz wersję z manifestu (potrzebne dodanie w init.py)
            via_device=(CAMERA_DOMAIN, self._camera_entity_id), # Powiązanie z encją kamery HA
            configuration_url=f"/config/integrations/integration/{DOMAIN}" # Ogólny link do integracji
            # Można dodać entry_type="service" jeśli urządzenie reprezentuje usługę a nie fizyczne urządzenie
        )
        _LOGGER.info(f"Initialized EnhancedPlateRecognizer: {self.name} (UID: {self.unique_id}) for camera: {self._camera_entity_id}")

    @property
    def camera_entity(self):
        """Return the camera entity id."""
        return self._camera_entity_id

    # name i unique_id są teraz jako _attr_name i _attr_unique_id
    # state jest jako _attr_state

    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        attr = {
            "vehicles": self._vehicles,
            "orientation": self._orientation,
            # "unit_of_measurement": self._attr_unit_of_measurement, # Już jest jako property
            "camera_entity_id": self._camera_entity_id,
            "camera_friendly_name": self._camera_friendly_name,
        }
        if self._regions_for_api:
            attr["api_regions"] = self._regions_for_api
        if self._save_file_folder:
            attr["save_file_folder"] = self._save_file_folder
            attr["save_timestamped_file"] = self._save_timestamped_file
            attr["always_save_latest_file"] = self._always_save_latest_file
        if self._statistics:
            attr["api_statistics"] = self._statistics # Zmieniono klucz dla jasności
        if self._last_detection:
            attr["last_detection_timestamp"] = self._last_detection # Zmieniono klucz
        return attr

    async def async_added_to_hass(self) -> None:
        """Wywoływane, gdy encja jest dodawana do Home Assistant."""
        await super().async_added_to_hass()
        # Utwórz/upewnij się, że sensor binarny istnieje
        if not self.hass.states.get(self._detect_known_plate_sensor_id):
            self.hass.states.async_set(self._detect_known_plate_sensor_id, "brak", {
                "friendly_name": f"Wykrycie znanej tablicy ({self._camera_friendly_name})",
                "device_class": "motion" # Można ustawić device_class
            })
            _LOGGER.debug(f"Created binary_sensor {self._detect_known_plate_sensor_id} for {self.name}")
        else:
            _LOGGER.debug(f"Binary_sensor {self._detect_known_plate_sensor_id} for {self.name} already exists.")


    async def async_will_remove_from_hass(self) -> None:
        """Wywoływane, gdy encja jest usuwana z Home Assistant."""
        await super().async_will_remove_from_hass()
        _LOGGER.info(f"Removing entity {self.entity_id} ({self.name}).")
        
        # Usuń dedykowany sensor tej kamery
        if self._camera_specific_recognized_sensor_id:
            _LOGGER.debug(f"Removing camera-specific sensor: {self._camera_specific_recognized_sensor_id}")
            self.hass.states.async_remove(self._camera_specific_recognized_sensor_id)
        
        # Usuń dane tej kamery z globalnego menedżera
        if self._global_manager:
            _LOGGER.debug(f"Removing camera data for {self._camera_friendly_name} from GlobalRecognitionManager.")
            self._global_manager.remove_camera_data(self._camera_friendly_name)
        
        # Usuń sensor binarny
        if self._detect_known_plate_sensor_id:
            _LOGGER.debug(f"Removing binary_sensor: {self._detect_known_plate_sensor_id}")
            self.hass.states.async_remove(self._detect_known_plate_sensor_id)

    async def async_process_image(self, image_bytes: bytes):
        """Process an image."""
        _LOGGER.debug(f"{self.name}: Starting image processing.")
        try:
            response_json = await self._call_plate_recognizer_api(image_bytes)
            if response_json:
                self._update_internal_attributes(response_json) # Aktualizuje self._vehicles, self._state itp.

                if self._save_file_folder and (self._save_timestamped_file or self._always_save_latest_file):
                    await self._save_image_to_disk(image_bytes)

                if self._max_images > 0 and self._save_file_folder:
                    from . import async_clean_old_images # Import wewnątrz, aby uniknąć problemów z cyklicznym importem
                    self.hass.async_create_task(
                        async_clean_old_images(self.hass, self._save_file_folder, self._max_images)
                    )
                
                # To powinno być wywołane, aby HA odświeżyło stan i atrybuty tej encji
                self.async_write_ha_state()

                # Aktualizacja sensorów (dedykowanego dla tej kamery i globalnych przez global_manager)
                await self._update_all_recognition_sensors(response_json)

                # Aktualizacja binarnego sensora wykrycia znanej tablicy
                detected_plates_for_binary_sensor = [res.get("plate", "").upper() for res in response_json.get("results", [])]
                await self._update_known_plate_binary_sensor(detected_plates_for_binary_sensor)
                
                _LOGGER.debug(f"{self.name}: Image processing finished. State: {self.state}, Plates: {self._vehicles}")
                return response_json # Zwraca przetworzone dane dla usługi 'scan'
            else:
                _LOGGER.warning(f"{self.name}: No response or error from PlateRecognizer API.")
                # Można ustawić stan na błąd lub nieznany
                self._attr_state = 0 # Lub jakiś stan błędu
                self._vehicles = []
                self.async_write_ha_state()
                # Mimo braku odpowiedzi z API, poinformuj global_manager, że ta kamera nie wykryła nic
                await self._update_all_recognition_sensors(None) # Przekaż None, aby obsłużyć przypadek braku danych
                await self._update_known_plate_binary_sensor([])


        except Exception as e:
            _LOGGER.error(f"{self.name}: Error in async_process_image: {e}", exc_info=True)
            self._attr_state = 0 # Lub stan błędu
            self.async_write_ha_state()
        return None


    async def async_scan_and_process(self):
        """Asynchronously captures and processes an image from the camera."""
        if self._processing:
            _LOGGER.warning(f"{self.name}: Already processing, skipping scan request.")
            return

        self._processing = True
        _LOGGER.info(f"{self.name}: Starting scan and process cycle (up to {self._consecutive_captures} captures).")
        try:
            for i in range(self._consecutive_captures):
                if i > 0:
                    await asyncio.sleep(self._capture_interval)
                
                _LOGGER.debug(f"{self.name}: Capture attempt {i+1}/{self._consecutive_captures} for camera {self._camera_entity_id}")
                try:
                    camera_component = self.hass.components.camera
                    image_data = await camera_component.async_get_image(self._camera_entity_id)
                    if image_data and image_data.content:
                        _LOGGER.debug(f"{self.name}: Image captured successfully ({len(image_data.content)} bytes). Processing...")
                        await self.async_process_image(image_data.content)
                        # Jeśli chcemy przerwać po pierwszym udanym rozpoznaniu w cyklu:
                        # if self.state > 0: 
                        #     _LOGGER.info(f"{self.name}: Plates detected, ending consecutive captures early.")
                        #     break 
                    else:
                        _LOGGER.warning(f"{self.name}: Failed to capture image from {self._camera_entity_id} (no content).")
                except Exception as e_capture:
                    _LOGGER.error(f"{self.name}: Error capturing/processing image from {self._camera_entity_id} in attempt {i+1}: {e_capture}", exc_info=True)
        except Exception as e_loop:
            _LOGGER.error(f"{self.name}: Error in scan and process loop: {e_loop}", exc_info=True)
        finally:
            self._processing = False
            _LOGGER.info(f"{self.name}: Scan and process cycle finished.")


    async def _call_plate_recognizer_api(self, image_bytes: bytes):
        """Calls the PlateRecognizer API and returns the JSON response."""
        headers = {"Authorization": f"Token {self._api_key}"}
        _LOGGER.debug(f"{self.name}: Calling PlateRecognizer API. Regions: {self._regions_for_api}")
        try:
            timeout = aiohttp.ClientTimeout(total=60)  # 60 sekund na całe żądanie
            async with aiohttp.ClientSession(timeout=timeout) as session:
                form_data = aiohttp.FormData()
                form_data.add_field("upload", image_bytes, filename="image.jpg", content_type="image/jpeg")
                if self._regions_for_api: # API oczekuje listy regionów
                    for region_code in self._regions_for_api:
                        form_data.add_field("regions", region_code)
                
                async with session.post(PLATE_READER_URL, headers=headers, data=form_data) as resp:
                    if resp.status == 200:
                        response_data = await resp.json()
                        _LOGGER.debug(f"{self.name}: API response OK (status {resp.status}). Results: {len(response_data.get('results', []))}")
                        return response_data
                    else:
                        response_text = await resp.text()
                        _LOGGER.error(f"{self.name}: PlateRecognizer API error. Status: {resp.status}. Response: {response_text}")
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err_http:
            _LOGGER.error(f"{self.name}: HTTP error calling PlateRecognizer API: {err_http}")
            return None
        except Exception as e_api:
            _LOGGER.error(f"{self.name}: Unexpected error calling PlateRecognizer API: {e_api}", exc_info=True)
            return None


    def _update_internal_attributes(self, response_json):
        """Updates internal attributes based on the API response."""
        if not response_json or "results" not in response_json:
            self._attr_state = 0
            self._vehicles = []
            self._orientation = []
            # Nie zeruj statystyk API, jeśli błąd był jednorazowy
            # self._statistics = None 
            return

        results = response_json.get("results", [])
        self._attr_state = len(results) # Ustawia stan encji na liczbę wykrytych tablic

        current_vehicles = []
        current_orientation = []
        for res_item in results:
            vehicle_info = {"plate": res_item.get("plate", "").upper()} # Zawsze normalizuj do wielkich liter
            if "vehicle" in res_item and isinstance(res_item["vehicle"], dict) and "type" in res_item["vehicle"]:
                vehicle_info["type"] = res_item["vehicle"]["type"]
            else:
                vehicle_info["type"] = "unknown"
            current_vehicles.append(vehicle_info)

            if "orientation" in res_item and isinstance(res_item["orientation"], dict) and "angle" in res_item["orientation"]:
                current_orientation.append(res_item["orientation"]["angle"])
            else:
                current_orientation.append(None)
        
        self._vehicles = current_vehicles
        self._orientation = current_orientation
        self._last_detection = datetime.datetime.now().isoformat() # Użyj ISO format dla spójności

        if "usage" in response_json and isinstance(response_json["usage"], dict):
            usage = response_json["usage"]
            self._statistics = {
                "total_calls": usage.get("total_calls"),
                "usage_year": usage.get("year"),
                "usage_month": usage.get("month"),
                "resets_on_day": usage.get("resets_on"), # Dzień miesiąca
                "calls_this_period": usage.get("calls"),
                "calls_remaining": usage.get("calls_remaining"),
            }
        _LOGGER.debug(f"{self.name}: Internal attributes updated. State: {self.state}, Vehicles: {self._vehicles}")


    async def _save_image_to_disk(self, image_bytes: bytes):
        """Asynchronously saves the image to disk."""
        if not self._save_file_folder:
            _LOGGER.debug(f"{self.name}: Save file folder not configured, skipping image save.")
            return
        
        try:
            timestamp_suffix = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3] # Dodaj milisekundy dla unikalności
            # Użyj self._camera_friendly_name do tworzenia nazw plików, aby były bardziej czytelne
            safe_camera_name = self._camera_friendly_name.lower().replace(" ", "_").replace(".", "_")
            
            def save_action():
                files_saved = []
                try:
                    if self._save_timestamped_file:
                        ts_filename = f"{safe_camera_name}_{timestamp_suffix}.jpg"
                        ts_path = os.path.join(self._save_file_folder, ts_filename)
                        with open(ts_path, "wb") as f:
                            f.write(image_bytes)
                        files_saved.append(ts_path)
                    
                    if self._always_save_latest_file:
                        latest_filename = f"{safe_camera_name}_latest.jpg"
                        latest_path = os.path.join(self._save_file_folder, latest_filename)
                        with open(latest_path, "wb") as f:
                            f.write(image_bytes)
                        files_saved.append(latest_path)
                    
                    if files_saved:
                        _LOGGER.info(f"{self.name}: Saved image(s): {', '.join(files_saved)}")
                    return True
                except (IOError, OSError) as e_io:
                    _LOGGER.error(f"{self.name}: I/O error saving image: {e_io}")
                    return False
            
            await self.hass.async_add_executor_job(save_action)
        except Exception as e_save:
            _LOGGER.error(f"{self.name}: Unexpected error in _save_image_to_disk: {e_save}", exc_info=True)


    async def _update_all_recognition_sensors(self, response_json_or_none):
        """Updates the camera-specific sensor and reports to the GlobalRecognitionManager."""
        try:
            plates_str_for_report = "Brak"
            message_specific_for_this_camera = "Brak danych" # Domyślny stan dla sensora specyficznego
            is_any_plate_known_on_this_camera = False

            if response_json_or_none and "results" in response_json_or_none:
                results = response_json_or_none.get("results", [])
                detected_plates_on_this_camera = [res.get("plate", "").upper() for res in results]

                if detected_plates_on_this_camera:
                    plates_str_for_report = ", ".join(detected_plates_on_this_camera)
                    
                    recognized_known_plates_here = []
                    for plate_text in detected_plates_on_this_camera:
                        if await self._plate_manager.async_is_plate_recognized(plate_text, self._tolerate_one_mistake): # Przekaż tolerancję
                            recognized_known_plates_here.append(plate_text)
                    
                    if recognized_known_plates_here:
                        is_any_plate_known_on_this_camera = True
                        first_known_plate = recognized_known_plates_here[0]
                        message_specific_for_this_camera = f"Rozpoznano znaną tablicę: {first_known_plate}"
                        if len(recognized_known_plates_here) > 1:
                            message_specific_for_this_camera += f" (oraz {len(recognized_known_plates_here) - 1} innych znanych)"
                        elif len(detected_plates_on_this_camera) > len(recognized_known_plates_here):
                             other_detected_count = len(detected_plates_on_this_camera) - len(recognized_known_plates_here)
                             message_specific_for_this_camera += f" (oraz {other_detected_count} innych wykrytych nieznanych)"

                    elif detected_plates_on_this_camera: # Wykryto tablice, ale żadna nie jest znana
                        message_specific_for_this_camera = f"Wykryto nieznane tablice: {plates_str_for_report}"
                else: # Brak wyników, ale API odpowiedziało
                    message_specific_for_this_camera = "Brak tablic na obrazie"
            # else: response_json_or_none jest None (błąd API) - message_specific_for_this_camera pozostaje "Brak danych"

            # Aktualizacja dedykowanego sensora tej kamery
            if self.hass.states.get(self._camera_specific_recognized_sensor_id): # Sprawdź czy sensor wciąż istnieje
                self.hass.states.async_set(
                    self._camera_specific_recognized_sensor_id,
                    message_specific_for_this_camera,
                    {"friendly_name": f"Rozpoznany samochód ({self._camera_friendly_name})"}
                )
                # Automatyczne czyszczenie tego sensora po pewnym czasie
                if message_specific_for_this_camera != "Brak danych":
                    self.hass.async_create_task(self._clear_specific_recognized_car_sensor(20)) # Czas w sekundach
            else:
                _LOGGER.warning(f"Sensor {self._camera_specific_recognized_sensor_id} not found, cannot update state.")


            # Raportowanie do globalnego menedżera
            # global_manager powinien obsłużyć aktualizację sensorów "sensor.last_recognized_car" i "sensor.recognized_car"
            self._global_manager.report_recognition(
                camera_friendly_name=self._camera_friendly_name, # Użyj oryginalnej przyjaznej nazwy
                plates_str=plates_str_for_report,
                recognized_msg=message_specific_for_this_camera, # Przekaż komunikat specyficzny dla tej kamery
                is_known=is_any_plate_known_on_this_camera
            )
            _LOGGER.debug(f"{self.name}: Updated recognition sensors. Specific: '{message_specific_for_this_camera}', Known here: {is_any_plate_known_on_this_camera}")

        except Exception as e_sensors:
            _LOGGER.error(f"{self.name}: Error updating recognition sensors: {e_sensors}", exc_info=True)

    async def _clear_specific_recognized_car_sensor(self, wait_seconds: int):
        """Clears the camera-specific recognized car sensor after a delay."""
        await asyncio.sleep(wait_seconds)
        # Sprawdź, czy stan nie został ponownie zmieniony na coś innego niż "Brak danych"
        current_sensor_state = self.hass.states.get(self._camera_specific_recognized_sensor_id)
        if current_sensor_state and current_sensor_state.state != "Brak danych":
            self.hass.states.async_set(
                self._camera_specific_recognized_sensor_id,
                "Brak danych", # Wartość po zresetowaniu
                {"friendly_name": f"Rozpoznany samochód ({self._camera_friendly_name})"}
            )
            _LOGGER.debug(f"Cleared camera-specific sensor {self._camera_specific_recognized_sensor_id}")


    async def _update_known_plate_binary_sensor(self, detected_plates_list: list):
        """Updates the binary_sensor indicating if a known plate was detected by this camera."""
        try:
            if not self.hass.states.get(self._detect_known_plate_sensor_id):
                _LOGGER.warning(f"Binary sensor {self._detect_known_plate_sensor_id} not found, cannot update.")
                return

            is_known_detected_here = False
            if detected_plates_list:
                for plate_text in detected_plates_list:
                    if await self._plate_manager.async_is_plate_recognized(plate_text, self._tolerate_one_mistake):
                        is_known_detected_here = True
                        break
            
            new_state = "on" if is_known_detected_here else "off"
            # Pobierz obecny stan, aby uniknąć niepotrzebnych aktualizacji
            current_state_obj = self.hass.states.get(self._detect_known_plate_sensor_id)
            current_ha_state = current_state_obj.state if current_state_obj else None

            if current_ha_state != new_state:
                self.hass.states.async_set(self._detect_known_plate_sensor_id, new_state, {
                    "friendly_name": f"Wykrycie znanej tablicy ({self._camera_friendly_name})",
                    "device_class": "motion" # Lub inny odpowiedni
                })
                _LOGGER.debug(f"Binary sensor {self._detect_known_plate_sensor_id} updated to: {new_state}")

            # Jeśli wykryto, ustaw timer do automatycznego wyłączenia (resetu)
            if is_known_detected_here:
                async def clear_binary_sensor_after_delay():
                    await asyncio.sleep(10) # Czas w sekundach, np. 10s
                    # Przed wyłączeniem, sprawdź czy stan się nie zmienił (np. nowe wykrycie)
                    current_state_obj_before_clear = self.hass.states.get(self._detect_known_plate_sensor_id)
                    if current_state_obj_before_clear and current_state_obj_before_clear.state == "on":
                        self.hass.states.async_set(self._detect_known_plate_sensor_id, "off", {
                            "friendly_name": f"Wykrycie znanej tablicy ({self._camera_friendly_name})"
                        })
                        _LOGGER.debug(f"Binary sensor {self._detect_known_plate_sensor_id} cleared after delay.")
                
                self.hass.async_create_task(clear_binary_sensor_after_delay())

        except Exception as e_binary:
            _LOGGER.error(f"{self.name}: Error updating known plate binary sensor: {e_binary}", exc_info=True)

    @staticmethod
    def _levenshtein_distance(s1, s2):
        """Oblicza odległość Levenshteina między dwoma stringami."""
        if not isinstance(s1, str) or not isinstance(s2, str):
            # Obsługa przypadków, gdy dane wejściowe nie są stringami
            return float('inf')  # Zwraca "nieskończoność" co oznacza brak dopasowania

        if len(s1) < len(s2):
            return EnhancedPlateRecognizer._levenshtein_distance(s2, s1)
        if len(s2) == 0:
            return len(s1)

        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]