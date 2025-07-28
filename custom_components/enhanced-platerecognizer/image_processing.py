"""Vehicle detection using Plate Recognizer cloud service."""
import logging
import requests
import voluptuous as vol
import re
import io
from typing import List, Dict
import json
import asyncio
from homeassistant.core import HomeAssistant

from PIL import Image, ImageDraw, UnidentifiedImageError
from pathlib import Path
import os

from homeassistant.components.image_processing import (
    CONF_ENTITY_ID,
    CONF_NAME,
    CONF_SOURCE,
    PLATFORM_SCHEMA,
    ImageProcessingEntity,
)
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import split_entity_id
import homeassistant.helpers.config_validation as cv
import homeassistant.util.dt as dt_util
from homeassistant.util.pil import draw_box
from datetime import datetime

_LOGGER = logging.getLogger(__name__)

REPEATS = 3      # liczba dodatkowych skanów
DELAY   = 1.2    # bazowe opóźnienie w sekundach

PLATE_READER_URL = "https://api.platerecognizer.com/v1/plate-reader/"
STATS_URL = "https://api.platerecognizer.com/v1/statistics/"

EVENT_VEHICLE_DETECTED = "platerecognizer.vehicle_detected"

ATTR_PLATE = "plate"
ATTR_CONFIDENCE = "confidence"
ATTR_REGION_CODE = "region_code"
ATTR_VEHICLE_TYPE = "vehicle_type"
ATTR_ORIENTATION = "orientation"
ATTR_BOX_Y_CENTRE = "box_y_centre"
ATTR_BOX_X_CENTRE = "box_x_centre"

CONF_API_TOKEN = "api_token"
CONF_REGIONS = "regions"
CONF_SAVE_FILE_FOLDER = "save_file_folder"
CONF_SAVE_TIMESTAMPTED_FILE = "save_timestamped_file"
CONF_ALWAYS_SAVE_LATEST_FILE = "always_save_latest_file"
CONF_WATCHED_PLATES = "watched_plates"
CONF_MMC = "mmc"
CONF_SERVER = "server"
CONF_DETECTION_RULE = "detection_rule"
CONF_REGION_STRICT = "region"

DATETIME_FORMAT = "%Y-%m-%d_%H-%M-%S"
RED = (255, 0, 0)  # For objects within the ROI
DEFAULT_REGIONS = ['None']

CONF_CONSECUTIVE_CAPTURES = "consecutive_captures"
CONF_TOLERATE_ONE_MISTAKE = "tolerate_one_mistake"

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_API_TOKEN): cv.string,
        vol.Optional(CONF_REGIONS, default=DEFAULT_REGIONS): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(CONF_MMC, default=False): cv.boolean,
        vol.Optional(CONF_SAVE_FILE_FOLDER): cv.isdir,
        vol.Optional(CONF_SAVE_TIMESTAMPTED_FILE, default=False): cv.boolean,
        vol.Optional(CONF_ALWAYS_SAVE_LATEST_FILE, default=False): cv.boolean,
        vol.Optional(CONF_WATCHED_PLATES): vol.All(
            cv.ensure_list, [cv.string]
        ),
        vol.Optional(CONF_SERVER, default=PLATE_READER_URL): cv.string,
        vol.Optional(CONF_DETECTION_RULE, default=False): cv.string,
        vol.Optional(CONF_REGION_STRICT, default=False): cv.string,
        vol.Optional(CONF_CONSECUTIVE_CAPTURES, default=False): cv.boolean,
        vol.Optional(CONF_TOLERATE_ONE_MISTAKE, default=True): cv.boolean,
    }
)

def get_plates(results : List[Dict]) -> List[str]:
    """
    Return the list of candidate plates. 
    If no plates empty list returned.
    """
    plates = []
    candidates = [result['candidates'] for result in results]
    for candidate in candidates:
        cand_plates = [cand['plate'] for cand in candidate]
        for plate in cand_plates:
            plates.append(plate)
    return list(set(plates))

