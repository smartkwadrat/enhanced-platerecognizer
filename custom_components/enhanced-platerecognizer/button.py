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
    CONF_SOURCE,
    _LOGGER,
)

async def async_setup_entry(hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    """Skonfiguruj przyciski z wpisu konfiguracyjnego."""
    config = {**config_entry.data, **config_entry.options}
    
    entities = []
    for camera_entity in config.get(CONF_SOURCE, []):
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
        
        camera_name = hass.states.get(camera_entity).name if hass.states.get(camera_entity) else camera_entity.split(".")[-1]
        self._attr_name = f"Rozpoznaj tablice - {camera_name}"
        self._attr_unique_id = f"{DOMAIN}_button_{camera_entity}_{config_entry.entry_id}"
    
    @property
    def device_info(self) -> DeviceInfo:
        """Zwraca informacje o urządzeniu nadrzędnym."""
        return {
            "identifiers": {(DOMAIN, f"platerecognizer_{self._config_entry.entry_id}")},
            "name": f"Plate Recognizer {self._config.get(CONF_NAME, 'Default')}",
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
