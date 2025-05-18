"""Enhanced PlateRecognizer image_processing platform."""

import asyncio
import datetime
import logging
import os
import aiohttp

from homeassistant.components.image_processing import ImageProcessingEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo

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
    CONF_CAMERAS_CONFIG,
    CONF_CAMERA_ENTITY_ID,
    CONF_CAMERA_FRIENDLY_NAME,
)

_LOGGER = logging.getLogger(__name__)

PLATE_READER_URL = "https://api.platerecognizer.com/v1/plate-reader/"

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up Enhanced PlateRecognizer from a config entry for multiple cameras."""
    entry_config = hass.data[DOMAIN].get(entry.entry_id)
    if not entry_config:
        _LOGGER.error(f"Config for entry {entry.entry_id} not found in hass.data. Cannot setup image processing entities.")
        return

    plate_manager = hass.data[DOMAIN].get("plate_manager")
    global_manager = hass.data[DOMAIN].get("global_recognition_manager")

    if not plate_manager or not global_manager:
        _LOGGER.error("PlateManager or GlobalRecognitionManager not found in hass.data. Critical for setup.")
        return

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

        api_key = entry_config.get(CONF_API_KEY)
        if not api_key:
            _LOGGER.error(f"API Key not found for camera {camera_friendly_name}. Skipping this camera.")
            continue

        region = entry_config.get(CONF_REGION, "pl")
        save_timestamped_file = entry_config.get(CONF_SAVE_TIMESTAMPED_FILE, True)
        always_save_latest_file = entry_config.get(CONF_ALWAYS_SAVE_LATEST_FILE, True)
        consecutive_captures = entry_config.get(CONF_CONSECUTIVE_CAPTURES, 1)
        capture_interval = entry_config.get(CONF_CAPTURE_INTERVAL, 1.2)
        max_images = entry_config.get(CONF_MAX_IMAGES, 10)
        tolerate_one_mistake = entry_config.get(CONF_TOLERATE_ONE_MISTAKE, False)
        specific_save_folder = save_file_folder_base

        entity = EnhancedPlateRecognizer(
            hass=hass,
            config_entry=entry,
            config_entry_id=entry.entry_id,
            camera_entity_id=camera_entity_id,
            camera_friendly_name=camera_friendly_name,
            api_key=api_key,
            region=region,
            save_file_folder=specific_save_folder,
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
        sensor_id = global_manager.get_camera_specific_sensor_id(camera_friendly_name)
        if not hass.states.get(sensor_id):
            hass.states.async_set(
                sensor_id, "Brak danych",
                {"friendly_name": f"Rozpoznany samochód ({camera_friendly_name})"}
            )
            _LOGGER.debug(f"Created camera-specific sensor: {sensor_id}")

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
        config_entry: ConfigEntry,
        config_entry_id: str,
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
        plate_manager,
        tolerate_one_mistake: bool,
        global_manager
    ):
        super().__init__()
        self.hass = hass
        self._config_entry = config_entry
        self._config_entry_id = config_entry_id
        self._camera_entity_id = camera_entity_id
        self._camera_friendly_name = camera_friendly_name
        self._attr_name = f"PlateRecognizer {self._camera_friendly_name}"
        self._attr_unique_id = f"{DOMAIN}_{self._camera_entity_id.replace('.', '_')}_{config_entry_id}"

        self._api_key = self._config_entry.data.get(CONF_API_KEY)
        self._region = self._config_entry.options.get(CONF_REGION, self._config_entry.data.get(CONF_REGION, "pl"))
        self._save_file_folder = save_file_folder
        self._save_timestamped_file = save_timestamped_file
        self._always_save_latest_file = always_save_latest_file
        self._consecutive_captures = consecutive_captures
        self._capture_interval = capture_interval
        self._max_images = max_images
        self._plate_manager = plate_manager
        self._tolerate_one_mistake = tolerate_one_mistake
        self._global_manager = global_manager

        self._attr_unit_of_measurement = "plates"
        self._vehicles = []
        self._statistics = None
        self._last_detection = None
        self._orientation = []
        self._processing = False
        self._attr_state = 0
        self._regions_for_api = [region] if region else None

        self._camera_specific_recognized_sensor_id = self._global_manager.get_camera_specific_sensor_id(self._camera_friendly_name)
        sane_binary_sensor_base_id = self._attr_unique_id.replace(f"{DOMAIN}_", "")
        self._detect_known_plate_sensor_id = f"binary_sensor.{DOMAIN}_{sane_binary_sensor_base_id}_known_plate_detected"

        manifest = hass.integration_manifests.get(DOMAIN)
        sw_version = manifest.version if manifest else "N/A"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"platerecognizer_{self._config_entry_id}")},
            name=self._config_entry.title,
            manufacturer="SmartKwadrat (Custom Integration)",
            model="Enhanced PlateRecognizer",
            sw_version=sw_version,
        )
        _LOGGER.info(f"Initialized EnhancedPlateRecognizer: {self.name} (UID: {self.unique_id}) for camera: {self._camera_entity_id}")

    @property
    def camera_entity(self):
        """Return the camera entity id."""
        return self._camera_entity_id

    @property
    def extra_state_attributes(self):
        attr = {
            "vehicles": self._vehicles,
            "orientation": self._orientation,
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
            attr["api_statistics"] = self._statistics
        if self._last_detection:
            attr["last_detection_timestamp"] = self._last_detection
        return attr

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if not self.hass.states.get(self._detect_known_plate_sensor_id):
            self.hass.states.async_set(self._detect_known_plate_sensor_id, "brak", {
                "friendly_name": f"Wykrycie znanej tablicy ({self._camera_friendly_name})",
                "device_class": "motion"
            })

    async def async_will_remove_from_hass(self) -> None:
        await super().async_will_remove_from_hass()
        if self._camera_specific_recognized_sensor_id:
            self.hass.states.async_remove(self._camera_specific_recognized_sensor_id)
        if self._global_manager:
            self._global_manager.remove_camera_data(self._camera_friendly_name)
        if self._detect_known_plate_sensor_id:
            self.hass.states.async_remove(self._detect_known_plate_sensor_id)

    async def async_process_image(self, image_bytes: bytes):
        _LOGGER.debug(f"{self.name}: Starting image processing.")
        try:
            response_json = await self._call_plate_recognizer_api(image_bytes)
            if response_json:
                self._update_internal_attributes(response_json)
                if self._save_file_folder and (self._save_timestamped_file or self._always_save_latest_file):
                    await self._save_image_to_disk(image_bytes)
                if self._max_images > 0 and self._save_file_folder:
                    from . import async_clean_old_images
                    self.hass.async_create_task(
                        async_clean_old_images(self.hass, self._save_file_folder, self._max_images)
                    )
                self.async_write_ha_state()
                await self._update_all_recognition_sensors(response_json)
                detected_plates_for_binary_sensor = [res.get("plate", "").upper() for res in response_json.get("results", [])]
                await self._update_known_plate_binary_sensor(detected_plates_for_binary_sensor)
                _LOGGER.debug(f"{self.name}: Image processing finished. State: {self.state}, Plates: {self._vehicles}")
                return response_json
            else:
                _LOGGER.warning(f"{self.name}: No response or error from PlateRecognizer API.")
                self._attr_state = 0
                self._vehicles = []
                self.async_write_ha_state()
                await self._update_all_recognition_sensors(None)
                await self._update_known_plate_binary_sensor([])
        except Exception as e:
            _LOGGER.error(f"{self.name}: Error in async_process_image: {e}", exc_info=True)
            self._attr_state = 0
            self.async_write_ha_state()
        return None

    async def async_scan_and_process(self):
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
        headers = {"Authorization": f"Token {self._api_key}"}
        _LOGGER.debug(f"{self.name}: Calling PlateRecognizer API. Regions: {self._regions_for_api}")
        try:
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                form_data = aiohttp.FormData()
                form_data.add_field("upload", image_bytes, filename="image.jpg", content_type="image/jpeg")
                if self._regions_for_api:
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
        if not response_json or "results" not in response_json:
            self._attr_state = 0
            self._vehicles = []
            self._orientation = []
            return

        results = response_json.get("results", [])
        self._attr_state = len(results)
        current_vehicles = []
        current_orientation = []
        for res_item in results:
            vehicle_info = {"plate": res_item.get("plate", "").upper()}
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
        self._last_detection = datetime.datetime.now().isoformat()
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
        _LOGGER.debug(f"{self.name}: Internal attributes updated. State: {self.state}, Vehicles: {self._vehicles}")

    async def _save_image_to_disk(self, image_bytes: bytes):
        if not self._save_file_folder:
            _LOGGER.debug(f"{self.name}: Save file folder not configured, skipping image save.")
            return
        try:
            timestamp_suffix = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3]
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
        try:
            plates_str_for_report = "Brak"
            message_specific_for_this_camera = "Brak danych"
            is_any_plate_known_on_this_camera = False

            if response_json_or_none and "results" in response_json_or_none:
                results = response_json_or_none.get("results", [])
                detected_plates_on_this_camera = [res.get("plate", "").upper() for res in results]

                if detected_plates_on_this_camera:
                    plates_str_for_report = ", ".join(detected_plates_on_this_camera)
                    recognized_known_plates_here = []
                    for plate_text in detected_plates_on_this_camera:
                        if await self._plate_manager.async_is_plate_recognized(plate_text, self._tolerate_one_mistake):
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
                    elif detected_plates_on_this_camera:
                        message_specific_for_this_camera = f"Wykryto nieznane tablice: {plates_str_for_report}"
                else:
                    message_specific_for_this_camera = "Brak tablic na obrazie"

            if self.hass.states.get(self._camera_specific_recognized_sensor_id):
                self.hass.states.async_set(
                    self._camera_specific_recognized_sensor_id,
                    message_specific_for_this_camera,
                    {"friendly_name": f"Rozpoznany samochód ({self._camera_friendly_name})"}
                )
                if message_specific_for_this_camera != "Brak danych":
                    self.hass.async_create_task(self._clear_specific_recognized_car_sensor(20))
            self._global_manager.report_recognition(
                camera_friendly_name=self._camera_friendly_name,
                plates_str=plates_str_for_report,
                recognized_msg=message_specific_for_this_camera,
                is_known=is_any_plate_known_on_this_camera
            )
            _LOGGER.debug(f"{self.name}: Updated recognition sensors. Specific: '{message_specific_for_this_camera}', Known here: {is_any_plate_known_on_this_camera}")
        except Exception as e_sensors:
            _LOGGER.error(f"{self.name}: Error updating recognition sensors: {e_sensors}", exc_info=True)

    async def _clear_specific_recognized_car_sensor(self, wait_seconds: int):
        await asyncio.sleep(wait_seconds)
        current_sensor_state = self.hass.states.get(self._camera_specific_recognized_sensor_id)
        if current_sensor_state and current_sensor_state.state != "Brak danych":
            self.hass.states.async_set(
                self._camera_specific_recognized_sensor_id,
                "Brak danych",
                {"friendly_name": f"Rozpoznany samochód ({self._camera_friendly_name})"}
            )

    async def _update_known_plate_binary_sensor(self, detected_plates_list: list):
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
            current_state_obj = self.hass.states.get(self._detect_known_plate_sensor_id)
            current_ha_state = current_state_obj.state if current_state_obj else None

            if current_ha_state != new_state:
                self.hass.states.async_set(self._detect_known_plate_sensor_id, new_state, {
                    "friendly_name": f"Wykrycie znanej tablicy ({self._camera_friendly_name})",
                    "device_class": "motion"
                })
                _LOGGER.debug(f"Binary sensor {self._detect_known_plate_sensor_id} updated to: {new_state}")

            if is_known_detected_here:
                async def clear_binary_sensor_after_delay():
                    await asyncio.sleep(10)
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
        if not isinstance(s1, str) or not isinstance(s2, str):
            return float('inf')
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
