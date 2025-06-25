"""Sensory dla Enhanced Plate Recognizer."""

import logging
import asyncio
from typing import Any, Dict, List

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

_LOGGER = logging.getLogger(__name__)

DOMAIN = "enhanced_platerecognizer"

async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the sensor platform."""
    _LOGGER.info("Enhanced Plate Recognizer: async_setup_platform called!")
    
    # SPRAWDŹ WSZYSTKIE ENCJE IMAGE_PROCESSING:
    all_entities = hass.states.async_entity_ids('image_processing')
    _LOGGER.info(f"Wszystkie encje image_processing: {all_entities}")
    
    # Znajdź encje z naszej integracji
    image_processing_entities = []
    for entity_id in all_entities:
        if 'platerecognizer' in entity_id:
            image_processing_entities.append(entity_id)
            _LOGGER.info(f"Znaleziono encję platerecognizer: {entity_id}")
    
    _LOGGER.info(f"Encje do mapowania: {image_processing_entities}")
    
    # SPRAWDŹ CZY PLATEMANAGER JEST DOSTĘPNY
    plate_manager = hass.data.get(DOMAIN, {}).get('plate_manager')
    if plate_manager:
        _LOGGER.info("PlateManager jest dostępny w hass.data")
    else:
        _LOGGER.error("PlateManager NIE JEST dostępny w hass.data!")
    
    sensors = []
    
    # Tworzenie sensorów dla każdej kamery
    for i, entity_id in enumerate(image_processing_entities, 1):
        _LOGGER.info(f"Tworzę sensory dla encji {entity_id} (kamera {i})")
        
        # Sensor dla konkretnej kamery
        kamera_sensor = RozpoznaneTablesKameraSensor(hass, entity_id, i)
        sensors.append(kamera_sensor)
        _LOGGER.info(f"Utworzono sensor: {kamera_sensor.entity_id} -> nasłuchuje: {entity_id}")
        
        # Wyciągnij nazwę kamery dla PlateRecognitionSensor
        #camera_entity = f"camera.{entity_id.split('.')[-1].replace('platerecognizer_', '')}"
        #last_detection_sensor = PlateRecognitionSensor(hass, entity_id, camera_entity)
        #sensors.append(last_detection_sensor)
        #_LOGGER.info(f"Utworzono sensor: {last_detection_sensor._attr_unique_id} -> nasłuchuje: {entity_id}")
    
    # Combined sensor
    if image_processing_entities:
        combined_sensor = CombinedPlatesSensor(hass, image_processing_entities)
        sensors.append(combined_sensor)
        _LOGGER.info(f"Utworzono combined sensor -> nasłuchuje: {image_processing_entities}")
    else:
        _LOGGER.warning("Brak encji image_processing - nie tworzę combined sensor")
    
    # Inne sensory
    additional_sensors = [
        LastRecognizedCarSensor(hass),
        RecognizedCarSensor(hass),
        FormattedCarPlatesSensor(hass)
    ]
    sensors.extend(additional_sensors)
    
    _LOGGER.info(f"Utworzono łącznie {len(sensors)} sensorów")
    for sensor in sensors:
        sensor_id = getattr(sensor, 'entity_id', getattr(sensor, '_attr_unique_id', 'unknown'))
        _LOGGER.info(f"Sensor do dodania: {sensor_id}")
    
    async_add_entities(sensors, True)


class RozpoznaneTablesKameraSensor(SensorEntity):
    """Sensor rozpoznane_tablice_kamera_X (zgodny z template)."""

    def __init__(self, hass: HomeAssistant, image_processing_entity: str, kamera_nr: int):
        self.hass = hass
        self._image_processing_entity = image_processing_entity
        self._attr_name = f"Rozpoznane Tablice Kamera {kamera_nr}"
        self._attr_unique_id = f"rozpoznane_tablice_kamera_{kamera_nr}"
        self.entity_id = f"sensor.rozpoznane_tablice_kamera_{kamera_nr}"
        self._attr_state = "Nie wykryto tablic"

    async def async_added_to_hass(self):
        _LOGGER.info(f"Sensor {self.entity_id}: inicjalizacja rozpoczęta")
        
        # Nasłuchuj zmian stanu encji (backup)
        async_track_state_change_event(
            self.hass,
            self._image_processing_entity,
            self._handle_state_change
        )
        _LOGGER.info(f"Sensor {self.entity_id}: zarejestrowano nasłuchiwanie zmian stanu dla {self._image_processing_entity}")
        
        # Nasłuchuj specjalnego eventu (główny mechanizm)
        self.hass.bus.async_listen(
            'enhanced_platerecognizer_image_processed', 
            self._handle_image_processed
        )
        _LOGGER.info(f"Sensor {self.entity_id}: zarejestrowano nasłuchiwanie eventu enhanced_platerecognizer_image_processed")
        
        # od razu pokaż stan domyślny zamiast "unknown"
        self.async_write_ha_state()
        self.hass.async_create_task(self._delayed_update())
        _LOGGER.info(f"Sensor {self.entity_id}: inicjalizacja zakończona")

    async def _delayed_update(self):
        await asyncio.sleep(5)
        _LOGGER.info(f"Sensor {self.entity_id}: wykonuję delayed update")
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu encji image_processing (backup mechanism)."""
        _LOGGER.info(f"Sensor {self.entity_id}: otrzymał zmianę stanu (backup)")
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_image_processed(self, event):
        """Obsłuż zdarzenie przetworzenia obrazu."""
        event_entity = event.data.get('entity_id')
        _LOGGER.info(f"Sensor {self.entity_id}: otrzymał event od {event_entity}, oczekuje od {self._image_processing_entity}")
        
        if event_entity == self._image_processing_entity:
            _LOGGER.info(f"Sensor {self.entity_id}: event pasuje, przetwarzam dane")
            
            # Wykorzystaj dane bezpośrednio z eventu
            if event.data.get('has_vehicles'):
                vehicles = event.data.get('vehicles', [])
                plates = [v.get('plate') for v in vehicles if v.get('plate') is not None]
                plates_str = ', '.join(plates) if plates else 'Nie wykryto tablic'
                _LOGGER.info(f"Sensor {self.entity_id}: znaleziono tablice: {plates_str}")
            else:
                plates_str = 'Nie wykryto tablic'
                _LOGGER.info(f"Sensor {self.entity_id}: brak pojazdów")
            
            timestamp = event.data.get('timestamp', '').strip()
            if timestamp:
                new_state = f"{plates_str} @ {timestamp}"
            else:
                new_state = plates_str
            
            # KLUCZOWE: Sprawdź czy stan się rzeczywiście zmienia
            if self._attr_state != new_state:
                self._attr_state = new_state
                _LOGGER.info(f"Sensor {self.entity_id}: ZMIENIAM stan z '{getattr(self, '_attr_state', 'unknown')}' na '{new_state}'")
            else:
                _LOGGER.info(f"Sensor {self.entity_id}: stan pozostaje bez zmian: '{new_state}'")
                
            # DODAJ atrybuty dla debugowania
            self._attr_extra_state_attributes = {
                'last_update': timestamp,
                'vehicles_count': len(event.data.get('vehicles', [])),
                'plates_count': len([v.get('plate') for v in event.data.get('vehicles', []) if v.get('plate') is not None]),
                'event_entity': event_entity
            }
            
            # Force update
            self.async_write_ha_state()
            _LOGGER.info(f"Sensor {self.entity_id}: async_write_ha_state() wywołane")
        else:
            _LOGGER.debug(f"Sensor {self.entity_id}: event od innej encji, ignoruję")

    # DODAJ właściwość state
    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_state

    @property
    def should_poll(self):
        """No polling needed."""
        return False

    def _update_state(self):
        """Aktualizuj stan na podstawie aktualnego stanu encji (backup method)."""
        _LOGGER.debug(f"Sensor {self.entity_id}: _update_state wywołane")
        image_processing = self.hass.states.get(self._image_processing_entity)
        if not image_processing or image_processing.state in ["unavailable", "unknown"]:
            self._attr_state = "Kamera niedostępna"
            _LOGGER.warning(f"Sensor {self.entity_id}: encja {self._image_processing_entity} niedostępna")
            return

        vehicles = image_processing.attributes.get('vehicles', [])
        last_detection = image_processing.attributes.get('last_detection', '')

        if vehicles:
            plates = [v.get('plate') for v in vehicles if v.get('plate') is not None]
            plates_str = ', '.join(plates) if plates else 'Nie wykryto tablic'
        else:
            plates_str = 'Nie wykryto tablic'

        if last_detection:
            self._attr_state = f"{plates_str} @ {last_detection}"
        else:
            self._attr_state = plates_str
            
        _LOGGER.debug(f"Sensor {self.entity_id}: backup update - nowy stan: {self._attr_state}")
    
    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_state

    @property
    def should_poll(self):
        """No polling needed."""
        return False


