"""Obsługa przycisków dla Enhanced PlateRecognizer."""
import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers import entity_registry as er

from . import DOMAIN 
from .const import (
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

        # Pobierz przyjazną nazwę kamery z konfiguracji
        camera_friendly_name = camera_conf.get(CONF_CAMERA_FRIENDLY_NAME)

        entities.append(
            PlateRecognitionButton(
                hass,
                config_entry,
                camera_entity_id,
                camera_friendly_name # Przekaż przyjazną nazwę
            )
        )

    if entities:
        async_add_entities(entities)
    else:
        _LOGGER.debug(f"Nie utworzono żadnych encji przycisków dla wpisu {config_entry.entry_id}, "
                      f"prawdopodobnie brak skonfigurowanych kamer.")


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
        self._camera_entity_id = camera_entity_id # Nazwa atrybutu zmieniona dla spójności

        # Ustalanie nazwy wyświetlanej dla przycisku
        if camera_friendly_name_from_config:
            camera_display_name = camera_friendly_name_from_config
        else:
            camera_state = hass.states.get(self._camera_entity_id)
            if camera_state and camera_state.name:
                camera_display_name = camera_state.name
            else:
                # Ostateczny fallback na część entity_id kamery
                camera_display_name = self._camera_entity_id.split(".")[-1]

        self._attr_name = f"Rozpoznaj tablice - {camera_display_name}"
        # Unique ID musi być unikalne dla każdego przycisku
        self._attr_unique_id = f"{DOMAIN}_button_{self._camera_entity_id.replace('.', '_')}_{self._config_entry.entry_id}"

    @property
    def device_info(self) -> DeviceInfo:
        """Zwraca informacje o urządzeniu powiązanym z tym przyciskiem."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"platerecognizer_{self._config_entry.entry_id}")},
            name=self._config_entry.title, # Tytuł wpisu konfiguracyjnego
            manufacturer="Enhanced PlateRecognizer", # Można przenieść do stałych
            model="API Integration", # Można przenieść do stałych
            sw_version=self.hass.data[DOMAIN].get("version", "N/A")
        )

    async def async_press(self) -> None:
        """Obsługuje naciśnięcie przycisku."""
        _LOGGER.debug(f"Naciśnięto przycisk dla kamery {self._camera_entity_id} (wpis: {self._config_entry.entry_id})")

        target_image_processing_unique_id = f"{DOMAIN}_{self._camera_entity_id.replace('.', '_')}_{self._config_entry.entry_id}"

        entity_reg = er.async_get(self.hass)
        target_entity = entity_reg.async_get_entity_id("image_processing", DOMAIN, target_image_processing_unique_id)

        if target_entity:
            _LOGGER.info(
                f"Wywoływanie usługi image_processing.scan dla encji: {target_entity} "
                f"(unique_id: {target_image_processing_unique_id})"
            )
            try:
                await self.hass.services.async_call(
                    "image_processing",
                    "scan",
                    {"entity_id": target_entity},
                    blocking=False
                )
            except Exception as e:
                _LOGGER.error(
                    f"Błąd podczas wywoływania usługi image_processing.scan dla {target_entity}: {e}"
                )
        else:
            _LOGGER.error(
                f"Nie można znaleźć encji image_processing w rejestrze dla unique_id: "
                f"{target_image_processing_unique_id}. "
                f"Sprawdź, czy encja image_processing dla kamery {self._camera_entity_id} "
                f"została poprawnie utworzona i ma pasujący unique_id."
            )

