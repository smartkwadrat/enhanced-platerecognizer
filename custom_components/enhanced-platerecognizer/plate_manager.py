"""Plate Manager - migrated from AppDaemon."""

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

DOMAIN = "enhanced_platerecognizer"

class PlateManager:
    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]):
        """Initialize PlateManager."""
        self.hass = hass
        self.config = config
        self.tolerate_one_mistake = config.get('tolerate_one_mistake', True)
        
        # Changed path - now points to /config/plates.yaml
        file_name = "plates.yaml"
        self.plates_file = self.hass.config.path(file_name)
        
        # Load plates asynchronously in setup_listeners
        self.known_plates = {}
        
        hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, self._setup_listeners)

    def _get_translation(self, key: str, **kwargs) -> str:
        """Get translated text based on current language setting."""
        language = self.hass.config.language if self.hass else 'en'
        _LOGGER.debug(f"PlateManager detected language: {language} for key: {key}")
        
        if language == 'pl':
            return self._get_polish_translation(key, **kwargs)
        else:
            return self._get_fallback_translation(key, **kwargs)

    def _get_polish_translation(self, key: str, **kwargs) -> str:
        """Polish translations hardcoded."""
        polish_translations = {
            'component.enhanced_platerecognizer.plate_manager.no_plates': 'Brak tablic',
            'component.enhanced_platerecognizer.plate_manager.select_to_delete': 'Wybierz tablice do usunięcia',
        }
        
        result = polish_translations.get(key, self._get_fallback_translation(key, **kwargs))
        if kwargs:
            try:
                result = result.format(**kwargs)
            except:
                pass
        return result

    def _get_fallback_translation(self, key: str, **kwargs) -> str:
        """Fallback translations when translation system fails."""
        fallbacks = {
            'component.enhanced_platerecognizer.plate_manager.no_plates': 'No plates',
            'component.enhanced_platerecognizer.plate_manager.select_to_delete': 'Select plates to delete',
        }
        
        result = fallbacks.get(key, key)
        if kwargs:
            try:
                result = result.format(**kwargs)
            except:
                pass
        return result

    async def _load_plates(self) -> Dict[str, str]:
        """Load plates from YAML file asynchronously."""
        try:
            if await aiofiles.os.path.exists(self.plates_file):
                async with aiofiles.open(self.plates_file, 'r', encoding='utf-8') as file:
                    content = await file.read()
                    if not content.strip():  # Empty file
                        return {}
                    data = yaml.safe_load(content)
                    if data is None:  # Invalid YAML
                        return {}
                    return data.get('plates', {})
            else:
                await self._save_plates({})
                return {}
        except Exception as e:
            _LOGGER.error(f"Error loading plates: {e}")
            return {}

    async def _save_plates(self, plates: Dict[str, str]):
        """Save plates to YAML file asynchronously."""
        try:
            data = {'plates': plates}
            content = yaml.dump(data, default_flow_style=False, allow_unicode=True)
            async with aiofiles.open(self.plates_file, 'w', encoding='utf-8') as file:
                await file.write(content)
            self.known_plates = plates
            await self._update_input_select()
            _LOGGER.info(f"Saved plates: {list(plates.keys())}")
        except Exception as e:
            _LOGGER.error(f"Error saving plates: {e}")

    async def _setup_listeners(self, event):
        """Set up state change listeners."""
        # Load plates asynchronously with protection
        loaded_plates = await self._load_plates()
        self.known_plates = loaded_plates if loaded_plates is not None else {}
        _LOGGER.info(f"Loaded {len(self.known_plates)} plates")

        # Listen to changes in input_text SEPARATELY for each
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

        # Listen to changes in input_select for removing plates
        async_track_state_change_event(
            self.hass,
            'input_select.remove_plate',
            self._handle_remove_plate
        )

        # Initialize input_select
        await self._update_input_select()
        _LOGGER.info("PlateManager listeners setup completed")

    async def _handle_plate_change(self, event):
        """Handle change in input_text.add_new_plate."""
        new_state = event.data.get('new_state')
        old_state = event.data.get('old_state')

        # Check if this is a real change (not empty -> empty)
        if (new_state and new_state.state and
            old_state and old_state.state != new_state.state):
            _LOGGER.info(f"Plate change detected: {new_state.state}")
            # Check if we also have owner and add plate
            await self._try_add_plate()

    async def _handle_owner_change(self, event):
        """Handle change in input_text.add_plate_owner."""
        new_state = event.data.get('new_state')
        old_state = event.data.get('old_state')

        # Check if this is a real change (not empty -> empty)
        if (new_state and new_state.state and
            old_state and old_state.state != new_state.state):
            _LOGGER.info(f"Owner change detected: {new_state.state}")
            # Check if we also have plate and add plate
            await self._try_add_plate()

    async def _try_add_plate(self):
        """Try to add plate if we have both plate and owner."""
        # Wait a moment to ensure states are current
        await self.hass.async_add_executor_job(lambda: __import__('time').sleep(0.1))

        plate_state = self.hass.states.get('input_text.add_new_plate')
        owner_state = self.hass.states.get('input_text.add_plate_owner')

        if plate_state and owner_state and plate_state.state and owner_state.state:
            plate_number = plate_state.state.strip().upper()
            owner_name = owner_state.state.strip()

            if plate_number and owner_name:
                _LOGGER.info(f"Adding plate: {plate_number} -> {owner_name}")

                # Add plate
                new_plates = self.known_plates.copy()
                new_plates[plate_number] = owner_name
                await self._save_plates(new_plates)

                # Clear input fields - IMPORTANT: add small delay
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

                _LOGGER.info(f"Added plate: {plate_number} -> {owner_name}")

                # Force UI update
                self.hass.bus.async_fire('enhanced_platerecognizer_plate_added', {
                    'plate': plate_number,
                    'owner': owner_name
                })

    async def _handle_remove_plate(self, event):
        """Handle plate removal."""
        new_state = event.data.get('new_state')
        old_state = event.data.get('old_state')

        # Get translated texts for comparison
        no_plates_text = self._get_translation('component.enhanced_platerecognizer.plate_manager.no_plates')
        select_text = self._get_translation('component.enhanced_platerecognizer.plate_manager.select_to_delete')

        if (new_state and old_state and
            new_state.state != old_state.state and
            new_state.state not in [no_plates_text, select_text]):

            selected = new_state.state
            _LOGGER.info(f"Remove plate selected: {selected}")

            # Remove plate
            new_plates = self.known_plates.copy()
            if selected in new_plates:
                del new_plates[selected]
                await self._save_plates(new_plates)
                _LOGGER.info(f"Removed plate: {selected}")

                # Force UI update
                self.hass.bus.async_fire('enhanced_platerecognizer_plate_removed', {
                    'plate': selected
                })

    async def _update_input_select(self):
        """Update input_select options with proper default option using translations."""
        try:
            if not self.known_plates or len(self.known_plates) == 0:
                # Empty plates.yaml - default to "No plates"
                no_plates_text = self._get_translation('component.enhanced_platerecognizer.plate_manager.no_plates')
                options = [no_plates_text]
                default_option = no_plates_text
            else:
                # We have plates - add selection option + plates
                select_text = self._get_translation('component.enhanced_platerecognizer.plate_manager.select_to_delete')
                options = [select_text] + list(self.known_plates.keys())
                default_option = select_text

            _LOGGER.info(f"Updating input_select with options: {options}, default: {default_option}")

            # Set options
            await self.hass.services.async_call(
                'input_select', 'set_options',
                {
                    'entity_id': 'input_select.remove_plate',
                    'options': options
                },
                blocking=True
            )

            # Set default option
            await self.hass.services.async_call(
                'input_select', 'select_option',
                {
                    'entity_id': 'input_select.remove_plate',
                    'option': default_option
                },
                blocking=True
            )

        except Exception as e:
            _LOGGER.error(f"Error updating input_select: {e}")

    def get_plate_owner(self, plate: str) -> str:
        """Return plate owner."""
        if self.tolerate_one_mistake:
            for known_plate in self.known_plates:
                if self._plates_similar(plate, known_plate):
                    return self.known_plates[known_plate]
        return self.known_plates.get(plate.upper(), "Unknown")

    def _plates_similar(self, plate1: str, plate2: str) -> bool:
        """Check if plates are similar (tolerance of 1 error)."""
        if len(plate1) != len(plate2):
            return False
        differences = sum(1 for a, b in zip(plate1.upper(), plate2.upper()) if a != b)
        return differences <= 1

    def is_plate_known(self, plate: str) -> bool:
        """Check if plate is known."""
        if self.known_plates is None:
            return False
        
        if plate.upper() in self.known_plates:
            return True
        
        if self.tolerate_one_mistake:
            for known_plate in self.known_plates:
                if self._plates_similar(plate, known_plate):
                    return True
        
        return False

    def get_all_plates(self) -> Dict[str, str]:
        """Return all known plates."""
        if self.known_plates is None:
            return {}
        return self.known_plates.copy()

    def get_plates_count(self) -> int:
        """Return number of known plates."""
        if self.known_plates is None:
            return 0
        return len(self.known_plates)

    def get_corrected_plate(self, plate: str) -> str:
        """Return correct plate from file, if similar."""
        plate_upper = plate.upper()
        
        if plate_upper in self.known_plates:
            return plate_upper  # Return original if exact match
        
        if self.tolerate_one_mistake:
            for known_plate in self.known_plates:
                if self._plates_similar(plate_upper, known_plate):
                    # Found similar plate, return the one from .yaml file
                    return known_plate
        
        # If no similar found, return original plate
        return plate
