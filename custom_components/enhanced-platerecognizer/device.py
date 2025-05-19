"""Urządzenia (device) dla Enhanced PlateRecognizer."""

import logging

from homeassistant.helpers.entity import DeviceEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback, async_get_current_platform
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Skonfiguruj urządzenia dla Enhanced PlateRecognizer."""
    platform = async_get_current_platform()

    # Rejestracja serwisu czyszczenia zdjęć na poziomie urządzenia
    platform.async_register_entity_service(
        "clean_images",
        {
            "folder": str,
            "max_images": int,
        },
        "async_clean_images_service",
    )

    # Pobierz wszystkie encje image_processing dla tej integracji
    image_processing_entities = []
    for entity_component in hass.data.get("image_processing", {}).values():
        if hasattr(entity_component, "entities"):
            for entity in entity_component.entities:
                # Sprawdź czy encja należy do tej integracji po platform_name
                if getattr(entity.platform, "platform_name", None) == DOMAIN:
                    image_processing_entities.append(entity)

    # Utwórz urządzenie dla każdej encji image_processing
    devices = [
        EnhancedPlateRecognizerDevice(entity, config_entry.entry_id)
        for entity in image_processing_entities
    ]

    if devices:
        async_add_entities(devices)
    else:
        _LOGGER.debug(
            f"Nie utworzono żadnych urządzeń dla wpisu {config_entry.entry_id} (brak encji image_processing)."
        )

class EnhancedPlateRecognizerDevice(DeviceEntity):
    """Reprezentacja urządzenia Enhanced PlateRecognizer."""

    def __init__(self, image_processing_entity, config_entry_id):
        """Inicjalizacja urządzenia."""
        self._config_entry_id = config_entry_id
        self._image_processing_entity = image_processing_entity
        self._name = image_processing_entity.name
        self._camera_entity_id = image_processing_entity.camera_entity
        self._attr_unique_id = f"{self._name}_device_{self._config_entry_id}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"{self._name}_{self._config_entry_id}")},
            "name": self._name,
            "manufacturer": "SmartKwadrat",
            "model": "Enhanced Plate Recognizer",
            "configuration_url": f"/config/integrations/integration/{DOMAIN}",
        }
        self._attr_has_entity_name = True
        self._attr_name = None

    @property
    def device_info(self):
        """Informacje o urządzeniu."""
        return self._attr_device_info

    @property
    def unique_id(self):
        """Unikalny ID urządzenia."""
        return self._attr_unique_id

    @property
    def name(self):
        """Nazwa urządzenia."""
        return self._name

    @property
    def available(self):
        """Czy urządzenie jest dostępne."""
        return True

    @property
    def should_poll(self):
        """Nie odpytuj urządzenia."""
        return False

    async def async_clean_images_service(self, folder=None, max_images=None):
        """Serwis do czyszczenia zdjęć."""
        _LOGGER.debug(f"Wywołano serwis clean_images z folderem: {folder}, max_images: {max_images}")

        # Pobierz folder i max_images z konfiguracji, jeśli nie zostały podane
        if not folder:
            folder = getattr(self._image_processing_entity, "_save_file_folder", None)
        if not max_images:
            max_images = getattr(self._image_processing_entity, "_max_images", None)

        if not folder:
            _LOGGER.warning("Brak folderu do czyszczenia zdjęć.")
            return
        if not max_images:
            _LOGGER.warning("Brak maksymalnej liczby zdjęć do pozostawienia.")
            return

        from . import async_clean_old_images
        await async_clean_old_images(self.hass, folder, max_images)
