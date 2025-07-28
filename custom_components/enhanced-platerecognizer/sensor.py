"""Sensors for Enhanced Plate Recognizer."""

import logging
import asyncio
from typing import Any, Dict, List

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback, CoreState
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType, DiscoveryInfoType
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import EVENT_HOMEASSISTANT_START

_LOGGER = logging.getLogger(__name__)

DOMAIN = "enhanced_platerecognizer"

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None
) -> None:
    """Configure platform sensors in an asynchronous and error-resistant manner."""
    _LOGGER.info("Enhanced Plate Recognizer: async_setup_platform called. Waiting for Home Assistant to start.")

    @callback
    def create_sensors(event: Any) -> None:
        """Function that creates sensors after Home Assistant fully starts."""
        _LOGGER.info("Home Assistant started. Creating Enhanced Plate Recognizer sensors.")

        all_ip_entities = hass.states.async_entity_ids('image_processing')
        image_processing_entities = [
            entity_id for entity_id in all_ip_entities if 'platerecognizer' in entity_id
        ]

        if not image_processing_entities:
            _LOGGER.warning("No 'platerecognizer' image_processing entities found. Sensors will not be created.")
            return

        _LOGGER.info(f"Found image_processing entities to use: {image_processing_entities}")

        sensors_to_add = []
        
        for i, entity_id in enumerate(image_processing_entities, 1):
            _LOGGER.info(f"Creating sensor for camera {i} linked to {entity_id}")
            sensors_to_add.append(PlateRecognitionCameraSensor(hass, entity_id, i))

        sensors_to_add.extend([
            LastRecognizedCarSensor(hass),
            RecognizedCarSensor(hass),
            FormattedCarPlatesSensor(hass)
        ])

        _LOGGER.info(f"Adding {len(sensors_to_add)} sensors to Home Assistant.")
        async_add_entities(sensors_to_add, True)

    if hass.state == CoreState.running:
        create_sensors(None)
    else:
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, create_sensors)


