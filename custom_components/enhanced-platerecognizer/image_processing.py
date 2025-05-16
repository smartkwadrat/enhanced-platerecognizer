"""Enhanced PlateRecognizer image_processing platform."""
import asyncio
import datetime
import io
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
    CONF_SAVE_FILE_FOLDER,
    CONF_SAVE_TIMESTAMPED_FILE,
    CONF_ALWAYS_SAVE_LATEST_FILE,
    CONF_MAX_IMAGES,
    CONF_TOLERATE_ONE_MISTAKE,
    SERVICE_CLEAN_IMAGES,
)

_LOGGER = logging.getLogger(__name__)

PLATE_READER_URL = "https://api.platerecognizer.com/v1/plate-reader/"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Enhanced PlateRecognizer from a config entry."""
    config = entry.data
    options = entry.options
    
    # Ustalamy stałą ścieżkę do katalogu Tablice
    save_file_folder = os.path.join(hass.config.path(), "www", "Tablice")

    # Sprawdzamy czy katalog istnieje - poprawione wcięcia
    if not os.path.isdir(save_file_folder):
        try:
            os.makedirs(save_file_folder, exist_ok=True)
            _LOGGER.info("Created directory: %s", save_file_folder)
        except OSError as err:
            _LOGGER.warning("Failed to create directory %s: %s", save_file_folder, err)

    camera_entity = config[CONF_SOURCE]
    api_key = config[CONF_API_KEY]
    name = config.get(CONF_NAME, f"Enhanced PlateRecognizer {camera_entity}")

    region = options.get(CONF_REGION, config.get(CONF_REGION))
    # Nie nadpisujemy save_file_folder z konfiguracji - używamy ustalonej wcześniej ścieżki
    save_timestamped_file = options.get(
        CONF_SAVE_TIMESTAMPED_FILE, config.get(CONF_SAVE_TIMESTAMPED_FILE, True)
    )
    always_save_latest_file = options.get(
        CONF_ALWAYS_SAVE_LATEST_FILE, config.get(CONF_ALWAYS_SAVE_LATEST_FILE, True)
    )
    consecutive_captures = options.get(
        CONF_CONSECUTIVE_CAPTURES, config.get(CONF_CONSECUTIVE_CAPTURES, 1)
    )
    capture_interval = options.get(
        CONF_CAPTURE_INTERVAL, config.get(CONF_CAPTURE_INTERVAL, 1.2)
    )
    max_images = options.get(
        CONF_MAX_IMAGES, config.get(CONF_MAX_IMAGES, 10)
    )
    tolerate_one_mistake = options.get(
        CONF_TOLERATE_ONE_MISTAKE, config.get(CONF_TOLERATE_ONE_MISTAKE, False)
    )

    # Usuń ten blok, ponieważ już sprawdziliśmy i utworzyliśmy katalog wyżej
    # Nie powinniśmy go ponownie sprawdzać

    plate_manager = hass.data[DOMAIN]["plate_manager"]

    entity = EnhancedPlateRecognizer(
        hass,
        camera_entity,
        name,
        api_key,
        region,
        save_file_folder,  # Przekazujemy stałą ścieżkę
        save_timestamped_file,
        always_save_latest_file,
        consecutive_captures,
        capture_interval,
        max_images,
        plate_manager,
        tolerate_one_mistake,
    )

    async_add_entities([entity])


class EnhancedPlateRecognizer(ImageProcessingEntity):
    """Representation of an Enhanced PlateRecognizer entity."""

    def __init__(
        self,
        hass,
        camera_entity,
        name,
        api_key,
        region,
        save_file_folder,
        save_timestamped_file,
        always_save_latest_file,
        consecutive_captures,
        capture_interval,
        max_images,
        plate_manager,
        tolerate_one_mistake,
    ):
        super().__init__()
        self.hass = hass
        self._camera = camera_entity
        self._name = name
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

        self._attr_unit_of_measurement = "plate"
        self._vehicles = []
        self._statistics = None
        self._last_detection = None
        self._orientation = []
        self._processing = False
        self._state = 0
        self._regions = [region] if region else None

        # Binary sensor for known plate detection
        self._detect_known_plate_sensor = (
            f"binary_sensor.{self._name.lower().replace(' ', '_').replace('.', '_')}_known_plate_detected"
        )

    @property
    def camera_entity(self):
        return self._camera

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        attr = {
            "vehicles": self._vehicles,
            "orientation": self._orientation,
            "unit_of_measurement": self._attr_unit_of_measurement,
        }
        if self._regions:
            attr["regions"] = self._regions
        if self._save_file_folder:
            attr["save_file_folder"] = self._save_file_folder
            attr["save_timestamped_file"] = self._save_timestamped_file
            attr["always_save_latest_file"] = self._always_save_latest_file
        if self._statistics:
            attr["statistics"] = self._statistics
        if self._last_detection:
            attr["last_detection"] = self._last_detection
        return attr

    async def async_process_image(self, image):
        response = await self._process_plate_recognition(image)
        if response:
            self._update_attributes(response)
            # Save image if configured
            if self._save_file_folder and (self._save_timestamped_file or self._always_save_latest_file):
                await self._save_image(image)
                # Clean old images
                if self._max_images > 0:
                    self.hass.async_create_task(
                        self.hass.services.async_call(
                            DOMAIN,
                            SERVICE_CLEAN_IMAGES,
                            {
                                "folder": self._save_file_folder,
                                "max_images": self._max_images
                            }
                        )
                    )
            # Update entity state
            self.async_schedule_update_ha_state()
            # Update sensors for recognized plates
            await self._update_recognition_sensors(response)
            # Update binary sensor for known plate
            plates = [res.get("plate", "").upper() for res in response.get("results", [])]
            await self._update_known_plate_sensor(plates)
        return response

    async def async_scan_and_process(self, service=None):
        if self._processing:
            _LOGGER.warning("Already processing, skipping request.")
            return
        self._processing = True
        try:
            for i in range(self._consecutive_captures):
                if i > 0:
                    await asyncio.sleep(self._capture_interval)
                camera = self.hass.components.camera
                image = await camera.async_get_image(self._camera)
                await self.async_process_image(image.content)
        finally:
            self._processing = False

    async def _process_plate_recognition(self, image):
        headers = {"Authorization": f"Token {self._api_key}"}
        data = {"regions": self._region if self._region else ""}
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                form = aiohttp.FormData()
                form.add_field("upload", image, filename="image.jpg", content_type="image/jpeg")
                if self._region:
                    form.add_field("regions", self._region)
                async with session.post(
                    PLATE_READER_URL, headers=headers, data=form
                ) as resp:
                    return await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as err:
            _LOGGER.error("API call error: %s", err)
        return None

    def _update_attributes(self, response):
        results = response.get("results", [])
        self._state = len(results)
        vehicles = []
        orientation = []
        for res in results:
            if "vehicle" in res and "type" in res["vehicle"]:
                vehicles.append({
                    "type": res["vehicle"]["type"],
                    "plate": res.get("plate", "")
                })
            else:
                vehicles.append({
                    "type": "unknown",
                    "plate": res.get("plate", "")
                })
            if "orientation" in res and "angle" in res["orientation"]:
                orientation.append(res["orientation"]["angle"])
            else:
                orientation.append(None)
        self._vehicles = vehicles
        self._orientation = orientation
        now = datetime.datetime.now()
        self._last_detection = now.strftime("%Y-%m-%d_%H-%M-%S")
        if "usage" in response:
            usage = response["usage"]
            statistics = {
                "total_calls": usage.get("total_calls"),
                "usage": {
                    "year": usage.get("year"),
                    "month": usage.get("month"),
                    "resets_on": usage.get("resets_on"),
                    "calls": usage.get("calls"),
                },
                "calls_remaining": usage.get("calls_remaining"),
            }
            self._statistics = statistics

    async def _save_image(self, image):
        if not self._save_file_folder:
            return
        timestamp_suffix = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = self._name.replace(" ", "_").replace(".", "_")
        latest_filename = f"{safe_name}_latest.jpg"
        latest_path = os.path.join(self._save_file_folder, latest_filename)
        if self._save_timestamped_file:
            timestamp_filename = f"{safe_name}_{timestamp_suffix}.jpg"
            timestamp_path = os.path.join(self._save_file_folder, timestamp_filename)
            await self.hass.async_add_executor_job(_write_image, timestamp_path, image)
        if self._always_save_latest_file:
            await self.hass.async_add_executor_job(_write_image, latest_path, image)

    async def _update_recognition_sensors(self, response):
        results = response.get("results", [])
        if not results:
            return
        plates = [result.get("plate", "").upper() for result in results]
        if plates:
            plates_str = ", ".join(plates)
            self.hass.states.async_set(
                "sensor.last_recognized_car", plates_str,
                {"friendly_name": "Ostatnio rozpoznane tablice"}
            )
            recognized_plates = []
            for plate in plates:
                if self._plate_manager.is_plate_recognized(plate):
                    recognized_plates.append(plate)
            if recognized_plates:
                message = f"Rozpoznane tablice {recognized_plates[0]} znajdują się na liście"
                if len(recognized_plates) > 1:
                    message += f" (oraz {len(recognized_plates) - 1} innych)"
            else:
                message = f"Nie rozpoznano tablic: {', '.join(plates)}"
            self.hass.states.async_set(
                "sensor.recognized_car", message,
                {"friendly_name": "Rozpoznany samochód"}
            )
            async def clear_recognized_car(wait):
                await asyncio.sleep(wait)
                self.hass.states.async_set(
                    "sensor.recognized_car", "",
                    {"friendly_name": "Rozpoznany samochód"}
                )
            self.hass.async_create_task(clear_recognized_car(10))

    async def _update_known_plate_sensor(self, detected_plates):
        known_plates = set(self._plate_manager.get_plates().keys())
        detected = False
        for plate in detected_plates:
            if plate in known_plates:
                detected = True
                break
            if self._tolerate_one_mistake:
                for known in known_plates:
                    if self._levenshtein_distance(plate, known) == 1:
                        detected = True
                        break
            if detected:
                break
        state = "wykryto" if detected else "brak"
        self.hass.states.async_set(self._detect_known_plate_sensor, state, {
            "friendly_name": "Wykrycie znanej tablicy"
        })
        if detected:
            async def clear_sensor():
                await asyncio.sleep(5)
                self.hass.states.async_set(self._detect_known_plate_sensor, "brak", {
                    "friendly_name": "Wykrycie znanej tablicy"
                })
            self.hass.async_create_task(clear_sensor())

    @staticmethod
    def _levenshtein_distance(s1, s2):
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

def _write_image(path, image):
    with open(path, "wb") as file:
        file.write(image)