class FormattedCarPlatesSensor(SensorEntity):
    """Sensor z listą znanych tablic z właścicielami."""
    
    def __init__(self, hass: HomeAssistant):
        """Inicjalizuj sensor."""
        self.hass = hass
        self._attr_name = "Formatted Car Plates"
        self._attr_unique_id = "formatted_car_plates"
        self._attr_state = "Znane tablice rejestracyjne"
        self._attr_extra_state_attributes = {}
    
    async def async_added_to_hass(self):
        """Gdy sensor zostanie dodany do HA."""
        _LOGGER.info(f"Sensor {self._attr_unique_id}: inicjalizacja rozpoczęta")
        
        # Sprawdź dostępność PlateManager
        plate_manager = self.hass.data.get(DOMAIN, {}).get('plate_manager')
        if plate_manager:
            _LOGGER.info(f"Sensor {self._attr_unique_id}: PlateManager jest dostępny")
        else:
            _LOGGER.error(f"Sensor {self._attr_unique_id}: PlateManager NIE JEST dostępny!")
        
        # Nasłuchuj zmian w PlateManager poprzez eventy
        self.hass.bus.async_listen('enhanced_platerecognizer_plate_added', self._handle_plate_change)
        self.hass.bus.async_listen('enhanced_platerecognizer_plate_removed', self._handle_plate_change)
        _LOGGER.info(f"Sensor {self._attr_unique_id}: zarejestrowano nasłuchiwanie eventów PlateManager")
        
        # Nasłuchuj też zmian w input_select dla backup
        async_track_state_change_event(
            self.hass,
            'input_select.remove_plate',
            self._handle_state_change
        )
        
        self._update_attributes()
        self.async_write_ha_state()
        _LOGGER.info(f"Sensor {self._attr_unique_id}: inicjalizacja zakończona")

    @callback
    def _handle_plate_change(self, event):
        """Obsłuż zmianę tablic przez PlateManager."""
        _LOGGER.info(f"Sensor {self._attr_unique_id}: otrzymał event zmiany tablic")
        self._update_attributes()
        self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu input_select (backup)."""
        _LOGGER.info(f"Sensor {self._attr_unique_id}: otrzymał zmianę stanu input_select")
        self._update_attributes()
        self.async_write_ha_state()

    def _update_attributes(self):
        """Zaktualizuj atrybuty z tablicami i właścicielami."""
        _LOGGER.debug(f"Sensor {self._attr_unique_id}: _update_attributes wywołane")
        
        plate_manager = self.hass.data.get(DOMAIN, {}).get('plate_manager')
        if plate_manager:
            _LOGGER.debug(f"Sensor {self._attr_unique_id}: PlateManager dostępny, pobieranie tablic")
            plates_dict = plate_manager.get_all_plates()
            _LOGGER.info(f"Sensor {self._attr_unique_id}: pobrano {len(plates_dict) if plates_dict else 0} tablic")
            
            if plates_dict:
                sorted_plates = sorted(plates_dict.items())
                formatted_list = '\n'.join([f"{plate} - {owner}" for plate, owner in sorted_plates])
                self._attr_extra_state_attributes = {
                    'formatted_list': formatted_list,
                    'total_plates': len(plates_dict)
                }
                self._attr_state = f"Znane tablice rejestracyjne ({len(plates_dict)})"
            else:
                self._attr_extra_state_attributes = {'formatted_list': 'Brak znanych tablic', 'total_plates': 0}
                self._attr_state = "Znane tablice rejestracyjne (0)"
        else:
            _LOGGER.error(f"Sensor {self._attr_unique_id}: PlateManager nie dostępny w _update_attributes")
            self._attr_extra_state_attributes = {'formatted_list': 'PlateManager nie dostępny', 'total_plates': 0}
            self._attr_state = "PlateManager nie dostępny"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_state

    @property
    def should_poll(self):
        """No polling needed."""
        return False


class PlateRecognitionSensor(SensorEntity):
    """Sensor rozpoznawania tablic dla konkretnej kamery (Last Detection)."""

    def __init__(self, hass: HomeAssistant, image_processing_entity: str, camera_entity: str):
        self.hass = hass
        self._image_processing_entity = image_processing_entity
        self._camera_entity = camera_entity
        camera_name = camera_entity.replace('camera.', '').replace('_', ' ').title()
        self._attr_name = f"Rozpoznane Tablice {camera_name} Last Detection"
        self._attr_unique_id = f"rozpoznane_tablice_{camera_entity.replace('camera.', '')}_last"
        self._attr_state = "Nie wykryto tablic"

    async def async_added_to_hass(self):
        _LOGGER.info(f"Sensor {self._attr_unique_id}: inicjalizacja rozpoczęta")
        
        # Nasłuchuj zmian stanu
        async_track_state_change_event(
            self.hass,
            self._image_processing_entity,
            self._handle_state_change
        )
        
        # Nasłuchuj specjalnego eventu
        self.hass.bus.async_listen(
            'enhanced_platerecognizer_image_processed', 
            self._handle_image_processed
        )
        
        _LOGGER.info(f"Sensor {self._attr_unique_id}: zarejestrowano nasłuchiwanie dla {self._image_processing_entity}")
        
        # od razu pokaż stan domyślny
        self._update_state()
        self.async_write_ha_state()
        _LOGGER.info(f"Sensor {self._attr_unique_id}: inicjalizacja zakończona")

    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu encji image_processing."""
        _LOGGER.debug(f"Sensor {self._attr_unique_id}: otrzymał zmianę stanu")
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_image_processed(self, event):
        """Obsłuż zdarzenie przetworzenia obrazu."""
        event_entity = event.data.get('entity_id')
        _LOGGER.info(f"Sensor {self._attr_unique_id}: otrzymał event od {event_entity}")
        
        if event_entity == self._image_processing_entity:
            _LOGGER.info(f"Sensor {self._attr_unique_id}: event pasuje, przetwarzam")
            
            if event.data.get('has_vehicles'):
                vehicles = event.data.get('vehicles', [])
                plates = [v.get('plate') for v in vehicles if v.get('plate') is not None]
                plates_str = ', '.join(plates) if plates else 'Nie wykryto tablic'
                
                # Dodatkowe atrybuty
                self._attr_extra_state_attributes = {
                    'vehicles_count': len(vehicles),
                    'plates_count': len(plates),
                    'raw_vehicles': vehicles
                }
            else:
                plates_str = 'Nie wykryto tablic'
                self._attr_extra_state_attributes = {
                    'vehicles_count': 0,
                    'plates_count': 0
                }
            
            timestamp = event.data.get('timestamp', '').strip()
            if timestamp:
                self._attr_state = f"{plates_str} @ {timestamp}"
            else:
                self._attr_state = plates_str
                
            _LOGGER.info(f"Sensor {self._attr_unique_id}: nowy stan: {self._attr_state}")
            self.async_write_ha_state()

    def _update_state(self):
        """Aktualizuj stan na podstawie aktualnego stanu encji image_processing."""
        image_processing = self.hass.states.get(self._image_processing_entity)
        if not image_processing or image_processing.state in ["unavailable", "unknown"]:
            self._attr_state = "Kamera niedostępna"
            return

        vehicles = image_processing.attributes.get('vehicles', [])
        if vehicles:
            plates = [v.get('plate') for v in vehicles if v.get('plate') is not None]
            plates_str = ', '.join(plates) if plates else 'Nie wykryto tablic'
        else:
            plates_str = 'Nie wykryto tablic'

        last_detection = image_processing.attributes.get('last_detection', '').strip()
        if last_detection:
            self._attr_state = f"{plates_str} @ {last_detection}"
        else:
            self._attr_state = plates_str


