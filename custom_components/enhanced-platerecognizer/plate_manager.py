"""Plate Manager - przeniesiony z AppDaemon."""
import logging
import os
import yaml
from typing import Dict, List, Any
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.const import EVENT_HOMEASSISTANT_START

_LOGGER = logging.getLogger(__name__)

class PlateManager:
    """Zarządza tablicami rejestracyjnymi."""
    
    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]):
        """Inicjalizuj PlateManager."""
        self.hass = hass
        self.config = config
        self.tolerate_one_mistake = config.get('tolerate_one_mistake', True)
        
        # Ścieżka do pliku plates.yaml w katalogu integracji
        integration_dir = os.path.dirname(__file__)
        self.plates_file = os.path.join(integration_dir, 'plates.yaml')
        
        # Załaduj tablice
        self.known_plates = self._load_plates()
        
        # Zarejestruj event listeners
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, self._setup_listeners)
    
    def _load_plates(self) -> Dict[str, str]:
        """Załaduj tablice z pliku YAML."""
        try:
            if os.path.exists(self.plates_file):
                with open(self.plates_file, 'r', encoding='utf-8') as file:
                    data = yaml.safe_load(file) or {}
                    return data.get('plates', {})
            else:
                # Utwórz pusty plik jeśli nie istnieje
                self._save_plates({})
                return {}
        except Exception as e:
            _LOGGER.error(f"Błąd podczas ładowania tablic: {e}")
            return {}
    
    def _save_plates(self, plates: Dict[str, str]):
        """Zapisz tablice do pliku YAML."""
        try:
            data = {'plates': plates}
            with open(self.plates_file, 'w', encoding='utf-8') as file:
                yaml.dump(data, file, default_flow_style=False, allow_unicode=True)
            self.known_plates = plates
            # Uruchom aktualizację input_select asynchronicznie
            self.hass.async_create_task(self._update_input_select())
        except Exception as e:
            _LOGGER.error(f"Błąd podczas zapisywania tablic: {e}")
    
    async def _setup_listeners(self, event):
        """Ustaw nasłuchiwanie zmian stanu."""
        # Nasłuchuj zmian w input_text dla dodawania tablic
        async_track_state_change_event(
            self.hass,
            ['input_text.add_new_plate', 'input_text.add_plate_owner'],
            self._handle_add_plate
        )
        
        # Nasłuchuj zmian w input_select dla usuwania tablic
        async_track_state_change_event(
            self.hass,
            'input_select.remove_plate',
            self._handle_remove_plate
        )
        
        # Inicjalizuj input_select
        await self._update_input_select()
    
    @callback
    async def _handle_add_plate(self, event):
        """Obsłuż dodawanie nowej tablicy."""
        plate = self.hass.states.get('input_text.add_new_plate')
        owner = self.hass.states.get('input_text.add_plate_owner')
        
        if plate and owner and plate.state and owner.state:
            plate_number = plate.state.strip().upper()
            owner_name = owner.state.strip()
            
            if plate_number and owner_name:
                # Dodaj tablicę
                new_plates = self.known_plates.copy()
                new_plates[plate_number] = owner_name
                self._save_plates(new_plates)
                
                # Wyczyść pola input
                await self.hass.services.async_call(
                    'input_text', 'set_value',
                    {'entity_id': 'input_text.add_new_plate', 'value': ''}
                )
                await self.hass.services.async_call(
                    'input_text', 'set_value',
                    {'entity_id': 'input_text.add_plate_owner', 'value': ''}
                )
                
                _LOGGER.info(f"Dodano tablicę: {plate_number} -> {owner_name}")
    
    @callback
    async def _handle_remove_plate(self, event):
        """Obsłuż usuwanie tablicy."""
        if event.data.get('new_state') is None:
            return
            
        selected = event.data['new_state'].state
        if selected and selected != "Brak tablic":
            # Usuń tablicę
            new_plates = self.known_plates.copy()
            if selected in new_plates:
                del new_plates[selected]
                self._save_plates(new_plates)
                _LOGGER.info(f"Usunięto tablicę: {selected}")
    
    async def _update_input_select(self):
        """Zaktualizuj opcje w input_select."""
        try:
            options = ["Brak tablic"] + list(self.known_plates.keys())
            
            await self.hass.services.async_call(
                'input_select', 'set_options',
                {
                    'entity_id': 'input_select.remove_plate',
                    'options': options
                }
            )
        except Exception as e:
            _LOGGER.error(f"Błąd podczas aktualizacji input_select: {e}")
    
    def get_plate_owner(self, plate: str) -> str:
        """Zwróć właściciela tablicy."""
        if self.tolerate_one_mistake:
            # Implementuj logikę tolerancji błędów
            for known_plate in self.known_plates:
                if self._plates_similar(plate, known_plate):
                    return self.known_plates[known_plate]
        
        return self.known_plates.get(plate.upper(), "Nieznany")
    
    def _plates_similar(self, plate1: str, plate2: str) -> bool:
        """Sprawdź czy tablice są podobne (tolerancja 1 błędu)."""
        if len(plate1) != len(plate2):
            return False
        
        differences = sum(1 for a, b in zip(plate1.upper(), plate2.upper()) if a != b)
        return differences <= 1
    
    def is_plate_known(self, plate: str) -> bool:
        """Sprawdź czy tablica jest znana."""
        if plate.upper() in self.known_plates:
            return True
        
        if self.tolerate_one_mistake:
            for known_plate in self.known_plates:
                if self._plates_similar(plate, known_plate):
                    return True
        
        return False
    
    def get_all_plates(self) -> Dict[str, str]:
        """Zwróć wszystkie znane tablice."""
        return self.known_plates.copy()
    
    def get_plates_count(self) -> int:
        """Zwróć liczbę znanych tablic."""
        return len(self.known_plates)
