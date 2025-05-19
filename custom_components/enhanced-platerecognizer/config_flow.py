"""Config flow for Enhanced PlateRecognizer."""
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class EnhancedPlateRecognizerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Enhanced PlateRecognizer."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        # Sprawdź, czy integracja nie jest już skonfigurowana przez UI (pozwól na jeden wpis UI)
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            # Nie zbieramy żadnych danych, tworzymy pusty wpis
            # jako znacznik, że integracja została "dodana" przez UI.
            # Tytuł może być stały lub oparty na DOMAIN.
            _LOGGER.info("Enhanced PlateRecognizer: Tworzenie pustego ConfigEntry z UI.")
            return self.async_create_entry(title="Enhanced Plate Recognizer", data={})

        # Pokaż formularz informacyjny
        return self.async_show_form(
            step_id="user",
            description_placeholders={
                "yaml_config_note": (
                    "Główna konfiguracja tej integracji (API token, lista kamer itp.) "
                    "odbywa się w pliku `configuration.yaml` w sekcji `image_processing`.\n\n"
                    "Ten krok jedynie rejestruje integrację w interfejsie użytkownika. "
                    "Upewnij się, że konfiguracja YAML jest poprawna, zanim przejdziesz dalej."
                )
            },
            # Nie potrzebujemy data_schema, jeśli nie zbieramy danych od użytkownika
            data_schema=None
        )