class CombinedPlatesSensor(SensorEntity):
    """Sensor rozpoznane_tablice (kombinuje dane z obu kamer)."""

    def __init__(self, hass: HomeAssistant, image_processing_entities: List[str]):
        self.hass = hass
        self._image_processing_entities = image_processing_entities
        self._attr_name = "Rozpoznane Tablice"
        self._attr_unique_id = "rozpoznane_tablice"
        self.entity_id = "sensor.rozpoznane_tablice"
        self._attr_state = "Brak tablic"
        self._last_detections = {}  # Cache najnowszych wykryć z każdej kamery

    async def async_added_to_hass(self):
        _LOGGER.info(f"Sensor {self.entity_id}: inicjalizacja rozpoczęta")
        _LOGGER.info(f"Sensor {self.entity_id}: będzie nasłuchiwać encji: {self._image_processing_entities}")
        
        if self._image_processing_entities:
            async_track_state_change_event(
                self.hass,
                self._image_processing_entities,
                self._handle_state_change
            )
            
            # Dodaj nasłuchiwanie specjalnego eventu
            self.hass.bus.async_listen(
                'enhanced_platerecognizer_image_processed', 
                self._handle_image_processed
            )
            _LOGGER.info(f"Sensor {self.entity_id}: zarejestrowano nasłuchiwanie eventów")
        else:
            _LOGGER.warning(f"Sensor {self.entity_id}: brak encji do nasłuchiwania!")
        
        # od razu pokaż stan domyślny
        self._update_state()
        self.async_write_ha_state()
        _LOGGER.info(f"Sensor {self.entity_id}: inicjalizacja zakończona")

    @callback
    def _handle_image_processed(self, event):
        """Obsłuż zdarzenie przetworzenia obrazu."""
        entity_id = event.data.get('entity_id')
        _LOGGER.info(f"Sensor {self.entity_id}: otrzymał event od {entity_id}")

        if entity_id in self._image_processing_entities:
            _LOGGER.info(f"Sensor {self.entity_id}: event pasuje, przetwarzam")
            
            timestamp = event.data.get('timestamp', '')
            if event.data.get('has_vehicles'):
                vehicles = event.data.get('vehicles', [])
                api_plates = [v.get('plate') for v in vehicles if v.get('plate') is not None]
                
                plate_manager = self.hass.data.get(DOMAIN, {}).get('plate_manager')
                if plate_manager and api_plates:
                    # Filtruj tylko znane tablice i zwróć wersje z plates.yaml
                    known_plates = []
                    for plate in api_plates:
                        if plate_manager.is_plate_known(plate):
                            corrected_plate = plate_manager.get_corrected_plate(plate)
                            known_plates.append(corrected_plate)
                    
                    if known_plates:
                        detection_text = ', '.join(known_plates)
                        _LOGGER.info(f"Sensor {self.entity_id}: znalezione znane tablice: {detection_text}")
                    else:
                        detection_text = 'Nie wykryto znanych tablic'
                        _LOGGER.info(f"Sensor {self.entity_id}: API zwróciło tablice, ale żadna nie jest znana")
                else:
                    detection_text = 'Nie wykryto znanych tablic'
                   
            else:
                detection_text = 'Nie wykryto tablic'

            # Zapisz najnowsze wykrycie z tej kamery
            self._last_detections[entity_id] = {
                'text': detection_text,
                'timestamp': timestamp,
                'has_plates': detection_text not in ['Nie wykryto tablic', 'Nie wykryto znanych tablic']
            }

            # Wybierz najnowsze wykrycie z tablicami lub najnowsze w ogóle
            self._update_combined_state()
            _LOGGER.info(f"Sensor {self.entity_id}: nowy stan: {self._attr_state}")
            self.async_write_ha_state()
        else:
            _LOGGER.debug(f"Sensor {self.entity_id}: event od innej encji, ignoruję")

    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu encji (backup mechanism)."""
        _LOGGER.info(f"Sensor {self.entity_id}: otrzymał zmianę stanu (backup)")
        self._update_state()
        self.async_write_ha_state()

    def _update_combined_state(self):
        """Zaktualizuj stan na podstawie cache'owanych wykryć."""
        if not self._last_detections:
            self._attr_state = "Brak tablic"
            return
        
        # Znajdź najnowsze wykrycie z tabliami
        valid_detections = [d for d in self._last_detections.values() if d['has_plates']]
        
        if valid_detections:
            # Wybierz najnowsze wykrycie z tabliami
            latest = max(valid_detections, key=lambda x: x['timestamp'])
            self._attr_state = latest['text']
        else:
            # Jeśli żadne nie ma tablic, pokaż "Nie wykryto tablic"
            self._attr_state = "Nie wykryto tablic"
        
        # Dodaj atrybuty z informacjami o wszystkich kamerach
        self._attr_extra_state_attributes = {
            'camera_states': {entity_id: data['text'] for entity_id, data in self._last_detections.items()},
            'camera_timestamps': {entity_id: data['timestamp'] for entity_id, data in self._last_detections.items()}
        }

    def _update_state(self):
        """Zaktualizuj stan na podstawie aktualnych stanów encji (backup method)."""
        if not self._image_processing_entities:
            self._attr_state = "Brak tablic"
            return

        plate_manager = self.hass.data.get(DOMAIN, {}).get('plate_manager')
        camera_data = []
        
        for entity_id in self._image_processing_entities:
            state = self.hass.states.get(entity_id)
            if not state or state.state in ["unavailable", "unknown"]:
                continue

            vehicles = state.attributes.get('vehicles', [])
            if vehicles:
                plates = [v.get('plate') for v in vehicles if v.get('plate') is not None]
                
                if plate_manager and plates:
                    known_plates = []
                    for plate in plates:
                        if plate_manager.is_plate_known(plate):
                            corrected_plate = plate_manager.get_corrected_plate(plate)
                            known_plates.append(corrected_plate)
                    
                    if known_plates:
                        detection_text = ', '.join(known_plates)
                    else:
                        detection_text = 'Nie wykryto znanych tablic'
                else:
                    detection_text = 'Nie wykryto znanych tablic'

            else:
                detection_text = 'Nie wykryto tablic'

            timestamp = state.last_updated
            camera_data.append({
                'entity_id': entity_id,
                'text': detection_text,
                'timestamp': timestamp,
                'has_plates': detection_text not in ['Nie wykryto tablic', 'Nie wykryto znanych tablic']
            })

        if not camera_data:
            self._attr_state = "Kamery niedostępne"
            return

        # Aktualizuj cache
        self._last_detections = {d['entity_id']: d for d in camera_data}

        # Wybierz najnowsze wykrycie z tablicami
        valid_detections = [d for d in camera_data if d['has_plates']]
        if valid_detections:
            latest = max(valid_detections, key=lambda x: x['timestamp'])
            self._attr_state = latest['text']
        else:
            self._attr_state = "Nie wykryto znanych tablic"

        # Dodaj atrybuty
        self._attr_extra_state_attributes = {
            'camera_states': {d['entity_id']: d['text'] for d in camera_data},
            'available_cameras': len(camera_data)
        }

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_state

    @property
    def should_poll(self):
        """No polling needed."""
        return False

