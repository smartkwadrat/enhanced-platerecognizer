"""Plate Manager - przeniesiony z AppDaemon."""
import logging
import os
import yaml
import aiofiles
import aiofiles.os
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
        
        integration_dir = os.path.dirname(__file__)
        self.plates_file = os.path.join(integration_dir, 'plates.yaml')
        
        # Załaduj tablice asynchronicznie w setup_listeners
        self.known_plates = {}
        
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, self._setup_listeners)
    
    async def _load_plates(self) -> Dict[str, str]:
        """Załaduj tablice z pliku YAML asynchronicznie."""
        try:
            if await aiofiles.os.path.exists(self.plates_file):
                async with aiofiles.open(self.plates_file, 'r', encoding='utf-8') as file:
                    content = await file.read()
                    data = yaml.safe_load(content) or {}
                    return data.get('plates', {})
            else:
                await self._save_plates({})
                return {}
        except Exception as e:
            _LOGGER.error(f"Błąd podczas ładowania tablic: {e}")
            return {}
    
    async def _save_plates(self, plates: Dict[str, str]):
        """Zapisz tablice do pliku YAML asynchronicznie."""
        try:
            data = {'plates': plates}
            content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
            async with aiofiles.open(self.plates_file, 'w', encoding='utf-8') as file:
                await file.write(content)
            self.known_plates = plates
            await self._update_input_select()
            _LOGGER.info(f"Zapisano tablice: {list(plates.keys())}")
        except Exception as e:
            _LOGGER.error(f"Błąd podczas zapisywania tablic: {e}")
    
    async def _setup_listeners(self, event):
        """Ustaw nasłuchiwanie zmian stanu."""
        # Załaduj tablice asynchronicznie
        self.known_plates = await self._load_plates()
        _LOGGER.info(f"Załadowano {len(self.known_plates)} tablic")
        
        # Nasłuchuj zmian w input_text OSOBNO dla każdego
        async_track_state_change_event(
            self.hass,
            'input_text.add_new_plate',
            self._handle_plate_change
        )
        
        async_track_state_change_event(
            self.hass,
            'input_text.add_plate_owner',
            self._handle_owner_change
        )
        
        # Nasłuchuj zmian w input_select dla usuwania tablic
        async_track_state_change_event(
            self.hass,
            'input_select.remove_plate',
            self._handle_remove_plate
        )
        
        # Inicjalizuj input_select
        await self._update_input_select()
        _LOGGER.info("PlateManager listeners setup completed")
    
    @callback
    async def _handle_plate_change(self, event):
        """Obsłuż zmianę w input_text.add_new_plate."""
        new_state = event.data.get('new_state')
        old_state = event.data.get('old_state')
        
        # Sprawdź czy to rzeczywista zmiana (nie pusty -> pusty)
        if (new_state and new_state.state and 
            old_state and old_state.state != new_state.state):
            
            _LOGGER.info(f"Plate change detected: {new_state.state}")
            # Sprawdź czy mamy też właściciela i dodaj tablicę
            await self._try_add_plate()
    
    @callback  
    async def _handle_owner_change(self, event):
        """Obsłuż zmianę w input_text.add_plate_owner."""
        new_state = event.data.get('new_state')
        old_state = event.data.get('old_state')
        
        # Sprawdź czy to rzeczywista zmiana (nie pusty -> pusty)
        if (new_state and new_state.state and 
            old_state and old_state.state != new_state.state):
            
            _LOGGER.info(f"Owner change detected: {new_state.state}")
            # Sprawdź czy mamy też tablicę i dodaj tablicę
            await self._try_add_plate()
    
    async def _try_add_plate(self):
        """Spróbuj dodać tablicę jeśli mamy i tablicę i właściciela."""
        # Poczekaj chwilę żeby się upewnić że stany są aktualne
        await self.hass.async_add_executor_job(lambda: __import__('time').sleep(0.1))
        
        plate_state = self.hass.states.get('input_text.add_new_plate')
        owner_state = self.hass.states.get('input_text.add_plate_owner')
        
        if plate_state and owner_state and plate_state.state and owner_state.state:
            plate_number = plate_state.state.strip().upper()
            owner_name = owner_state.state.strip()
            
            if plate_number and owner_name:
                _LOGGER.info(f"Adding plate: {plate_number} -> {owner_name}")
                
                # Dodaj tablicę
                new_plates = self.known_plates.copy()
                new_plates[plate_number] = owner_name
                await self._save_plates(new_plates)
                
                # Wyczyść pola input - WAŻNE: dodaj małe opóźnienie
                await self.hass.async_add_executor_job(lambda: __import__('time').sleep(0.2))
                
                await self.hass.services.async_call(
                    'input_text', 'set_value',
                    {'entity_id': 'input_text.add_new_plate', 'value': ''},
                    blocking=True
                )
                await self.hass.services.async_call(
                    'input_text', 'set_value',
                    {'entity_id': 'input_text.add_plate_owner', 'value': ''},
                    blocking=True
                )
                
                _LOGGER.info(f"Dodano tablicę: {plate_number} -> {owner_name}")
                
                # Wymuś aktualizację UI
                self.hass.bus.async_fire('enhanced_platerecognizer_plate_added', {
                    'plate': plate_number,
                    'owner': owner_name
                })
    
    @callback
    async def _handle_remove_plate(self, event):
        """Obsłuż usuwanie tablicy."""
        new_state = event.data.get('new_state')
        old_state = event.data.get('old_state')
        
        if (new_state and old_state and 
            new_state.state != old_state.state and 
            new_state.state not in ["Brak tablic", "Wybierz tablice do usunięcia"]):
            
            selected = new_state.state
            _LOGGER.info(f"Remove plate selected: {selected}")
            
            # Usuń tablicę
            new_plates = self.known_plates.copy()
            if selected in new_plates:
                del new_plates[selected]
                await self._save_plates(new_plates)
                _LOGGER.info(f"Usunięto tablicę: {selected}")
                
                # Wymuś aktualizację UI
                self.hass.bus.async_fire('enhanced_platerecognizer_plate_removed', {
                    'plate': selected
                })
    
    async def _update_input_select(self):
        """Zaktualizuj opcje w input_select z poprawną domyślną opcją."""
        try:
            if not self.known_plates:
                # Puste plates.yaml - domyślnie "Brak tablic"
                options = ["Brak tablic"]
                default_option = "Brak tablic"
            else:
                # Mamy tablice - dodaj opcję wyboru + tablice
                options = ["Wybierz tablice do usunięcia"] + list(self.known_plates.keys())
                default_option = "Wybierz tablice do usunięcia"
            
            _LOGGER.info(f"Updating input_select with options: {options}, default: {default_option}")
            
            # Ustaw opcje
            await self.hass.services.async_call(
                'input_select', 'set_options',
                {
                    'entity_id': 'input_select.remove_plate',
                    'options': options
                },
                blocking=True
            )
            
            # Ustaw domyślną opcję
            await self.hass.services.async_call(
                'input_select', 'select_option',
                {
                    'entity_id': 'input_select.remove_plate', 
                    'option': default_option
                },
                blocking=True
            )
            
        except Exception as e:
            _LOGGER.error(f"Błąd podczas aktualizacji input_select: {e}")

    # Pozostałe metody bez zmian
    def get_plate_owner(self, plate: str) -> str:
        """Zwróć właściciela tablicy."""
        if self.tolerate_one_mistake:
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
