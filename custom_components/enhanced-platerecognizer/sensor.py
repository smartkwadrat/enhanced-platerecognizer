"""Sensory dla Enhanced Plate Recognizer."""
import logging
from typing import Any, Dict, List
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

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
        async_track_state_change_event(
            self.hass,
            self._image_processing_entity,
            self._handle_state_change
        )
        # od razu pokaż stan domyślny zamiast "unknown"
        self.async_write_ha_state()
        self.hass.async_create_task(self._delayed_update())

    async def _delayed_update(self):
        import asyncio
        await asyncio.sleep(5)
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self):
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
        # Pobierz dane bezpośrednio z PlateManager
        plate_manager = self.hass.data.get(DOMAIN, {}).get('plate_manager')
        if plate_manager:
            plates_dict = plate_manager.get_all_plates()
            if plates_dict:
                # Format: "tablica - właściciel"
                formatted_list = '\n'.join([f"{plate} - {owner}" for plate, owner in plates_dict.items()])
                self._attr_extra_state_attributes = {'formatted_list': formatted_list}
            else:
                self._attr_extra_state_attributes = {'formatted_list': 'Brak znanych tablic'}
        else:
            self._attr_extra_state_attributes = {'formatted_list': 'PlateManager nie dostępny'}

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
        async_track_state_change_event(
            self.hass,
            self._image_processing_entity,
            self._handle_state_change
        )
        # od razu pokaż stan domyślny
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self):
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

        last_detection = image_processing.attributes.get('last_detection', '')
        self._attr_state = f"{plates_str} @ {last_detection}"

class CombinedPlatesSensor(SensorEntity):
    """Sensor rozpoznane_tablice (kombinuje dane z obu kamer)."""

    def __init__(self, hass: HomeAssistant, image_processing_entities: List[str]):
        self.hass = hass
        self._image_processing_entities = image_processing_entities
        self._attr_name = "Rozpoznane Tablice"
        self._attr_unique_id = "rozpoznane_tablice"
        self.entity_id = "sensor.rozpoznane_tablice"
        self._attr_state = "Brak tablic"

    async def async_added_to_hass(self):
        if self._image_processing_entities:
            async_track_state_change_event(
                self.hass,
                self._image_processing_entities,
                self._handle_state_change
            )
        # od razu pokaż stan domyślny
        self._update_state()
        self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self):
        if not self._image_processing_entities:
            self._attr_state = "Brak tablic"
            return

        camera_states = []
        camera_times = []
        for entity_id in self._image_processing_entities:
            state = self.hass.states.get(entity_id)
            if not state or state.state in ["unavailable", "unknown"]:
                continue
            vehicles = state.attributes.get('vehicles', [])
            if vehicles:
                plates = [v.get('plate') for v in vehicles if v.get('plate')]
                camera_states.append(', '.join(plates) if plates else 'Nie wykryto tablic')
            else:
                camera_states.append('Nie wykryto tablic')
            camera_times.append(state.last_changed)

        if not camera_states:
            self._attr_state = "Kamery niedostępne"
            return

        valid = [(s, t) for s, t in zip(camera_states, camera_times) if s != 'Nie wykryto tablic']
        if valid:
            latest_state = max(valid, key=lambda x: x[1])[0]
            self._attr_state = latest_state
        else:
            self._attr_state = "Nie wykryto tablic"

class LastRecognizedCarSensor(RestoreEntity, SensorEntity):
    """Sensor zapamiętujący ostatnio rozpoznane tablice."""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._attr_name = "Ostatnie rozpoznane tablice"
        self._attr_unique_id = "last_recognized_car"
        self.entity_id = "sensor.last_recognized_car"
        # Domyślna wartość przed przywróceniem
        self._attr_native_value = "Brak rozpoznanych tablic"

    async def async_added_to_hass(self):
        """Przywróć poprzedni stan i zacznij nasłuchiwać zmian."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last:
            self._attr_native_value = last.native_value
        async_track_state_change_event(
            self.hass,
            "sensor.rozpoznane_tablice",
            self._handle_state_change
        )
        # od razu pokaż przywrócony lub domyślny stan
        self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        """Aktualizuj stan na każdą istotną zmianę rozpoznania."""
        new = event.data.get("new_state")
        if not new or new.state in ["Brak tablic", "Nie wykryto tablic", "Kamery niedostępne", "", None]:
            return
        self._attr_native_value = new.state
        self.async_write_ha_state()

class RecognizedCarSensor(SensorEntity):
    """Sensor recognized_car (sprawdza czy tablice są na liście znanych)."""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._attr_name = "Recognized Car"
        self._attr_unique_id = "recognized_car"
        self._attr_state = "Nie wykryto tablic"

    async def async_added_to_hass(self):
        async_track_state_change_event(
            self.hass,
            'sensor.rozpoznane_tablice',
            self._handle_state_change
        )

    @callback
    def _handle_state_change(self, event):
        new_state = event.data.get('new_state')
        if not new_state or new_state.state in ["Kamery niedostępne", "Nie wykryto tablic"]:
            return

        plates_str = new_state.state.split('@')[0].strip()
        plates = [p.strip().upper() for p in plates_str.split(',') if p.strip()]
        plate_manager = self.hass.data.get(DOMAIN, {}).get("plate_manager")
        if not plate_manager or not plates:
            self._attr_state = "Nie wykryto tablic"
        else:
            recognized = [p for p in plates if plate_manager.is_plate_known(p)]
            if recognized:
                owner = plate_manager.get_plate_owner(recognized[0])
                text = f"Rozpoznano: {recognized[0]} ({owner})"
                if len(recognized) > 1:
                    text += f" + {len(recognized) - 1} innych"
                self._attr_state = text
            else:
                self._attr_state = f"Nie rozpoznano: {', '.join(plates)}"

        self.async_write_ha_state()
        # usuń po 10s
        import asyncio
        self.hass.async_create_task(self._clear_after_delay())

    async def _clear_after_delay(self):
        import asyncio
        await asyncio.sleep(10)
        self._attr_state = "Nie wykryto tablic"
        self.async_write_ha_state()