class PlateRecognitionCameraSensor(SensorEntity):
    """Sensor for individual camera, e.g. sensor.plate_recognition_camera_1."""

    def __init__(self, hass: HomeAssistant, image_processing_entity: str, camera_nr: int):
        """Initialize the sensor."""
        self.hass = hass
        self._image_processing_entity = image_processing_entity
        self._attr_name = f"Plate Recognition Camera {camera_nr}"
        self._attr_unique_id = f"enhanced_platerecognizer_camera_{camera_nr}"
        self.entity_id = f"sensor.plate_recognition_camera_{camera_nr}"
        self._attr_state = self._get_translation('state.sensor.plate_recognition_camera.waiting_api')
        self._attr_extra_state_attributes = {}

    def _get_translation(self, key: str, **kwargs) -> str:
        """Get translated text based on current language setting."""
        try:
            language = self.hass.config.language if self.hass else 'en'
            if language != 'pl':
                language = 'en'
            
            # Try to get translations from hass.data or fallback to hardcoded
            translations = self.hass.data.get(DOMAIN, {}).get('translations', {}).get(language, {})
            
            # Navigate through translation structure
            keys = key.split('.')
            current = translations
            for k in keys:
                if isinstance(current, dict) and k in current:
                    current = current[k]
                else:
                    # Fallback to English hardcoded values
                    return self._get_fallback_translation(key, **kwargs)
            
            # Format with provided kwargs if it's a string
            if isinstance(current, str) and kwargs:
                return current.format(**kwargs)
            return current if isinstance(current, str) else self._get_fallback_translation(key, **kwargs)
            
        except Exception as e:
            _LOGGER.debug(f"Translation error for key '{key}': {e}")
            return self._get_fallback_translation(key, **kwargs)

    def _get_fallback_translation(self, key: str, **kwargs) -> str:
        """Fallback translations when translation system fails."""
        fallbacks = {
            'state.sensor.plate_recognition_camera.waiting_api': 'Waiting for API',
            'state.sensor.plate_recognition_camera.no_plates': 'No plates detected',
            'state.sensor.plate_recognition_camera.vehicle_no_plate': 'Vehicle detected without plate',
            'state.sensor.plate_recognition_camera.camera_unavailable': 'Camera unavailable',
        }
        
        result = fallbacks.get(key, key)
        if kwargs:
            try:
                result = result.format(**kwargs)
            except:
                pass
        return result

    async def async_added_to_hass(self) -> None:
        """Called after adding entity to HA. Sets initial state and listens to events."""
        await super().async_added_to_hass()
        
        # Set default state
        self._attr_state = self._get_translation('state.sensor.plate_recognition_camera.waiting_api')
        self._attr_extra_state_attributes = {}
        _LOGGER.info(f"Sensor {self.entity_id}: Set default state: 'Waiting for API'")

        # Register event listening
        self.async_on_remove(
            self.hass.bus.async_listen(
                'enhanced_platerecognizer_image_processed',
                self._handle_image_processed
            )
        )
        _LOGGER.info(f"Sensor {self.entity_id}: Started listening to events from '{self._image_processing_entity}'.")

        # Force state update
        self.async_write_ha_state()
        _LOGGER.info(f"Sensor {self.entity_id}: State written to HA: '{self._attr_state}'")

    @callback
    def _handle_image_processed(self, event: Any) -> None:
        """Handle event after image processing by corresponding camera."""
        event_entity_id = event.data.get('entity_id')
        
        # Debug log for better diagnosis
        _LOGGER.debug(f"Sensor {self.entity_id}: Received event from '{event_entity_id}', expected: '{self._image_processing_entity}'")

        if event_entity_id != self._image_processing_entity:
            return

        _LOGGER.debug(f"Sensor {self.entity_id}: Received matching event with data: {event.data}")

        has_vehicles = event.data.get('has_vehicles', False)
        timestamp = event.data.get('timestamp', '')
        plates = []

        if has_vehicles:
            vehicles = event.data.get('vehicles', [])
            plates = [v.get('plate') for v in vehicles if v.get('plate')]
            
            # If there are vehicles but no plates, set appropriate message
            new_state_text = ', '.join(plates) if plates else self._get_translation('state.sensor.plate_recognition_camera.vehicle_no_plate')
        else:
            new_state_text = self._get_translation('state.sensor.plate_recognition_camera.no_plates')

        new_state = f"{new_state_text} @ {timestamp}" if plates and timestamp else new_state_text

        if self._attr_state != new_state:
            self._attr_state = new_state
            self._attr_extra_state_attributes['last_update'] = timestamp
            self.async_write_ha_state()
            _LOGGER.info(f"Sensor {self.entity_id}: state updated to: '{new_state}'")

    def get_linked_image_processing_entity(self):
        """Returns entity_id of linked image_processing entity for debugging."""
        return self._image_processing_entity

    @property
    def state(self):
        """Return current sensor state."""
        return self._attr_state

    @property
    def should_poll(self) -> bool:
        """Disable polling since sensor is updated by events."""
        return False