class LastRecognizedCarSensor(RestoreEntity, SensorEntity):
    """Sensor zapamiętujący ostatnio rozpoznane tablice."""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._attr_name = "Ostatnie rozpoznane tablice"
        self._attr_unique_id = "last_recognized_car"
        self.entity_id = "sensor.last_recognized_car"
        self._attr_native_value = "Brak rozpoznanych tablic"
        self._last_update_source = None

    async def async_added_to_hass(self):
        """Przywróć poprzedni stan i zacznij nasłuchiwać zmian."""
        await super().async_added_to_hass()
        _LOGGER.info(f"Sensor {self.entity_id}: inicjalizacja rozpoczęta")
        
        last_state = await self.async_get_last_state()
        if last_state and last_state.state:
            self._attr_native_value = last_state.state
            _LOGGER.info(f"Sensor {self.entity_id}: przywrócono stan: {last_state.state}")

        # Nasłuchuj eventu
        self.hass.bus.async_listen(
            'enhanced_platerecognizer_image_processed', 
            self._handle_image_processed
        )
        _LOGGER.info(f"Sensor {self.entity_id}: zarejestrowano nasłuchiwanie eventu")

        self.async_write_ha_state()
        _LOGGER.info(f"Sensor {self.entity_id}: inicjalizacja zakończona")

    @callback
    def _handle_image_processed(self, event):
        """Obsłuż zdarzenie przetworzenia obrazu."""
        _LOGGER.info(f"Sensor {self.entity_id}: otrzymał event, has_vehicles: {event.data.get('has_vehicles')}")
        
        # Zapobiegaj duplikatom
        event_time = event.data.get('timestamp', '')
        if self._last_update_source == f"event_{event_time}":
            _LOGGER.debug(f"Sensor {self.entity_id}: duplikat eventu, ignoruję")
            return
        self._last_update_source = f"event_{event_time}"
        
        if event.data.get('has_vehicles'):
            vehicles = event.data.get('vehicles', [])
            plates = [v.get('plate') for v in vehicles if v.get('plate') is not None]
            if plates:
                self._attr_native_value = ', '.join(plates)
                self._attr_extra_state_attributes = {
                    'last_detection_time': event_time,
                    'detection_source': 'direct_event'
                }
                _LOGGER.info(f"Sensor {self.entity_id}: zaktualizowano na: {self._attr_native_value}")
                self.async_write_ha_state()
        else:
            _LOGGER.debug(f"Sensor {self.entity_id}: brak pojazdów, nie aktualizuję")

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_native_value

    @property
    def should_poll(self):
        """No polling needed."""
        return False


