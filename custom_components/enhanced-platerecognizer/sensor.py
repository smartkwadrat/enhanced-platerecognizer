"""Sensory dla Enhanced Plate Recognizer."""
import logging
from typing import Any, Dict, List
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

DOMAIN = "enhanced_platerecognizer"

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType = None,
) -> None:
    """Ustaw sensory."""
    
    # Pobierz konfigurację image_processing z configuration.yaml
    image_processing_config = hass.data.get('image_processing', {})
    platerecognizer_sources = []
    tolerate_one_mistake = True  # domyślna wartość
    
    # Znajdź wszystkie źródła enhanced_platerecognizer i pobierz konfigurację
    for platform_config in image_processing_config:
        if platform_config.get('platform') == 'enhanced_platerecognizer':
            # Pobierz opcję tolerate_one_mistake z konfiguracji
            tolerate_one_mistake = platform_config.get('tolerate_one_mistake', True)
            
            sources = platform_config.get('source', [])
            for source in sources:
                entity_id = source.get('entity_id')
                if entity_id:
                    platerecognizer_sources.append(entity_id)
    
    # Zainicjalizuj PlateManager jeśli jeszcze nie istnieje
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    
    if "plate_manager" not in hass.data[DOMAIN]:
        from .plate_manager import PlateManager
        
        # Przekaż konfigurację z tolerate_one_mistake
        plate_config = {"tolerate_one_mistake": tolerate_one_mistake}
        plate_manager = PlateManager(hass, plate_config)
        hass.data[DOMAIN]["plate_manager"] = plate_manager
    
    # Utwórz input_text i input_select entities jeśli nie istnieją
    await _create_helper_entities(hass)
    
    entities = []
    
    # Dodaj sensor z listą znanych tablic
    entities.append(FormattedCarPlatesSensor(hass))
    
    # Dodaj sensory dla każdego źródła
    for source in platerecognizer_sources:
        # Utwórz entity_id dla image_processing
        camera_name = source.replace('camera.', '')
        image_processing_entity = f"image_processing.enhanced_platerecognizer_{camera_name}"
        
        entities.append(PlateRecognitionSensor(hass, image_processing_entity, source))
    
    async_add_entities(entities, True)

async def _create_helper_entities(hass: HomeAssistant):
    """Utwórz automatycznie input_text i input_select entities."""
    
    # Sprawdź czy entities już istnieją
    existing_entities = [
        'input_text.add_new_plate',
        'input_text.add_plate_owner', 
        'input_select.remove_plate'
    ]
    
    entities_to_create = []
    
    for entity_id in existing_entities:
        if hass.states.get(entity_id) is None:
            entities_to_create.append(entity_id)
    
    if not entities_to_create:
        return
    
    # Utwórz input_text entities
    if 'input_text.add_new_plate' in entities_to_create:
        await hass.services.async_call(
            'input_text', 'create',
            {
                'name': 'Add New Plate',
                'object_id': 'add_new_plate',
                'min': 0,
                'max': 255,
                'pattern': '[A-Z0-9 ]+',
                'mode': 'text'
            }
        )
        _LOGGER.info("Utworzono input_text.add_new_plate")
    
    if 'input_text.add_plate_owner' in entities_to_create:
        await hass.services.async_call(
            'input_text', 'create',
            {
                'name': 'Add Plate Owner',
                'object_id': 'add_plate_owner',
                'min': 0,
                'max': 255,
                'mode': 'text'
            }
        )
        _LOGGER.info("Utworzono input_text.add_plate_owner")
    
    # Utwórz input_select entity
    if 'input_select.remove_plate' in entities_to_create:
        await hass.services.async_call(
            'input_select', 'create',
            {
                'name': 'Remove plate',
                'object_id': 'remove_plate',
                'options': ['Brak tablic']
            }
        )
        _LOGGER.info("Utworzono input_select.remove_plate")

class FormattedCarPlatesSensor(SensorEntity):
    """Sensor z listą znanych tablic."""
    
    def __init__(self, hass: HomeAssistant):
        """Inicjalizuj sensor."""
        self.hass = hass
        self._attr_name = "Znane tablice rejestracyjne"
        self._attr_unique_id = "formatted_car_plates"
        self._attr_state = "Znane tablice rejestracyjne"
        self._attr_extra_state_attributes = {}
    
    async def async_added_to_hass(self):
        """Gdy sensor zostanie dodany do HA."""
        # Nasłuchuj zmian w input_select.remove_plate
        async_track_state_change_event(
            self.hass,
            'input_select.remove_plate',
            self._handle_state_change
        )
        self._update_attributes()
    
    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu."""
        self._update_attributes()
        self.async_write_ha_state()
    
    def _update_attributes(self):
        """Zaktualizuj atrybuty."""
        input_select = self.hass.states.get('input_select.remove_plate')
        if input_select and input_select.attributes.get('options'):
            plates = input_select.attributes['options'][1:]  # Pomiń "Brak tablic"
            formatted_list = '\n'.join(f"{i+1}. {plate}" for i, plate in enumerate(plates))
            self._attr_extra_state_attributes = {'formatted_list': formatted_list}

class PlateRecognitionSensor(SensorEntity):
    """Sensor rozpoznawania tablic dla konkretnej kamery."""
    
    def __init__(self, hass: HomeAssistant, image_processing_entity: str, camera_entity: str):
        """Inicjalizuj sensor."""
        self.hass = hass
        self._image_processing_entity = image_processing_entity
        self._camera_entity = camera_entity
        
        # Utwórz nazwę sensora na podstawie nazwy kamery
        camera_name = camera_entity.replace('camera.', '').replace('_', ' ').title()
        self._attr_name = f"Rozpoznane Tablice {camera_name} Last Detection"
        self._attr_unique_id = f"rozpoznane_tablice_{camera_entity.replace('camera.', '')}_last"
        self._attr_state = "Brak tablicy"
    
    async def async_added_to_hass(self):
        """Gdy sensor zostanie dodany do HA."""
        # Nasłuchuj zmian w odpowiednim image_processing
        async_track_state_change_event(
            self.hass,
            self._image_processing_entity,
            self._handle_state_change
        )
        self._update_state()
    
    @callback
    def _handle_state_change(self, event):
        """Obsłuż zmianę stanu."""
        self._update_state()
        self.async_write_ha_state()
    
    def _update_state(self):
        """Zaktualizuj stan sensora."""
        image_processing = self.hass.states.get(self._image_processing_entity)
        if not image_processing:
            self._attr_state = "Brak tablicy"
            return
        
        vehicles = image_processing.attributes.get('vehicles', [])
        if vehicles:
            plates = [vehicle.get('plate') for vehicle in vehicles if vehicle.get('plate')]
            plates_str = ', '.join(plates) if plates else 'Brak tablicy'
        else:
            plates_str = 'Brak tablicy'
        
        last_detection = image_processing.attributes.get('last_detection', '')
        self._attr_state = f"{plates_str} @ {last_detection}"