class FormattedCarPlatesSensor(SensorEntity):
    """Sensor with list of known plates with owners."""

    def __init__(self, hass: HomeAssistant):
        """Initialize sensor."""
        self.hass = hass
        self._attr_name = "Formatted Car Plates"
        self._attr_unique_id = "formatted_car_plates"
        self._attr_state = self._get_translation('state.sensor.formatted_car_plates.known_plates')
        self._attr_extra_state_attributes = {}

    def _get_translation(self, key: str, **kwargs) -> str:
        """Get translated text based on current language setting."""
        try:
            language = self.hass.config.language if self.hass else 'en'
            if language != 'pl':
                language = 'en'
            
            # Try to get translations from hass.data or fallback to hardcoded
            translations = self.hass.data.get(DOMAIN, {}).get('translations', {}).get(language, {})
            
            # Navigate through translation structure
            keys = key.split('.')
            current = translations
            for k in keys:
                if isinstance(current, dict) and k in current:
                    current = current[k]
                else:
                    # Fallback to English hardcoded values
                    return self._get_fallback_translation(key, **kwargs)
            
            # Format with provided kwargs if it's a string
            if isinstance(current, str) and kwargs:
                return current.format(**kwargs)
            return current if isinstance(current, str) else self._get_fallback_translation(key, **kwargs)
            
        except Exception as e:
            _LOGGER.debug(f"Translation error for key '{key}': {e}")
            return self._get_fallback_translation(key, **kwargs)

    def _get_fallback_translation(self, key: str, **kwargs) -> str:
        """Fallback translations when translation system fails."""
        fallbacks = {
            'state.sensor.formatted_car_plates.known_plates': 'Known license plates',
            'state.sensor.formatted_car_plates.known_plates_count': 'Known license plates ({count})',
            'state.sensor.formatted_car_plates.no_known_plates': 'No known plates',
            'state.sensor.formatted_car_plates.manager_unavailable': 'PlateManager unavailable',
        }
        
        result = fallbacks.get(key, key)
        if kwargs:
            try:
                result = result.format(**kwargs)
            except:
                pass
        return result

    async def async_added_to_hass(self):
        """When sensor is added to HA."""
        _LOGGER.info(f"Sensor {self._attr_unique_id}: initialization started")
        
        # Check PlateManager availability
        plate_manager = self.hass.data.get(DOMAIN, {}).get('plate_manager')
        if plate_manager:
            _LOGGER.info(f"Sensor {self._attr_unique_id}: PlateManager is available")
        else:
            _LOGGER.error(f"Sensor {self._attr_unique_id}: PlateManager IS NOT available!")

        # Listen to PlateManager changes via events
        self.hass.bus.async_listen('enhanced_platerecognizer_plate_added', self._handle_plate_change)
        self.hass.bus.async_listen('enhanced_platerecognizer_plate_removed', self._handle_plate_change)
        _LOGGER.info(f"Sensor {self._attr_unique_id}: registered PlateManager events listening")

        # Also listen to input_select changes for backup
        async_track_state_change_event(
            self.hass,
            'input_select.remove_plate',
            self._handle_state_change
        )

        self._update_attributes()
        self.async_write_ha_state()
        _LOGGER.info(f"Sensor {self._attr_unique_id}: initialization completed")

    @callback
    def _handle_plate_change(self, event):
        """Handle plate changes via PlateManager."""
        _LOGGER.info(f"Sensor {self._attr_unique_id}: received plate change event")
        self._update_attributes()
        self.async_write_ha_state()

    @callback
    def _handle_state_change(self, event):
        """Handle input_select state change (backup)."""
        _LOGGER.info(f"Sensor {self._attr_unique_id}: received input_select state change")
        self._update_attributes()
        self.async_write_ha_state()

    def _update_attributes(self):
        """Update attributes with plates and owners."""
        _LOGGER.debug(f"Sensor {self._attr_unique_id}: _update_attributes called")
        
        plate_manager = self.hass.data.get(DOMAIN, {}).get('plate_manager')
        if plate_manager:
            _LOGGER.debug(f"Sensor {self._attr_unique_id}: PlateManager available, getting plates")
            plates_dict = plate_manager.get_all_plates()
            _LOGGER.info(f"Sensor {self._attr_unique_id}: retrieved {len(plates_dict) if plates_dict else 0} plates")
            
            if plates_dict:
                sorted_plates = sorted(plates_dict.items())
                formatted_list = '\n'.join([f"{plate} - {owner}" for plate, owner in sorted_plates])
                self._attr_extra_state_attributes = {
                    'formatted_list': formatted_list,
                    'total_plates': len(plates_dict)
                }
                self._attr_state = self._get_translation('state.sensor.formatted_car_plates.known_plates_count', count=len(plates_dict))
            else:
                self._attr_extra_state_attributes = {
                    'formatted_list': self._get_translation('state.sensor.formatted_car_plates.no_known_plates'), 
                    'total_plates': 0
                }
                self._attr_state = self._get_translation('state.sensor.formatted_car_plates.known_plates_count', count=0)
        else:
            _LOGGER.error(f"Sensor {self._attr_unique_id}: PlateManager not available in _update_attributes")
            self._attr_extra_state_attributes = {
                'formatted_list': self._get_translation('state.sensor.formatted_car_plates.manager_unavailable'), 
                'total_plates': 0
            }
            self._attr_state = self._get_translation('state.sensor.formatted_car_plates.manager_unavailable')

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_state

    @property
    def should_poll(self):
        """No polling needed."""
        return False


