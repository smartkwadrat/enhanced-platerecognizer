"""Enhanced Plate Recognizer integration."""
import logging
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform

DOMAIN = "enhanced_platerecognizer"
PLATFORMS = [Platform.SENSOR, Platform.IMAGE_PROCESSING]

async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Enhanced Plate Recognizer integration."""
    
    # Załaduj platformy
    await hass.helpers.discovery.async_load_platform(Platform.SENSOR, DOMAIN, {}, config)
    await hass.helpers.discovery.async_load_platform(Platform.IMAGE_PROCESSING, DOMAIN, {}, config)
    
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return True