def get_orientations(results : List[Dict]) -> List[str]:
    """
    Return the list of candidate orientations. 
    If no orientations empty list returned.
    """
    try:
        orientations = []
        candidates = [result['orientation'] for result in results]
        for candidate in candidates:
            for cand in candidate:
                _LOGGER.debug("get_orientations cand: %s", cand)
                if cand["score"] >= 0.7:
                    orientations.append(cand["orientation"])
        return list(set(orientations))
    except Exception as exc:
        _LOGGER.error("get_orientations error: %s", exc)

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the platform."""
    save_folder = config.get("save_file_folder")
    # 1) Sprawdź najpierw, czy ścieżka jest na liście dozwolonych:
    if save_folder and not hass.config.is_allowed_path(save_folder):
        _LOGGER.error(
            "Ścieżka %r nie jest dozwolona w allowlist_external_dirs – pomijam zapisywanie plików",
            save_folder,
        )
        save_folder = None

    # 2) Jeżeli ścieżka jest OK, utwórz katalog
    if save_folder:
        try:
            Path(save_folder).mkdir(parents=True, exist_ok=True)
            os.chmod(save_folder, 0o755)
        except Exception as e:
            _LOGGER.error("Nie udało się utworzyć folderu %r: %s", save_folder, e)
            save_folder = None
            
    # Przekaż tolerate_one_mistake do hass.data
    domain = "enhanced_platerecognizer"
    if domain not in hass.data:
        hass.data[domain] = {}
    
    hass.data[domain]["tolerate_one_mistake"] = config.get(CONF_TOLERATE_ONE_MISTAKE, True)

    entities = []
    for camera in config[CONF_SOURCE]:
        platerecognizer = PlateRecognizerEntity(
            api_token=config.get(CONF_API_TOKEN),
            regions = config.get(CONF_REGIONS),
            save_file_folder=save_folder,
            save_timestamped_file=config.get(CONF_SAVE_TIMESTAMPTED_FILE),
            always_save_latest_file=config.get(CONF_ALWAYS_SAVE_LATEST_FILE),
            watched_plates=config.get(CONF_WATCHED_PLATES),
            camera_entity=camera[CONF_ENTITY_ID],
            name=camera.get(CONF_NAME),
            mmc=config.get(CONF_MMC),
            server=config.get(CONF_SERVER),
            detection_rule = config.get(CONF_DETECTION_RULE),
            region_strict = config.get(CONF_REGION_STRICT),
            consecutive_captures=config.get(CONF_CONSECUTIVE_CAPTURES, False),

        )
        entities.append(platerecognizer)
    add_entities(entities)


class PlateRecognizerEntity(ImageProcessingEntity):
    """Create entity."""

    def __init__(
        self,
        api_token,
        regions,
        save_file_folder: str,
        save_timestamped_file,
        always_save_latest_file,
        watched_plates,
        camera_entity,
        name,
        mmc,
        server,
        detection_rule,
        region_strict,
        consecutive_captures=False,
    ):
        """Init."""
        self._headers = {"Authorization": f"Token {api_token}"}
        self._regions = regions
        self._camera = camera_entity
        if name:
            self._name = name
        else:
            camera_name = split_entity_id(camera_entity)[1]
            self._name = f"platerecognizer_{camera_name}"
        self._save_file_folder = Path(save_file_folder) if save_file_folder else None
        self._save_timestamped_file = save_timestamped_file
        self._always_save_latest_file = always_save_latest_file
        self._watched_plates = watched_plates
        self._mmc = mmc
        self._server = server
        self._detection_rule = detection_rule
        self._region_strict = region_strict
        self._state = None
        self._results = {}
        self._vehicles = [{}]
        self._orientations = []
        self._plates = []
        self._statistics = {}
        self._last_detection = None
        self._image_width = None
        self._image_height = None
        self._image = None
        self._config = {}
        self.get_statistics()
        self._consecutive_captures = consecutive_captures
        self._processing_additional_captures = False
        self._current_capture_count = 0

    def process_image(self, image):
        """Przetwarza obraz, obsługuje błędy i ZAWSZE wysyła zdarzenie."""
        self._current_capture_count += 1
        
        # Resetowanie stanów na początku
        self._state = None
        self._results = {}
        self._vehicles = [] # ZMIANA: Inicjalizujemy jako pustą listę, a nie listę z pustym słownikiem
        self._plates = []
        self._orientations = []
        
        try:
            self._image = Image.open(io.BytesIO(bytearray(image)))
            self._image_width, self._image_height = self._image.size
        except UnidentifiedImageError:
            _LOGGER.error("Nie udało się otworzyć obrazu. Może być uszkodzony.")
            self._state = "Błąd obrazu"
            # Mimo błędu, wysyłamy zdarzenie - to jest KLUCZOWA ZMIANA
            self.hass.bus.fire('enhanced_platerecognizer_image_processed', {
                'entity_id': self.entity_id,
                'has_vehicles': False,
                'vehicles': [],
                'timestamp': dt_util.now().strftime(DATETIME_FORMAT)
            })
            return # Kończymy działanie tej metody

        if self._regions == DEFAULT_REGIONS:
            regions = None
        else:
            regions = self._regions
        if self._detection_rule:
            self._config.update({"detection_rule": self._detection_rule})
        if self._region_strict:
            self._config.update({"region": self._region_strict})
        
        try:
            _LOGGER.debug("Config: " + str(json.dumps(self._config)))
            response = requests.post(
                self._server,
                data=dict(regions=regions, camera_id=self.name, mmc=self._mmc, config=json.dumps(self._config)),
                files={"upload": image},
                headers=self._headers,
                timeout=10 # Dobrą praktyką jest dodanie timeoutu
            ).json()
            
            self._results = response.get("results", [])
            self._plates = get_plates(self._results)
            if self._mmc:
                self._orientations = get_orientations(self._results)
            
            # Uproszczona i bardziej niezawodna logika tworzenia listy pojazdów
            self._vehicles = [
                {
                    ATTR_PLATE: r["plate"],
                    ATTR_CONFIDENCE: r["score"],
                    ATTR_REGION_CODE: r["region"]["code"],
                    ATTR_VEHICLE_TYPE: r["vehicle"]["type"],
                    ATTR_BOX_Y_CENTRE: (r["box"]["ymin"] + ((r["box"]["ymax"] - r["box"]["ymin"]) / 2)),
                    ATTR_BOX_X_CENTRE: (r["box"]["xmin"] + ((r["box"]["xmax"] - r["box"]["xmin"]) / 2)),
                }
                for r in self._results if "plate" in r
            ]

        except requests.RequestException as exc:
            _LOGGER.error("Błąd połączenia z API Plate Recognizer: %s", exc)
            self._state = "Błąd API"
            self._vehicles = []
        except Exception as exc:
            _LOGGER.error("Nieoczekiwany błąd podczas przetwarzania w Plate Recognizer: %s", exc)
            self._state = "Błąd przetwarzania"
            self._vehicles = []

        current_time = dt_util.now().strftime(DATETIME_FORMAT)
        
        if self._vehicles:
            self._last_detection = current_time
            # Używamy _plates, bo self._vehicles zawiera teraz więcej danych
            self._state = ", ".join(self._plates)
        elif self._state is None: # Jeśli nie było błędu, ale nie ma pojazdów
            self._state = f"no_vehicles_{current_time}"

        _LOGGER.info(f"Wysyłanie eventu 'enhanced_platerecognizer_image_processed' dla {self.entity_id}")
        _LOGGER.debug(f"Event data: entity_id={self.entity_id}, has_vehicles={bool(self._vehicles)}, vehicles_count={len(self._vehicles)}")
        _LOGGER.info(f"Przygotowywanie zdarzenia dla {self.entity_id} z danymi: has_vehicles={bool(self._vehicles)}")

        self.hass.bus.fire('enhanced_platerecognizer_image_processed', {
            'entity_id': self.entity_id,
            'has_vehicles': bool(self._vehicles),
            'vehicles': self._vehicles,
            'timestamp': current_time
        })

        if self._save_file_folder:
            if self._vehicles or self._always_save_latest_file:
                self.save_image()
        
        if self._server == PLATE_READER_URL:
            self.get_statistics()
        elif "usage" in response:
            stats = response["usage"]
            calls_remaining = stats.get("max_calls", 0) - stats.get("calls", 0)
            stats.update({"calls_remaining": calls_remaining})
            self._statistics = stats
        
        if self._consecutive_captures and self._current_capture_count == 1:
            for i in range(1, REPEATS + 1):
                self.hass.create_task(self._schedule_next_scan(DELAY * i))
                
        if self._current_capture_count >= REPEATS + 1:
            self._current_capture_count = 0

    async def _schedule_next_scan(self, delay):
        """Zaplanuj następne skanowanie po określonym opóźnieniu."""
        await asyncio.sleep(delay)
        await self.hass.services.async_call(
            "image_processing", 
            "scan", 
            {"entity_id": self.entity_id}
        )
        # Reset flagi po ostatnim skanowaniu
        if self._current_capture_count >= 3:
            self._current_capture_count = 0
            self._processing_additional_captures = False

    def get_statistics(self):
        try:
            response = requests.get(STATS_URL, headers=self._headers).json()
            calls_remaining = response["total_calls"] - response["usage"]["calls"]
            response.update({"calls_remaining": calls_remaining})
            self._statistics = response.copy()
        except Exception as exc:
            _LOGGER.error("platerecognizer error getting statistics: %s", exc)

    def fire_vehicle_detected_event(self, vehicle):
        """Send event."""
        vehicle_copy = vehicle.copy()
        vehicle_copy.update({ATTR_ENTITY_ID: self.entity_id})
        self.hass.bus.fire(EVENT_VEHICLE_DETECTED, vehicle_copy)

    def save_image(self):
        """Save a timestamped image with bounding boxes around plates."""
        draw = ImageDraw.Draw(self._image)

        decimal_places = 3
        for vehicle in self._results:
            box = (
                    round(vehicle['box']["ymin"] / self._image_height, decimal_places),
                    round(vehicle['box']["xmin"] / self._image_width, decimal_places),
                    round(vehicle['box']["ymax"] / self._image_height, decimal_places),
                    round(vehicle['box']["xmax"] / self._image_width, decimal_places),
            )
            text = vehicle['plate']
            draw_box(
                draw,
                box,
                self._image_width,
                self._image_height,
                text=text,
                color=RED,
                )

        latest_save_path = self._save_file_folder / f"{self._name}_latest.png"
        self._image.save(latest_save_path)

        if self._save_timestamped_file:
            timestamp_save_path = self._save_file_folder / f"{self._name}_{self._last_detection}.png"
            self._image.save(timestamp_save_path)
            _LOGGER.info("platerecognizer saved file %s", timestamp_save_path)

    @property
    def camera_entity(self):
        """Return camera entity id from process pictures."""
        return self._camera

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def should_poll(self):
        """Return the polling state."""
        return False

    @property
    def state(self):
        """Return the state of the entity."""
        return self._state

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return ATTR_PLATE

    @property
    def extra_state_attributes(self):
        """Return the attributes."""
        attr = {}
        attr.update({"last_detection": self._last_detection})
        attr.update({"vehicles": self._vehicles})
        attr.update({ATTR_ORIENTATION: self._orientations})
        if self._watched_plates:
            watched_plates_results = {plate : False for plate in self._watched_plates}
            for plate in self._watched_plates:
                if plate in self._plates:
                    watched_plates_results.update({plate: True})
            attr[CONF_WATCHED_PLATES] = watched_plates_results
        attr.update({"statistics": self._statistics})
        if self._regions != DEFAULT_REGIONS:
            attr[CONF_REGIONS] = self._regions
        if self._server != PLATE_READER_URL:
            attr[CONF_SERVER] = str(self._server)
        if self._save_file_folder:
            attr[CONF_SAVE_FILE_FOLDER] = str(self._save_file_folder)
            attr[CONF_SAVE_TIMESTAMPTED_FILE] = self._save_timestamped_file
            attr[CONF_ALWAYS_SAVE_LATEST_FILE] = self._always_save_latest_file
        return attr