class LastRecognizedCarSensor(RestoreEntity, SensorEntity):
    """Sensor remembering last recognized plates."""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._attr_name = "Last recognized plates"
        self._attr_unique_id = "last_recognized_car"
        self.entity_id = "sensor.last_recognized_car"
        self._attr_native_value = self._get_translation('state.sensor.last_recognized_car.no_recognized')
        self._last_update_source = None

    def _get_translation(self, key: str, **kwargs) -> str:
        """Get translated text based on current language setting."""
        try:
            language = self.hass.config.language if self.hass else 'en'
            if language != 'pl':
                language = 'en'
            
            # Try to get translations from hass.data or fallback to hardcoded
            translations = self.hass.data.get(DOMAIN, {}).get('translations', {}).get(language, {})
            
            # Navigate through translation structure
            keys = key.split('.')
            current = translations
            for k in keys:
                if isinstance(current, dict) and k in current:
                    current = current[k]
                else:
                    # Fallback to English hardcoded values
                    return self._get_fallback_translation(key, **kwargs)
            
            # Format with provided kwargs if it's a string
            if isinstance(current, str) and kwargs:
                return current.format(**kwargs)
            return current if isinstance(current, str) else self._get_fallback_translation(key, **kwargs)
            
        except Exception as e:
            _LOGGER.debug(f"Translation error for key '{key}': {e}")
            return self._get_fallback_translation(key, **kwargs)

    def _get_fallback_translation(self, key: str, **kwargs) -> str:
        """Fallback translations when translation system fails."""
        fallbacks = {
            'state.sensor.last_recognized_car.no_recognized': 'No recognized plates',
        }
        
        result = fallbacks.get(key, key)
        if kwargs:
            try:
                result = result.format(**kwargs)
            except:
                pass
        return result

    async def async_added_to_hass(self):
        """Restore previous state and start listening to changes."""
        await super().async_added_to_hass()
        _LOGGER.info(f"Sensor {self.entity_id}: initialization started")

        last_state = await self.async_get_last_state()
        if last_state and last_state.state:
            self._attr_native_value = last_state.state
            _LOGGER.info(f"Sensor {self.entity_id}: restored state: {last_state.state}")

        # Listen to event
        self.hass.bus.async_listen(
            'enhanced_platerecognizer_image_processed',
            self._handle_image_processed
        )
        _LOGGER.info(f"Sensor {self.entity_id}: registered event listening")

        self.async_write_ha_state()
        _LOGGER.info(f"Sensor {self.entity_id}: initialization completed")

    @callback
    def _handle_image_processed(self, event):
        """Handle image processing event."""
        _LOGGER.info(f"Sensor {self.entity_id}: received event, has_vehicles: {event.data.get('has_vehicles')}")
        
        # Prevent duplicates
        event_time = event.data.get('timestamp', '')
        if self._last_update_source == f"event_{event_time}":
            _LOGGER.debug(f"Sensor {self.entity_id}: duplicate event, ignoring")
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
                _LOGGER.info(f"Sensor {self.entity_id}: updated to: {self._attr_native_value}")
                self.async_write_ha_state()
            else:
                _LOGGER.debug(f"Sensor {self.entity_id}: no vehicles, not updating")

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_native_value

    @property
    def should_poll(self):
        """No polling needed."""
        return False


