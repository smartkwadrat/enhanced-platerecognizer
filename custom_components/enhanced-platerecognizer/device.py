"""Urządzenia (device) dla Enhanced PlateRecognizer."""
import logging

# Importy potrzebne dla standardowej sygnatury async_setup_entry
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo # Może być potrzebne, jeśli będziesz tworzyć DeviceEntity

# Importuj DOMAIN, aby można było go użyć w logach lub przyszłej logice
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> bool:
    """
    Konfiguracja platformy 'device' dla Enhanced PlateRecognizer poprzez ConfigEntry.

    W obecnej architekturze integracji, gdzie:
    - Konfiguracja odbywa się głównie przez plik `configuration.yaml`.
    - `config_flow` w `manifest.json` jest ustawione na `false`.
    - Centralne urządzenie dla całej integracji jest tworzone programatycznie
      w pliku `__init__.py` podczas inicjalizacji integracji.
    - Encje (takie jak przyciski) są bezpośrednio powiązywane z tym centralnym urządzeniem
      poprzez atrybut `device_info` w ich definicjach.

    Ta funkcja (`device.async_setup_entry`) jest standardowym punktem wejścia dla platformy
    'device', gdy Home Assistant przetwarza ConfigEntry. Jednak w przypadku tej integracji,
    ponieważ `config_flow` jest `false` i nie są tworzone ConfigEntries przez interfejs
    użytkownika dla głównej konfiguracji, ta funkcja zazwyczaj nie będzie wywoływana
    w standardowym przepływie konfiguracji YAML.

    Jeśli w przyszłości integracja zaczęłaby wykorzystywać ConfigEntry do zarządzania
    specyficznymi aspektami, które mogłyby wymagać dedykowanych encji typu `DeviceEntity`
    tworzonych przez tę platformę, odpowiednia logika zostałaby tutaj zaimplementowana.

    Obecnie ta platforma nie tworzy żadnych dodatkowych urządzeń ani encji urządzeń,
    ponieważ zarządzanie urządzeniami odbywa się w sposób opisany powyżej.
    """
    _LOGGER.debug(
        "Enhanced PlateRecognizer (%s): device.async_setup_entry zostało wywołane dla wpisu konfiguracyjnego ID: %s. "
        "Integracja jest skonfigurowana przez YAML, a główne urządzenie jest tworzone w __init__.py. "
        "Ta funkcja obecnie nie tworzy dodatkowych urządzeń ani encji urządzeń z poziomu platformy 'device' "
        "dla wpisów konfiguracyjnych.",
        DOMAIN,
        config_entry.entry_id
    )

    # W tym miejscu nie ma potrzeby dodawania encji (async_add_entities),
    # ponieważ encje przycisków są zarządzane przez platformę 'button',
    # a encje image_processing przez platformę 'image_processing'.
    # Wszystkie te encje są powiązane z centralnym urządzeniem zdefiniowanym w __init__.py.

    # Należy zwrócić True, aby wskazać Home Assistant, że platforma
    # została pomyślnie "załadowana", nawet jeśli nie wykonuje
    # żadnych konkretnych operacji dodawania encji w tym kontekście.
    return True

# Poniżej mógłby znajdować się kod definiujący klasy dziedziczące po DeviceEntity,
# gdyby ta platforma miała tworzyć własne, specyficzne encje urządzeń.
# W obecnej konfiguracji nie jest to potrzebne.
#
# Przykład (kod nieaktywny, tylko dla ilustracji):
#
# class ExampleDeviceEntity(DeviceEntity):
#     """Przykładowa encja urządzenia dla tej platformy."""
#
#     def __init__(self, hass: HomeAssistant, config_entry_id: str, device_name: str):
#         """Inicjalizacja przykładowej encji urządzenia."""
#         self._hass = hass
#         self._name = f"EPR Device - {device_name}"
#         self._attr_unique_id = f"{DOMAIN}_{config_entry_id}_{device_name.lower().replace(' ', '_')}"
#
#         # Informacje o urządzeniu, które powiążą tę encję z urządzeniem
#         # stworzonym przez ConfigEntry lub centralnym urządzeniem.
#         # Jeśli chcemy powiązać z centralnym urządzeniem:
#         self._attr_device_info = DeviceInfo(
#             identifiers={(DOMAIN, DOMAIN)}, # Identyfikatory centralnego urządzenia
#         )
#         # Lub jeśli chcemy powiązać z urządzeniem stworzonym przez ConfigEntry (jeśli by istniało):
#         # self._attr_device_info = DeviceInfo(
#         #     identifiers={(DOMAIN, config_entry_id)},
#         # )
#
#     @property
#     def name(self) -> str:
#         """Zwraca nazwę encji."""
#         return self._name
#
#     # ... inne wymagane właściwości i metody dla DeviceEntity ...

