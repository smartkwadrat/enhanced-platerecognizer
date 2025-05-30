"""Enhanced Plate Recognizer integration."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.helpers import discovery

_LOGGER = logging.getLogger(__name__)
DOMAIN = "enhanced_platerecognizer"

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Enhanced Plate Recognizer integration."""
    _LOGGER.info("Enhanced Plate Recognizer: Setting up integration")
    
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