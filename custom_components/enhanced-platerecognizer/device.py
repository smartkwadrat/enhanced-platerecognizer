from homeassistant.helpers.entity import DeviceEntity
from homeassistant.core import callback
from homeassistant.helpers import entity_platform
from .const import DOMAIN
import logging

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Ustawia platformę device dla Enhanced PlateRecognizer."""

    platform = entity_platform.async_get_current_platform()
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
                if getattr(entity.platform, "platform_name", None) == DOMAIN:
                    image_processing_entities.append(entity)

    # Utwórz urządzenie dla każdej encji image_processing
    devices = [EnhancedPlateRecognizerDevice(entity) for entity in image_processing_entities]
    async_add_entities(devices)

class EnhancedPlateRecognizerDevice(DeviceEntity):
    """Reprezentacja urządzenia Enhanced PlateRecognizer."""

    def __init__(self, image_processing_entity):
        """Inicjalizacja urządzenia."""
        self._image_processing_entity = image_processing_entity
        self._name = image_processing_entity.name
        self._camera = image_processing_entity._camera
        self._attr_unique_id = f"{self._name}_device"
        self._attr_device_info = {
            "identifiers": {
                # Unikalny identyfikator urządzenia
                (DOMAIN, self._name)
            },
            "name": self._name,  # Nazwa urządzenia
            "manufacturer": "SmartKwadrat",  # Producent
            "model": "Enhanced PlateRecognizer",  # Model
            "sw_version": "0.1.6",  # Wersja oprogramowania
            "configuration_url": f"/config/integrations/integration/{DOMAIN}",
        }
        self._attr_has_entity_name = True
        self._attr_name = None  # Urządzenie nie ma nazwy, bazuje na nazwach encji

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
            folder = self._image_processing_entity._save_file_folder
        if not max_images:
            max_images = self._image_processing_entity._max_images

        if not folder:
            _LOGGER.warning("Brak folderu do czyszczenia zdjęć.")
            return

        if not max_images:
            _LOGGER.warning("Brak maksymalnej liczby zdjęć do pozostawienia.")
            return
        from . import async_clean_old_images
        # Wywołaj funkcję czyszczącą zdjęcia
        await async_clean_old_images(self.hass, folder, max_images)

