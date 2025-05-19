"""Enhanced PlateRecognizer image_processing platform (YAML setup only)."""

import asyncio
import datetime
import logging
import os
import aiohttp
import voluptuous as vol

from homeassistant.components.image_processing import (
    ImageProcessingEntity,
    PLATFORM_SCHEMA,
)
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_API_TOKEN,
    CONF_REGIONS,
    CONF_CONSECUTIVE_CAPTURES,
    CONF_CAPTURE_INTERVAL,
    CONF_SAVE_FILE_FOLDER,
    CONF_SAVE_TIMESTAMPED_FILE,
    CONF_ALWAYS_SAVE_LATEST_FILE,
    CONF_MAX_IMAGES,
    CONF_TOLERATE_ONE_MISTAKE,
)

_LOGGER = logging.getLogger(__name__)
PLATE_READER_URL = "https://api.platerecognizer.com/v1/plate-reader/"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_API_TOKEN): cv.string,
    vol.Optional(CONF_REGIONS, default=[]): vol.All(cv.ensure_list, [cv.string]),
    vol.Optional(CONF_SAVE_FILE_FOLDER, default="/config/www/Tablice"): cv.string,
    vol.Optional(CONF_MAX_IMAGES, default=10): vol.All(vol.Coerce(int), vol.Range(min=1, max=30)),
    vol.Optional(CONF_CONSECUTIVE_CAPTURES, default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=5)),
    vol.Optional(CONF_CAPTURE_INTERVAL, default=1.2): vol.All(vol.Coerce(float), vol.Range(min=1.0, max=2.0)),
    vol.Optional(CONF_SAVE_TIMESTAMPED_FILE, default=True): cv.boolean,
    vol.Optional(CONF_ALWAYS_SAVE_LATEST_FILE, default=True): cv.boolean,
    vol.Optional(CONF_TOLERATE_ONE_MISTAKE, default=False): cv.boolean,
    vol.Required("source"): vol.All(cv.ensure_list, [
        {
            vol.Required("entity_id"): cv.entity_id,
            vol.Optional("friendly_name"): cv.string,
        }
    ]),
})

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Enhanced PlateRecognizer from YAML."""
    _LOGGER.info("Setting up Enhanced PlateRecognizer image_processing platform from YAML.")
    api_token = config[CONF_API_TOKEN]
    regions = config[CONF_REGIONS]
    save_file_folder = config[CONF_SAVE_FILE_FOLDER]
    max_images = config[CONF_MAX_IMAGES]
    consecutive_captures = config[CONF_CONSECUTIVE_CAPTURES]
    capture_interval = config[CONF_CAPTURE_INTERVAL]
    save_timestamped_file = config[CONF_SAVE_TIMESTAMPED_FILE]
    always_save_latest_file = config[CONF_ALWAYS_SAVE_LATEST_FILE]
    tolerate_one_mistake = config[CONF_TOLERATE_ONE_MISTAKE]
    cameras = config["source"]

    # Pobierz menedżery z hass.data (muszą być zainicjalizowane w __init__.py)
    plate_manager = hass.data[DOMAIN].get("plate_manager")
    global_manager = hass.data[DOMAIN].get("global_recognition_manager")

    # Upewnij się, że katalog istnieje
    def create_dir_sync():
        try:
            if not os.path.isdir(save_file_folder):
                os.makedirs(save_file_folder, exist_ok=True)
                _LOGGER.info(f"Utworzono katalog: {save_file_folder}")
            return True
        except OSError as err:
            _LOGGER.error(f"Nie udało się utworzyć katalogu {save_file_folder}: {err}")
            return False

    await hass.async_add_executor_job(create_dir_sync)

    entities = []
    for cam in cameras:
        camera_entity_id = cam["entity_id"]
        camera_friendly_name = cam.get("friendly_name", camera_entity_id.split(".")[-1])
        entities.append(
            EnhancedPlateRecognizer(
                hass=hass,
                camera_entity_id=camera_entity_id,
                camera_friendly_name=camera_friendly_name,
                api_token=api_token,
                regions=regions,
                save_file_folder=save_file_folder,
                save_timestamped_file=save_timestamped_file,
                always_save_latest_file=always_save_latest_file,
                consecutive_captures=consecutive_captures,
                capture_interval=capture_interval,
                max_images=max_images,
                plate_manager=plate_manager,
                tolerate_one_mistake=tolerate_one_mistake,
                global_manager=global_manager,
            )
        )
    async_add_entities(entities)

class EnhancedPlateRecognizer(ImageProcessingEntity):
    """Representation of an Enhanced PlateRecognizer entity for a specific camera."""

    def __init__(
        self,
        hass,
        camera_entity_id,
        camera_friendly_name,
        api_token,
        regions,
        save_file_folder,
        save_timestamped_file,
        always_save_latest_file,
        consecutive_captures,
        capture_interval,
        max_images,
        plate_manager,
        tolerate_one_mistake,
        global_manager,
    ):
        super().__init__()
        self.hass = hass
        self._camera_entity_id = camera_entity_id
        self._camera_friendly_name = camera_friendly_name
        self._api_token = api_token
        self._regions = regions
        self._save_file_folder = save_file_folder
        self._save_timestamped_file = save_timestamped_file
        self._always_save_latest_file = always_save_latest_file
        self._consecutive_captures = consecutive_captures
        self._capture_interval = capture_interval
        self._max_images = max_images
        self._plate_manager = plate_manager
        self._tolerate_one_mistake = tolerate_one_mistake
        self._global_manager = global_manager

        self._attr_name = f"PlateRecognizer {self._camera_friendly_name}"
        self._attr_unique_id = f"{DOMAIN}_{self._camera_entity_id.replace('.', '_')}_yaml"
        self._attr_unit_of_measurement = "plates"
        self._vehicles = []
        self._statistics = None
        self._last_detection = None
        self._orientation = []
        self._processing = False
        self._attr_state = 0

    @property
    def camera_entity(self):
        return self._camera_entity_id

    @property
    def extra_state_attributes(self):
        attr = {
            "vehicles": self._vehicles,
            "orientation": self._orientation,
            "camera_entity_id": self._camera_entity_id,
            "camera_friendly_name": self._camera_friendly_name,
            "api_regions": self._regions,
            "save_file_folder": self._save_file_folder,
            "save_timestamped_file": self._save_timestamped_file,
            "always_save_latest_file": self._always_save_latest_file,
        }
        if self._statistics:
            attr["api_statistics"] = self._statistics
        if self._last_detection:
            attr["last_detection_timestamp"] = self._last_detection
        return attr

    async def async_process_image(self, image_bytes: bytes):
        """Process an image using Plate Recognizer API."""
        # Przygotuj regiony na podstawie konfiguracji
        self._regions_for_api = self._regions if self._regions else []
        
        # Wywołaj API
        response = await self._call_plate_recognizer_api(image_bytes)
        
        # Zapisz zdjęcie jeśli skonfigurowano
        await self._save_image_to_disk(image_bytes)
        
        # Zaktualizuj atrybuty
        self._update_internal_attributes(response)
        
        # Zaktualizuj sensory
        await self._update_all_recognition_sensors(response)

    async def async_scan_and_process(self):
        """Scan for plates by capturing an image from the camera and then processing it."""
        _LOGGER.debug(f"{self.name}: Rozpoczynanie skanowania...")
        
        if self._processing:
            _LOGGER.warning(f"{self.name}: Przetwarzanie jest już w toku, pomijam żądanie.")
            return
        
        self._processing = True
        
        try:
            # Wykonaj serię zdjęć w odstępach
            for capture_index in range(self._consecutive_captures):
                if capture_index > 0:
                    # Czekaj między kolejnymi zdjęciami
                    await asyncio.sleep(self._capture_interval)
                    
                _LOGGER.debug(f"{self.name}: Pobieranie obrazu dla kamery {self.camera_entity} (zdjęcie {capture_index + 1}/{self._consecutive_captures})")
                
                # Pobierz obraz z kamery
                try:
                    image = await camera.async_get_image(self.camera_entity)
                    if not image:
                        _LOGGER.error(f"{self.name}: Nie można pobrać obrazu z kamery {self.camera_entity}")
                        continue
                    
                    # Przetwórz obraz
                    await self.async_process_image(image.content)
                    
                except Exception as capture_err:
                    _LOGGER.error(f"{self.name}: Błąd podczas przetwarzania obrazu: {capture_err}", exc_info=True)
        finally:
            self._processing = False
            _LOGGER.debug(f"{self.name}: Zakończono przetwarzanie.")


    async def _call_plate_recognizer_api(self, image_bytes: bytes):
        """Call the Plate Recognizer API with the provided image bytes."""
        headers = {"Authorization": f"Token {self._api_token}"}
        _LOGGER.debug(f"{self.name}: Wywoływanie API PlateRecognizer. URL: {PLATE_READER_URL}, Regiony: {self._regions_for_api}")
        try:
            timeout = aiohttp.ClientTimeout(total=60) # 60 sekund globalny timeout dla operacji
            async with aiohttp.ClientSession(timeout=timeout) as session:
                form_data = aiohttp.FormData()
                form_data.add_field("upload", image_bytes, filename="image.jpg", content_type="image/jpeg")

                # Dodaj regiony do FormData, jeśli są zdefiniowane
                if self._regions_for_api:
                    for region_code in self._regions_for_api:
                        form_data.add_field("regions", region_code)
                        _LOGGER.debug(f"{self.name}: Dodano region '{region_code}' do żądania API.")

                _LOGGER.debug(f"{self.name}: Wysyłanie żądania POST do API...")
                async with session.post(PLATE_READER_URL, headers=headers, data=form_data) as resp:
                    if resp.status == 200:
                        response_data = await resp.json()
                        _LOGGER.debug(
                            f"{self.name}: Odpowiedź API OK (status {resp.status}). "
                            f"Liczba wyników: {len(response_data.get('results', []))}. "
                            f"Odpowiedź: {response_data}" # Loguj całą odpowiedź dla debugowania
                        )
                        return response_data
                    else:
                        response_text = await resp.text() # Pobierz tekst odpowiedzi w przypadku błędu
                        _LOGGER.error(
                            f"{self.name}: Błąd API PlateRecognizer. Status: {resp.status}. Odpowiedź: {response_text}"
                        )
                        return None
        except (aiohttp.ClientError, asyncio.TimeoutError) as err_http:
            _LOGGER.error(f"{self.name}: Błąd HTTP/Timeout podczas wywoływania API PlateRecognizer: {err_http}")
            return None
        except Exception as e_api:
            _LOGGER.error(f"{self.name}: Nieoczekiwany błąd podczas wywoływania API PlateRecognizer: {e_api}", exc_info=True)
            return None


    def _update_internal_attributes(self, response_json):
        """Update internal attributes based on API response."""
        _LOGGER.debug(f"{self.name}: Rozpoczynanie aktualizacji atrybutów wewnętrznych na podstawie odpowiedzi API: {response_json}")
        if not response_json or "results" not in response_json:
            _LOGGER.debug(f"{self.name}: Brak wyników w odpowiedzi API lub nieprawidłowa odpowiedź. Resetuję stan.")
            self._attr_state = 0
            self._vehicles = []
            self._orientation = []
            self._last_detection = None # Resetuj też ostatnią detekcję
            self._statistics = None # Resetuj statystyki
            return

        results = response_json.get("results", [])
        self._attr_state = len(results) # Ustaw stan na liczbę wykrytych tablic

        current_vehicles = []
        current_orientation = []
        for res_item in results:
            vehicle_info = {"plate": res_item.get("plate", "N/A").upper()} # Domyślna wartość "N/A"
            # Sprawdź, czy 'vehicle' i 'type' istnieją
            if "vehicle" in res_item and isinstance(res_item["vehicle"], dict) and "type" in res_item["vehicle"]:
                vehicle_info["type"] = res_item["vehicle"]["type"]
            else:
                vehicle_info["type"] = "unknown" # Domyślna wartość
            current_vehicles.append(vehicle_info)

            # Sprawdź, czy 'orientation' i 'angle' istnieją
            if "orientation" in res_item and isinstance(res_item["orientation"], list) and len(res_item["orientation"]) > 0:
                # API zwraca listę obiektów orientacji, bierzemy pierwszy
                orientation_data = res_item["orientation"][0]
                if isinstance(orientation_data, dict) and "angle" in orientation_data:
                     current_orientation.append(orientation_data["angle"])
                else:
                    current_orientation.append(None)
            elif "orientation" in res_item and isinstance(res_item["orientation"], dict) and "angle" in res_item["orientation"]:
                # Starszy format, gdzie orientation jest słownikiem (na wszelki wypadek)
                current_orientation.append(res_item["orientation"]["angle"])
            else:
                current_orientation.append(None) # Domyślna wartość

        self._vehicles = current_vehicles
        self._orientation = current_orientation
        self._last_detection = datetime.datetime.now(datetime.timezone.utc).isoformat() # Zaktualizuj czas ostatniej detekcji (UTC)

        if "usage" in response_json and isinstance(response_json["usage"], dict):
            usage = response_json["usage"]
            self._statistics = {
                "total_calls": usage.get("total_calls"),
                "usage_year": usage.get("year"),
                "usage_month": usage.get("month"),
                "resets_on_day": usage.get("resets_on"),
                "calls_this_period": usage.get("calls"),
                "calls_remaining": usage.get("calls_remaining"),
            }
        else:
            self._statistics = None # Wyczyść statystyki, jeśli nie ma ich w odpowiedzi

        _LOGGER.debug(f"{self.name}: Zaktualizowano atrybuty wewnętrzne. Stan: {self.state}, Pojazdy: {self._vehicles}, Orientacja: {self._orientation}")


    async def _save_image_to_disk(self, image_bytes: bytes):
        """Save the image to disk if configured."""
        if not self._save_file_folder:
            _LOGGER.debug(f"{self.name}: Folder zapisu nie skonfigurowany, pomijam zapis obrazu.")
            return

        _LOGGER.debug(f"{self.name}: Przygotowywanie do zapisu obrazu w folderze: {self._save_file_folder}")
        try:
            timestamp_suffix = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3] # Do milisekund
            # Użyj camera_friendly_name do nazwy pliku, oczyszczając ją
            safe_camera_name = self._camera_friendly_name.lower().replace(" ", "_").replace(".", "_")

            def save_action_sync(): # Zmieniono nazwę, aby uniknąć konfliktu
                """Synchronous part of saving files."""
                files_actually_saved = [] # Zmieniono nazwę
                try:
                    if self._save_timestamped_file:
                        ts_filename = f"{safe_camera_name}_{timestamp_suffix}.jpg"
                        ts_path = os.path.join(self._save_file_folder, ts_filename)
                        _LOGGER.debug(f"{self.name}: Zapisywanie obrazu z timestampem: {ts_path}")
                        with open(ts_path, "wb") as f:
                            f.write(image_bytes)
                        files_actually_saved.append(ts_path) # Zmieniono nazwę

                    if self._always_save_latest_file:
                        latest_filename = f"{safe_camera_name}_latest.jpg"
                        latest_path = os.path.join(self._save_file_folder, latest_filename)
                        _LOGGER.debug(f"{self.name}: Zapisywanie najnowszego obrazu: {latest_path}")
                        with open(latest_path, "wb") as f:
                            f.write(image_bytes)
                        files_actually_saved.append(latest_path) # Zmieniono nazwę

                    if files_actually_saved: # Zmieniono nazwę
                        _LOGGER.info(f"{self.name}: Zapisano obraz(y): {', '.join(files_actually_saved)}") # Zmieniono nazwę
                    else:
                        _LOGGER.debug(f"{self.name}: Żadne flagi zapisu (_save_timestamped_file, _always_save_latest_file) nie były aktywne. Nie zapisano obrazu.")
                    return True # Sukces, jeśli nie było błędów I/O, nawet jeśli nic nie zapisano
                except (IOError, OSError) as e_io:
                    _LOGGER.error(f"{self.name}: Błąd I/O podczas zapisu obrazu: {e_io}")
                    return False # Błąd zapisu

            await self.hass.async_add_executor_job(save_action_sync) # Użyto nowej nazwy funkcji
        except Exception as e_save:
            _LOGGER.error(f"{self.name}: Nieoczekiwany błąd w _save_image_to_disk: {e_save}", exc_info=True)


    async def _update_all_recognition_sensors(self, response_json_or_none):
        """Update all relevant recognition sensors based on API response."""
        _LOGGER.debug(f"{self.name}: Rozpoczynanie aktualizacji sensorów rozpoznawania. Odpowiedź API: {'Jest' if response_json_or_none else 'Brak'}")
        try:
            plates_str_for_report = "Brak" # To, co trafi do GlobalManager jako wykryte tablice
            message_specific_for_this_camera = "Brak danych" # Domyślny stan sensora specyficznego dla kamery
            is_any_plate_known_on_this_camera = False # Czy na tej kamerze wykryto znaną tablicę

            if response_json_or_none and "results" in response_json_or_none:
                results = response_json_or_none.get("results", [])
                _LOGGER.debug(f"{self.name}: Wyniki API do aktualizacji sensorów: {results}")
                detected_plates_on_this_camera = [res.get("plate", "").upper() for res in results if res.get("plate")] # Filtruj puste/None tablice

                if detected_plates_on_this_camera:
                    plates_str_for_report = ", ".join(detected_plates_on_this_camera)
                    recognized_known_plates_here = [] # Lista znanych tablic wykrytych na tej kamerze
                    
                    recognized_known_plates_here = []
                    recognized_known_plates_saved = []

                    for plate_text in detected_plates_on_this_camera:
                        saved_plate = await self._plate_manager.async_get_recognized_plate(plate_text, self._tolerate_one_mistake)
                        if saved_plate:
                            recognized_known_plates_here.append(plate_text)
                            recognized_known_plates_saved.append(saved_plate)
                            _LOGGER.debug(f"{self.name}: Tablica '{plate_text}' jest ZNANA (tolerancja: {self._tolerate_one_mistake}).")
                        else:
                            _LOGGER.debug(f"{self.name}: Tablica '{plate_text}' jest NIEZNANA (tolerancja: {self._tolerate_one_mistake}).")

                    if recognized_known_plates_saved:
                        is_any_plate_known_on_this_camera = True
                        first_saved_plate = recognized_known_plates_saved[0]
                        message_specific_for_this_camera = f"Rozpoznano znaną tablicę: {first_saved_plate}"
                        if len(recognized_known_plates_here) > 1:
                            message_specific_for_this_camera += f" (oraz {len(recognized_known_plates_here) - 1} innych znanych)"
                        # Dodaj informację o innych wykrytych (nieznanych), jeśli są i nie ma więcej znanych
                        elif len(detected_plates_on_this_camera) > len(recognized_known_plates_here):
                             other_detected_count = len(detected_plates_on_this_camera) - len(recognized_known_plates_here)
                             message_specific_for_this_camera += f" (oraz {other_detected_count} innych wykrytych nieznanych)"
                    elif detected_plates_on_this_camera: # Wykryto tablice, ale żadna nie jest znana
                        message_specific_for_this_camera = f"Wykryto nieznane tablice: {plates_str_for_report}"
                    # else: Jeśli detected_plates_on_this_camera jest puste, message_specific_for_this_camera pozostanie "Brak tablic na obrazie" (ustawione niżej)
                else: # Brak tablic w wynikach API (pusta lista "results" lub brak pola "plate")
                    _LOGGER.debug(f"{self.name}: Brak tablic w wynikach API do aktualizacji sensorów.")
                    message_specific_for_this_camera = "Brak tablic na obrazie"
            else: # response_json_or_none jest None lub nie ma klucza "results"
                _LOGGER.debug(f"{self.name}: Brak odpowiedzi API lub nieprawidłowa struktura do aktualizacji sensorów.")
                message_specific_for_this_camera = "Błąd API lub brak danych"


            # Aktualizacja sensora specyficznego dla kamery
            if self.hass.states.get(self._camera_specific_recognized_sensor_id):
                _LOGGER.debug(f"{self.name}: Aktualizowanie stanu sensora '{self._camera_specific_recognized_sensor_id}' na: '{message_specific_for_this_camera}'")
                self.hass.states.async_set(
                    self._camera_specific_recognized_sensor_id,
                    message_specific_for_this_camera,
                    {"friendly_name": f"Rozpoznany samochód ({self._camera_friendly_name})"} # Zachowaj oryginalną przyjazną nazwę
                )
                # Zaplanuj czyszczenie tego sensora tylko jeśli zmienił stan z "Brak danych" (lub podobnego stanu spoczynku)
                if message_specific_for_this_camera not in ["Brak danych", "Brak tablic na obrazie", "Błąd API lub brak danych"]:
                    _LOGGER.debug(f"{self.name}: Planowanie czyszczenia sensora '{self._camera_specific_recognized_sensor_id}'.")
                    self.hass.async_create_task(self._clear_specific_recognized_car_sensor(20))
            else:
                _LOGGER.warning(f"{self.name}: Sensor specyficzny dla kamery '{self._camera_specific_recognized_sensor_id}' nie istnieje w stanach HA.")


            # Zgłoś rozpoznanie do GlobalRecognitionManager
            _LOGGER.debug(
                f"{self.name}: Zgłaszanie rozpoznania do GlobalManager. Kamera: '{self._camera_friendly_name}', "
                f"Wykryte tablice (string): '{plates_str_for_report}', "
                f"Komunikat dla tej kamery: '{message_specific_for_this_camera}', "
                f"Czy znana na tej kamerze: {is_any_plate_known_on_this_camera}"
            )

            # Jeśli rozpoznano znane tablice – przekaż zapisane, nie wykryte
            if recognized_known_plates_saved:
                plates_str_for_report = ", ".join(recognized_known_plates_saved)
            elif detected_plates_on_this_camera:
                plates_str_for_report = ", ".join(detected_plates_on_this_camera)
            else:
                plates_str_for_report = "Brak"

            self._global_manager.report_recognition(
                camera_friendly_name=self._camera_friendly_name,
                plates_str=plates_str_for_report,
                recognized_msg=message_specific_for_this_camera,
                is_known=is_any_plate_known_on_this_camera
            )

            _LOGGER.debug(f"{self.name}: Zakończono aktualizację sensorów rozpoznawania.")
        except Exception as e_sensors:
            _LOGGER.error(f"{self.name}: Krytyczny błąd podczas aktualizacji sensorów rozpoznawania: {e_sensors}", exc_info=True)


    async def _clear_specific_recognized_car_sensor(self, wait_seconds: int):
        """Clear the camera-specific recognized car sensor after a delay."""
        _LOGGER.debug(f"{self.name}: Oczekiwanie {wait_seconds}s przed czyszczeniem sensora '{self._camera_specific_recognized_sensor_id}'.")
        await asyncio.sleep(wait_seconds)
        current_sensor_state = self.hass.states.get(self._camera_specific_recognized_sensor_id)
        # Wyczyść tylko jeśli nadal nie jest "Brak danych" (lub podobnym stanem spoczynku)
        # aby uniknąć nadpisania nowego, ważnego stanu, który mógł pojawić się w międzyczasie.
        if current_sensor_state and current_sensor_state.state not in ["Brak danych", "Brak tablic na obrazie", "Błąd API lub brak danych"]:
            _LOGGER.info(f"{self.name}: Czyszczenie sensora '{self._camera_specific_recognized_sensor_id}' po {wait_seconds}s.")
            self.hass.states.async_set(
                self._camera_specific_recognized_sensor_id,
                "Brak danych", # Ustaw na neutralny stan "Brak danych"
                {"friendly_name": f"Rozpoznany samochód ({self._camera_friendly_name})"} # Zachowaj przyjazną nazwę
            )
        else:
            _LOGGER.debug(f"{self.name}: Pominięto czyszczenie sensora '{self._camera_specific_recognized_sensor_id}', stan to '{current_sensor_state.state if current_sensor_state else 'nie istnieje'}'.")


    async def _update_known_plate_binary_sensor(self, detected_plates_list: list):
        """Update the binary sensor for known plate detection based on the provided list of detected plates."""
        _LOGGER.debug(f"{self.name}: Rozpoczynanie aktualizacji sensora binarnego '{self._detect_known_plate_sensor_id}'. Wykryte tablice: {detected_plates_list}")
        try:
            sensor_state = self.hass.states.get(self._detect_known_plate_sensor_id)
            if not sensor_state:
                _LOGGER.warning(f"{self.name}: Sensor binarny {self._detect_known_plate_sensor_id} nie znaleziony, nie można zaktualizować.")
                return

            is_known_detected_here = False
            if detected_plates_list: # Sprawdź, czy lista nie jest pusta
                for plate_text in detected_plates_list:
                    if await self._plate_manager.async_is_plate_recognized(plate_text, self._tolerate_one_mistake):
                        _LOGGER.debug(f"{self.name}: Wykryto ZNANĄ tablicę '{plate_text}' dla sensora binarnego.")
                        is_known_detected_here = True
                        break # Wystarczy jedna znana tablica, aby sensor był 'on'
                    else:
                        _LOGGER.debug(f"{self.name}: Wykryto NIEZNANĄ tablicę '{plate_text}' dla sensora binarnego.")


            new_state_str = "on" if is_known_detected_here else "off"
            current_ha_state_str = sensor_state.state

            if current_ha_state_str != new_state_str:
                _LOGGER.info(f"{self.name}: Aktualizacja stanu sensora binarnego '{self._detect_known_plate_sensor_id}' z '{current_ha_state_str}' na: '{new_state_str}'")
                self.hass.states.async_set(self._detect_known_plate_sensor_id, new_state_str, {
                    "friendly_name": f"Wykrycie znanej tablicy ({self._camera_friendly_name})",
                    "device_class": "motion" # Utrzymaj device_class
                })
            else:
                _LOGGER.debug(f"{self.name}: Stan sensora binarnego '{self._detect_known_plate_sensor_id}' bez zmian ('{current_ha_state_str}').")


            # Jeśli wykryto znaną tablicę (stan 'on'), zaplanuj wyłączenie sensora binarnego po chwili
            if is_known_detected_here:
                _LOGGER.debug(f"{self.name}: Planowanie automatycznego wyłączenia sensora binarnego '{self._detect_known_plate_sensor_id}' po opóźnieniu (bo stan to 'on').")
                async def clear_binary_sensor_after_delay():
                    await asyncio.sleep(10) # Czas w sekundach, po którym sensor wróci do 'off'
                    sensor_state_before_clear = self.hass.states.get(self._detect_known_plate_sensor_id)
                    # Wyłącz tylko jeśli nadal jest 'on' (nie został wyłączony przez kolejne rozpoznanie bez znanych tablic)
                    if sensor_state_before_clear and sensor_state_before_clear.state == "on":
                        _LOGGER.info(f"{self.name}: Automatyczne czyszczenie (wyłączenie) sensora binarnego '{self._detect_known_plate_sensor_id}' po opóźnieniu.")
                        self.hass.states.async_set(self._detect_known_plate_sensor_id, "off", {
                            "friendly_name": f"Wykrycie znanej tablicy ({self._camera_friendly_name})", # Zachowaj atrybuty
                            "device_class": "motion"
                        })
                    else:
                        _LOGGER.debug(f"{self.name}: Pominięto automatyczne czyszczenie sensora binarnego '{self._detect_known_plate_sensor_id}', stan to '{sensor_state_before_clear.state if sensor_state_before_clear else 'nie istnieje'}'.")

                self.hass.async_create_task(clear_binary_sensor_after_delay())

        except Exception as e_binary:
            _LOGGER.error(f"{self.name}: Krytyczny błąd podczas aktualizacji binarnego sensora wykrycia znanej tablicy: {e_binary}", exc_info=True)

    @staticmethod
    def _levenshtein_distance(s1: str, s2: str) -> int: # Dodano typy dla przejrzystości
        """Oblicza odległość Levenshteina między dwoma ciągami znaków."""
        if not isinstance(s1, str) or not isinstance(s2, str):
            _LOGGER.warning(f"Błędne typy dla _levenshtein_distance: s1='{s1}' (typ: {type(s1)}), s2='{s2}' (typ: {type(s2)})")
            return float('inf') # Zwróć dużą wartość, aby wskazać błąd/niezgodność

        if len(s1) < len(s2):
            return EnhancedPlateRecognizer._levenshtein_distance(s2, s1) # Zamień, aby s1 był dłuższy lub równy

        # len(s2) == 0; jeśli s2 jest pusty, odległość to długość s1
        if len(s2) == 0:
            return len(s1)

        previous_row = list(range(len(s2) + 1)) # Użyj list() dla Pythona 3

        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row

        return previous_row[-1]