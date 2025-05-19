"""Plate manager for Enhanced PlateRecognizer."""

import logging
import os
import re
import yaml
from typing import Dict, List

_LOGGER = logging.getLogger(__name__)


async def async_get_recognized_plate(self, plate: str, tolerate_one_mistake: bool = False) -> str | None:
    """Zwraca zapisaną tablicę, która została rozpoznana (dokładnie lub z tolerancją jednego błędu)."""
    normalized_plate = plate.upper()
    if normalized_plate in self.plates:
        return normalized_plate
    if tolerate_one_mistake:
        for known_plate in self.plates.keys():
            if self._levenshtein_distance(normalized_plate, known_plate) <= 1:
                return known_plate
    return None


class PlateManager:
    """Class to manage license plates, owners, and persistence."""

    def __init__(self, hass, config_dir: str):
        """Initialize the plate manager."""
        self.hass = hass  # Instance of HomeAssistant
        self.plates_file: str = os.path.join(config_dir, "enhanced_platerecognizer_plates.yaml")
        self.plates: Dict[str, str] = {}  # Stores plate_number: owner_name

    async def async_initial_load(self) -> None: # Nowa metoda do początkowego ładowania
        """Load plates from YAML file asynchronously."""
        _LOGGER.debug(f"Attempting initial load of plates from {self.plates_file}")
        await self.hass.async_add_executor_job(self._load_plates_sync)

    def _load_plates_sync(self) -> None:
        """
        Load plates from YAML file synchronously.
        This should ideally be called once during setup or wrapped in async_add_executor_job if called from async context.
        """
        if not os.path.exists(self.plates_file):
            _LOGGER.info(f"Plates file not found at {self.plates_file}. A new one will be created on save if plates are added.")
            self.plates = {} # Start with an empty dict if file doesn't exist
            # Optionally, create an empty file here:
            # self._save_plates_sync() 
            return

        try:
            with open(self.plates_file, 'r', encoding='utf-8') as file:
                content = yaml.safe_load(file)
                if content and isinstance(content, dict) and "plates" in content and isinstance(content["plates"], dict):
                    # Ensure all keys (plates) are strings and uppercase, and values (owners) are strings.
                    self.plates = {str(plate).upper(): str(owner) for plate, owner in content["plates"].items()}
                    _LOGGER.debug(f"Successfully loaded {len(self.plates)} plates from {self.plates_file}.")
                else:
                    _LOGGER.warning(f"Plates file {self.plates_file} is malformed or empty. Initializing with empty plates list.")
                    self.plates = {}
                    # Optionally, overwrite with an empty valid structure:
                    # self._save_plates_sync() 
        except (yaml.YAMLError, IOError) as exc:
            _LOGGER.error(f"Error loading plates file {self.plates_file}: {exc}")
            self.plates = {} # Default to empty on error
        except Exception as e:
            _LOGGER.error(f"Unexpected error while loading plates from {self.plates_file}: {e}", exc_info=True)
            self.plates = {}

    def _save_plates_sync(self) -> bool:
        """
        Save plates to YAML file synchronously.
        This should be wrapped in async_add_executor_job if called from async context.
        """
        try:
            directory = os.path.dirname(self.plates_file)
            if not os.path.exists(directory):
                os.makedirs(directory, exist_ok=True)
                _LOGGER.info(f"Created directory for plates file: {directory}")

            with open(self.plates_file, 'w', encoding='utf-8') as file:
                yaml.dump({"plates": self.plates}, file, allow_unicode=True, sort_keys=True)
            _LOGGER.debug(f"Successfully saved {len(self.plates)} plates to {self.plates_file}.")
            return True
        except (IOError, OSError) as exc:
            _LOGGER.error(f"Error saving plates file to {self.plates_file}: {exc}")
            return False
        except Exception as e:
            _LOGGER.error(f"Unexpected error while saving plates to {self.plates_file}: {e}", exc_info=True)
            return False

    async def async_reload_plates(self) -> None:
        """Asynchronously reloads plates from the file."""
        _LOGGER.info(f"Attempting to reload plates from {self.plates_file}")
        await self.hass.async_add_executor_job(self._load_plates_sync)

    async def async_save_plates(self) -> bool:
        """Asynchronously save the current plates to the YAML file."""
        return await self.hass.async_add_executor_job(self._save_plates_sync)

    @staticmethod
    def is_valid_plate(plate: str) -> bool:
        """Validate plate format (2 to 10 alphanumeric characters)."""
        if not plate or not isinstance(plate, str):
            return False
        pattern = r'^[a-zA-Z0-9]{2,10}$'
        return bool(re.match(pattern, plate))

    async def async_add_plate(self, plate: str, owner: str = "") -> bool:
        """
        Add a plate to the list asynchronously.
        Returns True if added, False if invalid format or other issue.
        """
        if not self.is_valid_plate(plate):
            _LOGGER.warning(f"Attempted to add invalid plate format: '{plate}'")
            return False
        
        normalized_plate = plate.upper()
        normalized_owner = str(owner).strip() # Ensure owner is a string and strip whitespace

        if normalized_plate in self.plates and self.plates[normalized_plate] == normalized_owner:
            _LOGGER.debug(f"Plate '{normalized_plate}' with owner '{normalized_owner}' already exists. No change made.")
            return True # Considered success as the state is already as desired

        self.plates[normalized_plate] = normalized_owner
        _LOGGER.info(f"Added/Updated plate: '{normalized_plate}', Owner: '{normalized_owner}'")
        return await self.async_save_plates()

    async def async_remove_plate(self, plate: str) -> bool:
        """
        Remove a plate from the list asynchronously.
        Returns True if removed, False if not found.
        """
        normalized_plate = plate.upper()
        if normalized_plate in self.plates:
            del self.plates[normalized_plate]
            _LOGGER.info(f"Removed plate: '{normalized_plate}'")
            return await self.async_save_plates()
        else:
            _LOGGER.warning(f"Attempted to remove plate '{normalized_plate}' which was not found.")
            return False

    async def async_get_all_plates(self) -> Dict[str, str]:
        """Get all plates with their owners asynchronously."""
        # Returns a copy to prevent external modification of the internal dict
        return self.plates.copy()

    async def async_get_formatted_plates(self) -> List[str]:
        """
        Get a formatted list of plates (e.g., "PLATE - OWNER" or "PLATE") for display.
        Sorted alphabetically by plate number.
        """
        # Sort by plate number for consistent display
        sorted_plates = sorted(self.plates.items())
        return [
            f"{plate} - {owner}" if owner else plate
            for plate, owner in sorted_plates
        ]

    async def async_is_plate_recognized(self, plate: str, tolerate_one_mistake: bool = False) -> bool:
        """
        Check if a plate is in the known plates list asynchronously.
        Optionally tolerates one character difference using Levenshtein distance.
        """
        if not plate: # Handle empty or None plate string
            return False
            
        normalized_plate = plate.upper()

        if normalized_plate in self.plates:
            return True
        
        if tolerate_one_mistake:
            # This check can be computationally intensive for very large lists of known plates.
            # For typical home use, it should be acceptable.
            for known_plate in self.plates.keys(): # Iterate over keys (plate numbers)
                if self._levenshtein_distance(normalized_plate, known_plate) <= 1:
                    _LOGGER.debug(f"Plate '{normalized_plate}' recognized as '{known_plate}' with 1 mistake tolerance.")
                    return True
        return False

    @staticmethod
    def _levenshtein_distance(s1: str, s2: str) -> int:
        """
        Calculates the Levenshtein distance between two strings.
        A common measure of similarity between two strings.
        """
        if not isinstance(s1, str) or not isinstance(s2, str):
            # Handle cases where inputs might not be strings, though type hints should help.
            return float('inf') # Or raise an error, or handle as per desired logic.

        if len(s1) < len(s2):
            return PlateManager._levenshtein_distance(s2, s1)

        if len(s2) == 0:
            return len(s1)

        previous_row = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]