class RecognizedCarSensor(SensorEntity):
    """Recognized car sensor (checks if plates are on the known list)."""

    def __init__(self, hass: HomeAssistant):
        self.hass = hass
        self._attr_name = "Recognized Car"
        self._attr_unique_id = "recognized_car"
        self._attr_state = self._get_translation('state.sensor.recognized_car.no_plates')
        self._clear_task = None

    def _get_translation(self, key: str, **kwargs) -> str:
        """Get translated text based on current language setting."""
        try:
            language = self.hass.config.language if self.hass else 'en'
            if language != 'pl':
                language = 'en'
            
            # Try to get translations from hass.data or fallback to hardcoded
            translations = self.hass.data.get(DOMAIN, {}).get('translations', {}).get(language, {})
            
            # Navigate through translation structure
            keys = key.split('.')
            current = translations
            for k in keys:
                if isinstance(current, dict) and k in current:
                    current = current[k]
                else:
                    # Fallback to English hardcoded values
                    return self._get_fallback_translation(key, **kwargs)
            
            # Format with provided kwargs if it's a string
            if isinstance(current, str) and kwargs:
                return current.format(**kwargs)
            return current if isinstance(current, str) else self._get_fallback_translation(key, **kwargs)
            
        except Exception as e:
            _LOGGER.debug(f"Translation error for key '{key}': {e}")
            return self._get_fallback_translation(key, **kwargs)

    def _get_fallback_translation(self, key: str, **kwargs) -> str:
        """Fallback translations when translation system fails."""
        fallbacks = {
            'state.sensor.recognized_car.no_plates': 'No plates detected',
            'state.sensor.recognized_car.recognized': 'Recognized: {plates}',
            'state.sensor.recognized_car.not_recognized': 'Not recognized: {plates}',
        }
        
        result = fallbacks.get(key, key)
        if kwargs:
            try:
                result = result.format(**kwargs)
            except:
                pass
        return result

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        _LOGGER.info(f"Sensor {self._attr_unique_id}: initialization started")
        
        # Check PlateManager availability
        plate_manager = self.hass.data.get(DOMAIN, {}).get("plate_manager")
        if plate_manager:
            _LOGGER.info(f"Sensor {self._attr_unique_id}: PlateManager is available")
        else:
            _LOGGER.error(f"Sensor {self._attr_unique_id}: PlateManager IS NOT available!")

        # Listen to event
        self.hass.bus.async_listen(
            'enhanced_platerecognizer_image_processed',
            self._handle_image_processed
        )
        _LOGGER.info(f"Sensor {self._attr_unique_id}: registered event listening")

    @callback
    def _handle_image_processed(self, event):
        """Handle image processing event."""
        _LOGGER.info(f"Sensor {self._attr_unique_id}: received event, has_vehicles: {event.data.get('has_vehicles')}")

        if not event.data.get('has_vehicles'):
            _LOGGER.debug(f"Sensor {self._attr_unique_id}: no vehicles, ignoring")
            return

        vehicles = event.data.get('vehicles', [])
        plates = [v.get('plate').upper() for v in vehicles if v.get('plate') is not None]

        if not plates:
            _LOGGER.debug(f"Sensor {self._attr_unique_id}: no plates, ignoring")
            return

        _LOGGER.info(f"Sensor {self._attr_unique_id}: processing plates: {plates}")

        plate_manager = self.hass.data.get(DOMAIN, {}).get("plate_manager")
        if not plate_manager:
            _LOGGER.error(f"Sensor {self._attr_unique_id}: PlateManager not available during processing!")
            return

        # Cancel previous task
        if self._clear_task and not self._clear_task.done():
            self._clear_task.cancel()

        recognized = [p for p in plates if plate_manager.is_plate_known(p)]
        if recognized:
            # Get owners for all recognized plates – CHANGE: Use corrected plate from plates.yaml
            owners_info = []
            for plate in recognized:
                corrected_plate = plate_manager.get_corrected_plate(plate)  # Get version from plates.yaml (with tolerate_one_mistake)
                owner = plate_manager.get_plate_owner(corrected_plate)  # Get owner based on corrected plate
                owners_info.append(f"{corrected_plate} ({owner})")  # CHANGE: Use corrected_plate instead of original plate

            self._attr_state = self._get_translation('state.sensor.recognized_car.recognized', plates=', '.join(owners_info))
            _LOGGER.info(f"Sensor {self._attr_unique_id}: recognized plates: {self._attr_state}")
        else:
            self._attr_state = self._get_translation('state.sensor.recognized_car.not_recognized', plates=', '.join(plates))
            _LOGGER.info(f"Sensor {self._attr_unique_id}: plates not recognized: {self._attr_state}")

        self.async_write_ha_state()

        # Clear after 10s
        self._clear_task = self.hass.async_create_task(self._clear_after_delay())

    async def _clear_after_delay(self):
        """Clear state after 10 seconds."""
        try:
            await asyncio.sleep(10)
            self._attr_state = self._get_translation('state.sensor.recognized_car.no_plates')
            _LOGGER.info(f"Sensor {self._attr_unique_id}: state cleared after 10s")
            self.async_write_ha_state()
        except asyncio.CancelledError:
            _LOGGER.debug(f"Sensor {self._attr_unique_id}: clear task cancelled")
            pass

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._attr_state

    @property
    def should_poll(self):
        """No polling needed."""
        return False
