"""Sensory dla Enhanced Plate Recognizer."""
import logging
from typing import Any, Dict, List
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
import asyncio 

_LOGGER = logging.getLogger(__name__)

DOMAIN = "enhanced_platerecognizer"

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType = None,
) -> None:
    """Ustaw sensory."""
    _LOGGER.info("Enhanced Plate Recognizer: async_setup_platform called!")
    
    # Pobierz konfigurację image_processing z configuration.yaml
    image_processing_config = hass.data.get('image_processing', {})
    platerecognizer_sources = []
    tolerate_one_mistake = True
    
    for platform_config in image_processing_config:
        if platform_config.get('platform') == 'enhanced_platerecognizer':
            tolerate_one_mistake = platform_config.get('tolerate_one_mistake', True)
            sources = platform_config.get('source', [])
            for source in sources:
                entity_id = source.get('entity_id')
                if entity_id:
                    platerecognizer_sources.append(entity_id)
    
    # Zainicjalizuj PlateManager
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    
    if "plate_manager" not in hass.data[DOMAIN]:
        from .plate_manager import PlateManager
        plate_config = {"tolerate_one_mistake": tolerate_one_mistake}
        plate_manager = PlateManager(hass, plate_config)
        hass.data[DOMAIN]["plate_manager"] = plate_manager
    
    entities = []
    
    # 1. Sensor z listą znanych tablic
    entities.append(FormattedCarPlatesSensor(hass))
    
    # 2. Utwórz image_processing entity_id na podstawie konfiguracji (nie sprawdzaj czy istnieją)
    image_processing_entities = []
    for source in platerecognizer_sources:
        camera_name = source.replace('camera.', '')
        # Przewidywane entity_id na podstawie nazwy kamery
        image_processing_entity = f"image_processing.platerecognizer_{camera_name}"
        image_processing_entities.append(image_processing_entity)
        _LOGGER.info(f"Expected image_processing entity: {image_processing_entity}")
    
    # 3. Sensory Last Detection dla każdej kamery
    for i, source in enumerate(platerecognizer_sources):
        camera_name = source.replace('camera.', '')
        image_processing_entity = f"image_processing.platerecognizer_{camera_name}"
        entities.append(PlateRecognitionSensor(hass, image_processing_entity, source))
    
    # 4. Sensory rozpoznane_tablice_kamera_1/2 (mapowanie template)
    for i, source in enumerate(platerecognizer_sources, 1):
        camera_name = source.replace('camera.', '')
        image_processing_entity = f"image_processing.platerecognizer_{camera_name}"
        entities.append(RozpoznaneTablesKameraSensor(hass, image_processing_entity, i))
    
    # 5. Sensor rozpoznane_tablice (combined)
    entities.append(CombinedPlatesSensor(hass, image_processing_entities))
    
    # 6. Sensor last_recognized_car
    entities.append(LastRecognizedCarSensor(hass))
    
    # 7. Sensor recognized_car
    entities.append(RecognizedCarSensor(hass))
    
    _LOGGER.info(f"Created {len(entities)} sensors")
    async_add_entities(entities, True)

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
        # Nasłuchuj zmian stanu encji (dla przypadków gdy event się nie wyemituje)
        async_track_state_change_event(
            self.hass,
            self._image_processing_entity,
            self._handle_state_change
        )
        
        # Nasłuchuj specjalnego eventu (główny mechanizm)
        self.hass.bus.async_listen(
            'enhanced_platerecognizer_image_processed', 
            self._handle_image_processed
        )
        
        # od razu pokaż stan domyślny zamiast "unknown"
        self.async_write_ha_state()
        self.hass.async_create_task(self._delayed_update())

    async def _delayed_update(self):
        await asyncio.sleep(5)
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu encji image_processing (backup mechanism)."""
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_image_processed(self, event):
        """Obsłuż zdarzenie przetworzenia obrazu (primary mechanism)."""
        if event.data.get('entity_id') == self._image_processing_entity:
            # Wykorzystaj dane bezpośrednio z eventu - bardziej efektywne
            if event.data.get('has_vehicles'):
                vehicles = event.data.get('vehicles', [])
                plates = [v.get('plate') for v in vehicles if v.get('plate')]
                plates_str = ', '.join(plates) if plates else 'Nie wykryto tablic'
            else:
                plates_str = 'Nie wykryto tablic'
            
            timestamp = event.data.get('timestamp', '')
            if timestamp:
                self._attr_state = f"{plates_str} @ {timestamp}"
            else:
                self._attr_state = plates_str
                
            self.async_write_ha_state()

    def _update_state(self):
        """Aktualizuj stan na podstawie aktualnego stanu encji (backup method)."""
        image_processing = self.hass.states.get(self._image_processing_entity)
        if not image_processing or image_processing.state in ["unavailable", "unknown"]:
            self._attr_state = "Kamera niedostępna"
            return

        vehicles = image_processing.attributes.get('vehicles', [])
        last_detection = image_processing.attributes.get('last_detection', '')

        if vehicles:
            plates = [v.get('plate') for v in vehicles if v.get('plate')]
            plates_str = ', '.join(plates) if plates else 'Nie wykryto tablic'
        else:
            plates_str = 'Nie wykryto tablic'

        if last_detection:
            self._attr_state = f"{plates_str} @ {last_detection}"
        else:
            self._attr_state = plates_str
            

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
        # Nasłuchuj zmian w PlateManager poprzez eventy
        self.hass.bus.async_listen('enhanced_platerecognizer_plate_added', self._handle_plate_change)
        self.hass.bus.async_listen('enhanced_platerecognizer_plate_removed', self._handle_plate_change)
        
        # Nasłuchuj też zmian w input_select dla backup
        async_track_state_change_event(
            self.hass,
            'input_select.remove_plate',
            self._handle_state_change
        )
        self._update_attributes()
        self.async_write_ha_state()  # DODANE
    
    @callback
    def _handle_plate_change(self, event):
        """Obsłuż zmianę tablic przez PlateManager."""
        self._update_attributes()
        self.async_write_ha_state()
    
    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu input_select (backup)."""
        self._update_attributes()
        self.async_write_ha_state()
    
    def _update_attributes(self):
        """Zaktualizuj atrybuty z tablicami i właścicielami."""
        plate_manager = self.hass.data.get(DOMAIN, {}).get('plate_manager')
        if plate_manager:
            plates_dict = plate_manager.get_all_plates()
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
            self._attr_extra_state_attributes = {'formatted_list': 'PlateManager nie dostępny', 'total_plates': 0}
            self._attr_state = "PlateManager nie dostępny"

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
        # Nasłuchuj zmian stanu (istniejący kod)
        async_track_state_change_event(
            self.hass,
            self._image_processing_entity,
            self._handle_state_change
        )
        
        # Nasłuchuj specjalnego eventu dla natychmiastowych reakcji
        self.hass.bus.async_listen(
            'enhanced_platerecognizer_image_processed', 
            self._handle_image_processed
        )
        
        # od razu pokaż stan domyślny
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu encji image_processing."""
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_image_processed(self, event):
        """Obsłuż zdarzenie przetworzenia obrazu."""
        if event.data.get('entity_id') == self._image_processing_entity:
            if event.data.get('has_vehicles'):
                vehicles = event.data.get('vehicles', [])
                plates = [v.get('plate') for v in vehicles if v.get('plate')]
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
            self.async_write_ha_state()

    def _update_state(self):
        """Aktualizuj stan na podstawie aktualnego stanu encji image_processing."""
        image_processing = self.hass.states.get(self._image_processing_entity)
        if not image_processing or image_processing.state in ["unavailable", "unknown"]:
            self._attr_state = "Kamera niedostępna"
            return

        vehicles = image_processing.attributes.get('vehicles', [])
        if vehicles:
            plates = [v.get('plate') for v in vehicles if v.get('plate')]
            plates_str = ', '.join(plates) if plates else 'Nie wykryto tablic'
        else:
            plates_str = 'Nie wykryto tablic'

        last_detection = image_processing.attributes.get('last_detection', '').strip()
        # POPRAWKA: Sprawdź czy last_detection nie jest pusty
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
        # od razu pokaż stan domyślny
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_image_processed(self, event):
        """Obsłuż zdarzenie przetworzenia obrazu."""
        entity_id = event.data.get('entity_id')
        if entity_id in self._image_processing_entities:
            # OPTYMALIZACJA: Wykorzystaj dane bezpośrednio z eventu
            timestamp = event.data.get('timestamp', '')
            
            if event.data.get('has_vehicles'):
                vehicles = event.data.get('vehicles', [])
                plates = [v.get('plate') for v in vehicles if v.get('plate') is not None]
                detection_text = ', '.join(plates) if plates else 'Nie wykryto tablic'
            else:
                detection_text = 'Nie wykryto tablic'
            
            # Zapisz najnowsze wykrycie z tej kamery
            self._last_detections[entity_id] = {
                'text': detection_text,
                'timestamp': timestamp,
                'has_plates': detection_text != 'Nie wykryto tablic'
            }
            
            # Wybierz najnowsze wykrycie z tablicami lub najnowsze w ogóle
            self._update_combined_state()
            self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu encji (backup mechanism)."""
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

        camera_data = []
        for entity_id in self._image_processing_entities:
            state = self.hass.states.get(entity_id)
            if not state or state.state in ["unavailable", "unknown"]:
                continue
                
            vehicles = state.attributes.get('vehicles', [])
            if vehicles:
                # POPRAWKA: Sprawdź czy plate nie jest None
                plates = [v.get('plate') for v in vehicles if v.get('plate') is not None]
                detection_text = ', '.join(plates) if plates else 'Nie wykryto tablic'
            else:
                detection_text = 'Nie wykryto tablic'
            
            # Użyj last_updated zamiast last_changed dla lepszej precyzji
            timestamp = state.last_updated
            camera_data.append({
                'entity_id': entity_id,
                'text': detection_text,
                'timestamp': timestamp,
                'has_plates': detection_text != 'Nie wykryto tablic'
            })

        if not camera_data:
            self._attr_state = "Kamery niedostępne"
            return

        # Aktualizuj cache
        self._last_detections = {d['entity_id']: d for d in camera_data}
        
        # Wybierz najnowsze wykrycie z tabliami
        valid_detections = [d for d in camera_data if d['has_plates']]
        
        if valid_detections:
            latest = max(valid_detections, key=lambda x: x['timestamp'])
            self._attr_state = latest['text']
        else:
            self._attr_state = "Nie wykryto tablic"
        
        # Dodaj atrybuty
        self._attr_extra_state_attributes = {
            'camera_states': {d['entity_id']: d['text'] for d in camera_data},
            'available_cameras': len(camera_data)
        }

