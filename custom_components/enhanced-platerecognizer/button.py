"""Obsługa przycisków dla Enhanced PlateRecognizer."""
from typing import Any, Optional

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from . import DOMAIN
from .const import (
    CONF_NAME,
    CONF_CAMERAS_CONFIG,
    CONF_CAMERA_ENTITY_ID,
    CONF_NAME,
)

_LOGGER = logging.getLogger(__name__) 

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Skonfiguruj przyciski z wpisu konfiguracyjnego."""
    config = hass.data[DOMAIN][config_entry.entry_id]
    
    entities = []
    for camera_conf in config.get(CONF_CAMERAS_CONFIG, []):
        camera_entity = camera_conf[CONF_CAMERA_ENTITY_ID]
        entities.append(
            PlateRecognitionButton(
                hass,
                config_entry,
                camera_entity,
                config,
            )
        )
    
    async_add_entities(entities)


class PlateRecognitionButton(ButtonEntity):
    """Przycisk do uruchamiania rozpoznawania tablic dla określonej kamery."""

    def __init__(self, hass, config_entry, camera_entity, config):
        """Inicjalizacja przycisku."""
        self.hass = hass
        self._config_entry = config_entry
        self._camera_entity = camera_entity
        self._config = config
        
        camera_state = hass.states.get(camera_entity)
        camera_name = camera_state.name if camera_state else camera_entity.split(".")[-1]
        self._attr_name = f"Rozpoznaj tablice - {camera_name}"
        self._attr_unique_id = f"{DOMAIN}_button_{camera_entity.replace('.', '_')}_{config_entry.entry_id}"
    
    @property
    def device_info(self) -> DeviceInfo:
        return {
            "identifiers": {(DOMAIN, f"platerecognizer_{self._config_entry.entry_id}")},
            "name": self._config_entry.title,
            "manufacturer": "Enhanced PlateRecognizer",
            "model": "API Integration",
        }
    
    async def async_press(self) -> None:
        """Obsługuje naciśnięcie przycisku."""
        _LOGGER.debug(f"Naciśnięto przycisk dla kamery {self._camera_entity}")
        
        # Wywołaj usługę image_processing.scan dla tej konkretnej kamery
        await self.hass.services.async_call(
            "image_processing",
            "scan",
            {"entity_id": f"image_processing.enhanced_platerecognizer_{self._camera_entity.split('.')[-1]}"},
        )