class RecognizedCarSensor(SensorEntity):
    """Sensor recognized_car (sprawdza czy tablice są na liście znanych)."""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._attr_name = "Recognized Car"
        self._attr_unique_id = "recognized_car"
        self._attr_state = "Nie wykryto tablic"
        self._clear_task = None

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        _LOGGER.info(f"Sensor {self._attr_unique_id}: inicjalizacja rozpoczęta")
        
        # Sprawdź dostępność PlateManager
        plate_manager = self.hass.data.get(DOMAIN, {}).get("plate_manager")
        if plate_manager:
            _LOGGER.info(f"Sensor {self._attr_unique_id}: PlateManager jest dostępny")
        else:
            _LOGGER.error(f"Sensor {self._attr_unique_id}: PlateManager NIE JEST dostępny!")
        
        # Nasłuchuj eventu
        self.hass.bus.async_listen(
            'enhanced_platerecognizer_image_processed', 
            self._handle_image_processed
        )
        _LOGGER.info(f"Sensor {self._attr_unique_id}: zarejestrowano nasłuchiwanie eventu")

    @callback
    def _handle_image_processed(self, event):
        """Obsłuż zdarzenie przetworzenia obrazu."""
        _LOGGER.info(f"Sensor {self._attr_unique_id}: otrzymał event, has_vehicles: {event.data.get('has_vehicles')}")
        
        if not event.data.get('has_vehicles'):
            _LOGGER.debug(f"Sensor {self._attr_unique_id}: brak pojazdów, ignoruję")
            return

        vehicles = event.data.get('vehicles', [])
        plates = [v.get('plate').upper() for v in vehicles if v.get('plate') is not None]
        
        if not plates:
            _LOGGER.debug(f"Sensor {self._attr_unique_id}: brak tablic, ignoruję")
            return

        _LOGGER.info(f"Sensor {self._attr_unique_id}: przetwarzam tablice: {plates}")

        plate_manager = self.hass.data.get(DOMAIN, {}).get("plate_manager")
        if not plate_manager:
            _LOGGER.error(f"Sensor {self._attr_unique_id}: PlateManager nie dostępny podczas przetwarzania!")
            return

        # Anuluj poprzedni task
        if self._clear_task and not self._clear_task.done():
            self._clear_task.cancel()

        recognized = [p for p in plates if plate_manager.is_plate_known(p)]
        if recognized:
            # Pobierz właścicieli dla wszystkich rozpoznanych tablic
            owners_info = []
            for plate in recognized:
                owner = plate_manager.get_plate_owner(plate)
                owners_info.append(f"{plate} ({owner})")
            
            self._attr_state = f"Rozpoznano: {', '.join(owners_info)}"
            _LOGGER.info(f"Sensor {self._attr_unique_id}: rozpoznano tablice: {self._attr_state}")
        else:
            self._attr_state = f"Nie rozpoznano: {', '.join(plates)}"
            _LOGGER.info(f"Sensor {self._attr_unique_id}: nie rozpoznano tablic: {self._attr_state}")

        self.async_write_ha_state()

        # Usuń po 10s
        self._clear_task = self.hass.async_create_task(self._clear_after_delay())

    async def _clear_after_delay(self):
        """Wyczyść stan po 10 sekundach."""
        try:
            await asyncio.sleep(10)
            self._attr_state = "Nie wykryto tablic"
            _LOGGER.info(f"Sensor {self._attr_unique_id}: stan wyczyszczony po 10s")
            self.async_write_ha_state()
        except asyncio.CancelledError:
            _LOGGER.debug(f"Sensor {self._attr_unique_id}: clear task anulowany")
            pass

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_state

    @property
    def should_poll(self):
        """No polling needed."""
        return False