class LastRecognizedCarSensor(RestoreEntity, SensorEntity):
    """Sensor zapamiętujący ostatnio rozpoznane tablice."""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._attr_name = "Ostatnie rozpoznane tablice"
        self._attr_unique_id = "last_recognized_car"
        self.entity_id = "sensor.last_recognized_car"
        # Domyślna wartość przed przywróceniem
        self._attr_native_value = "Brak rozpoznanych tablic"
        self._last_update_source = None  # Śledź źródło ostatniej aktualizacji

    async def async_added_to_hass(self):
        """Przywróć poprzedni stan i zacznij nasłuchiwać zmian."""
        await super().async_added_to_hass()
        
        last_state = await self.async_get_last_state()
        if last_state and last_state.state:
            self._attr_native_value = last_state.state

        # WYBIERZ JEDEN MECHANIZM - zalecam event jako główny
        # async_track_state_change_event(
        #     self.hass,
        #     "sensor.rozpoznane_tablice",
        #     self._handle_state_change
        # )

        # Główny mechanizm - nasłuchuj eventu
        self.hass.bus.async_listen(
            'enhanced_platerecognizer_image_processed', 
            self._handle_image_processed
        )

        self.async_write_ha_state()

    @callback
    def _handle_image_processed(self, event):
        """Obsłuż zdarzenie przetworzenia obrazu."""
        # Zapobiegaj duplikatom jeśli ten sam event przyszedł z różnych źródeł
        event_time = event.data.get('timestamp', '')
        if self._last_update_source == f"event_{event_time}":
            return
        self._last_update_source = f"event_{event_time}"
        
        if event.data.get('has_vehicles'):
            vehicles = event.data.get('vehicles', [])
            # POPRAWKA: Sprawdź czy plate nie jest None
            plates = [v.get('plate') for v in vehicles if v.get('plate') is not None]
            if plates:
                self._attr_native_value = ', '.join(plates)
                # Dodaj timestamp jako atrybut
                self._attr_extra_state_attributes = {
                    'last_detection_time': event_time,
                    'detection_source': 'direct_event'
                }
                self.async_write_ha_state()
        # OPCJONALNIE: Jeśli chcesz aktualizować też gdy nie ma tablic
        # else:
        #     # Nie zmieniaj _attr_native_value, ale zaktualizuj timestamp
        #     self._attr_extra_state_attributes = {
        #         'last_scan_time': event_time,
        #         'detection_source': 'direct_event'
        #     }
        #     self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu sensor.rozpoznane_tablice (backup mechanism)."""
        new = event.data.get("new_state")
        if not new or new.state in ["Brak tablic", "Nie wykryto tablic", "Kamery niedostępne", "", None]:
            return

        # Zapobiegaj duplikatom
        state_time = new.last_updated.isoformat()
        if self._last_update_source == f"state_{state_time}":
            return
        self._last_update_source = f"state_{state_time}"

        self._attr_native_value = new.state
        self._attr_extra_state_attributes = {
            'last_detection_time': state_time,
            'detection_source': 'state_change'
        }
        self.async_write_ha_state()

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
        
        # Tylko event - prostsze
        self.hass.bus.async_listen(
            'enhanced_platerecognizer_image_processed', 
            self._handle_image_processed
        )

    @callback
    def _handle_image_processed(self, event):
        """Obsłuż zdarzenie przetworzenia obrazu."""
        if not event.data.get('has_vehicles'):
            return
        
        vehicles = event.data.get('vehicles', [])
        plates = [v.get('plate').upper() for v in vehicles if v.get('plate') is not None]
        
        if not plates:
            return
        
        plate_manager = self.hass.data.get(DOMAIN, {}).get("plate_manager")
        if not plate_manager:
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
        else:
            self._attr_state = f"Nie rozpoznano: {', '.join(plates)}"
        
        self.async_write_ha_state()
        
        # Usuń po 10s
        self._clear_task = self.hass.async_create_task(self._clear_after_delay())

    async def _clear_after_delay(self):
        """Wyczyść stan po 10 sekundach."""
        try:
            await asyncio.sleep(10)
            self._attr_state = "Nie wykryto tablic"
            self.async_write_ha_state()
        except asyncio.CancelledError:
            pass


