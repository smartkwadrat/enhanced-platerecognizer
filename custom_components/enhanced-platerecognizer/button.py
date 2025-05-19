"""Obsługa przycisków dla Enhanced PlateRecognizer."""

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    CONF_CAMERAS_CONFIG,
    CONF_CAMERA_ENTITY_ID,
    CONF_CAMERA_FRIENDLY_NAME,
)

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Skonfiguruj przyciski z wpisu konfiguracyjnego."""
    entry_data_config = hass.data[DOMAIN].get(config_entry.entry_id)
    if not entry_data_config:
        _LOGGER.error(
            f"Konfiguracja dla wpisu {config_entry.entry_id} nie znaleziona w hass.data[DOMAIN]. "
            f"Nie można skonfigurować encji przycisków."
        )
        return

    cameras_config_list = entry_data_config.get(CONF_CAMERAS_CONFIG, [])
    if not isinstance(cameras_config_list, list):
        _LOGGER.warning(
            f"Oczekiwano listy dla '{CONF_CAMERAS_CONFIG}' w wpisie {config_entry.entry_id}, "
            f"otrzymano {type(cameras_config_list)}. Pominięcie tworzenia przycisków."
        )
        return

    entities = []
    for camera_conf in cameras_config_list:
        if not isinstance(camera_conf, dict):
            _LOGGER.warning(f"Element konfiguracji kamery nie jest słownikiem: {camera_conf}. Pomijanie.")
            continue
        camera_entity_id = camera_conf.get(CONF_CAMERA_ENTITY_ID)
        if not camera_entity_id:
            _LOGGER.warning(f"Brak '{CONF_CAMERA_ENTITY_ID}' w konfiguracji kamery: {camera_conf}. Pomijanie.")
            continue
        camera_friendly_name = camera_conf.get(CONF_CAMERA_FRIENDLY_NAME)
        entities.append(
            PlateRecognitionButton(
                hass,
                config_entry,
                camera_entity_id,
                camera_friendly_name
            )
        )

    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.debug(
            f"Nie utworzono żadnych encji przycisków dla wpisu {config_entry.entry_id}, "
            f"prawdopodobnie brak skonfigurowanych kamer."
        )

class PlateRecognitionButton(ButtonEntity):
    """Przycisk do uruchamiania rozpoznawania tablic dla określonej kamery."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        camera_entity_id: str,
        camera_friendly_name_from_config: str | None
    ):
        """Inicjalizacja przycisku."""
        self.hass = hass
        self._config_entry = config_entry
        self._camera_entity_id = camera_entity_id

        # Ustalanie nazwy wyświetlanej dla przycisku
        if camera_friendly_name_from_config:
            camera_display_name = camera_friendly_name_from_config
        else:
            camera_state = hass.states.get(self._camera_entity_id)
            if camera_state and camera_state.name:
                camera_display_name = camera_state.name
            else:
                camera_display_name = self._camera_entity_id.split(".")[-1]

        self._attr_name = f"Rozpoznaj tablice - {camera_display_name}"
        self._attr_unique_id = f"{DOMAIN}_button_{self._camera_entity_id.replace('.', '_')}_{self._config_entry.entry_id}"

    @property
    def device_info(self) -> DeviceInfo:
        """Zwraca informacje o urządzeniu powiązanym z tym przyciskiem."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"platerecognizer_{self._config_entry.entry_id}")},
            name=self._config_entry.title,
            manufacturer="SmartKwadrat",
            model="Enhanced Plate Recognizer",
            sw_version=self.hass.data[DOMAIN].get("version", "N/A"),
        )

    async def async_press(self) -> None:
        """Obsługuje naciśnięcie przycisku."""
        _LOGGER.debug(f"Naciśnięto przycisk dla kamery {self._camera_entity_id} (wpis: {self._config_entry.entry_id})")
        
        # Szukaj encji image_processing o entity_id pasującym do wzorca dla tej kamery
        target_entity_pattern = f"image_processing.platerecognizer_{self._camera_entity_id.split('.')[-1]}"
        _LOGGER.debug(f"Szukam encji pasującej do wzorca: {target_entity_pattern}")
        
        # Znajdź wszystkie encje image_processing
        all_entities = self.hass.states.async_all("image_processing")
        target_entity = None
        
        for entity in all_entities:
            if entity.entity_id.startswith(target_entity_pattern):
                target_entity = entity.entity_id
                _LOGGER.debug(f"Znaleziono pasującą encję: {target_entity}")
                break
        
        if target_entity:
            _LOGGER.info(
                f"Wywoływanie usługi enhanced_platerecognizer.scan dla encji: {target_entity}"
            )
            try:
                await self.hass.services.async_call(
                    "enhanced_platerecognizer",  # Zmieniono z "image_processing" na "enhanced_platerecognizer"
                    "scan",
                    {"entity_id": target_entity},
                    blocking=False
                )
            except Exception as e:
                _LOGGER.error(
                    f"Błąd podczas wywoływania usługi enhanced_platerecognizer.scan dla {target_entity}: {e}"
                )
        else:
            _LOGGER.error(
                f"Nie można znaleźć encji image_processing pasującej do wzorca: "
                f"{target_entity_pattern}. "
                f"Sprawdź, czy encja image_processing dla kamery {self._camera_entity_id} "
                f"została poprawnie utworzona."
            )
