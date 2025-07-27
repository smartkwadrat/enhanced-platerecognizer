"""Enhanced Plate Recognizer integration."""

import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers import discovery

from .plate_manager import PlateManager

_LOGGER = logging.getLogger(__name__)

DOMAIN = "enhanced_platerecognizer"

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Enhanced Plate Recognizer integration."""
    _LOGGER.info("Enhanced Plate Recognizer: Setting up integration")
    
    # KLUCZOWE: Inicjalizuj hass.data dla domeny
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    
    # KLUCZOWE: Utwórz i zarejestruj PlateManager
    try:
        # POPRAWKA: Przekaż config (lub pusty dict jeśli config nie zawiera naszej domeny)
        domain_config = config.get(DOMAIN, {})
        plate_manager = PlateManager(hass, domain_config)
        hass.data[DOMAIN]["plate_manager"] = plate_manager
        _LOGGER.info("PlateManager został pomyślnie zarejestrowany w hass.data")
               
    except Exception as e:
        _LOGGER.error(f"Błąd podczas inicjalizacji PlateManager: {e}")
        return False

    # NOWOŚĆ: Jawnie załaduj image_processing PRZED sensorami
    await discovery.async_load_platform(hass, Platform.IMAGE_PROCESSING, DOMAIN, {}, config)

    # Jawnie załaduj sensor platform
    await discovery.async_load_platform(hass, Platform.SENSOR, DOMAIN, {}, config)
    _LOGGER.info("Enhanced Plate Recognizer: Sensor platform loaded")
    
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True
