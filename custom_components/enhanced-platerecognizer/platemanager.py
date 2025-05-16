"""Plate manager for Enhanced PlateRecognizer."""

import logging
import os
import re
import yaml

_LOGGER = logging.getLogger(__name__)

class PlateManager:
    """Class to manage license plates."""

    def __init__(self, hass, config_dir):
        """Initialize the plate manager."""
        self.hass = hass
        self.plates_file = os.path.join(config_dir, "enhanced_platerecognizer_plates.yaml")
        self.plates = {} # {plate: owner}
        self._load_plates()

    async def async_load_plates(self):
        """Load plates from YAML file asynchronicznie."""
        def load_file():
            try:
                if not os.path.exists(self.plates_file):
                    return None
                
                with open(self.plates_file, 'r') as file:
                    content = yaml.safe_load(file)
                
                if content and isinstance(content, dict) and "plates" in content:
                    return content["plates"]
                else:
                    return {}
            except (yaml.YAMLError, IOError) as exc:
                _LOGGER.error(f"Error loading plates file: {exc}")
                return {}
            except Exception as e:
                _LOGGER.error(f"Nieoczekiwany błąd podczas wczytywania tablic: {e}")
                return {}

        loaded_plates = await self.hass.async_add_executor_job(load_file)
        if loaded_plates is not None:
            self.plates = loaded_plates
            await self.async_save_plates()
        return self.plates

    def _load_plates(self):
        """Load plates from YAML file synchronicznie."""
        if not os.path.exists(self.plates_file):
            self._save_plates()
            return

        try:
            with open(self.plates_file, 'r') as file:
                content = yaml.safe_load(file)
                
            if content and isinstance(content, dict) and "plates" in content:
                self.plates = content["plates"]
            else:
                self.plates = {}
                self._save_plates()
        except (yaml.YAMLError, IOError) as exc:
            _LOGGER.error(f"Error loading plates file: {exc}")
            self.plates = {}
            self._save_plates()
        except Exception as e:
            _LOGGER.error(f"Nieoczekiwany błąd podczas wczytywania tablic: {e}")
            self.plates = {}
            self._save_plates()

    async def async_save_plates(self):
        """Save plates to YAML file asynchronicznie."""
        def save_file():
            try:
                directory = os.path.dirname(self.plates_file)
                os.makedirs(directory, exist_ok=True)
                
                with open(self.plates_file, 'w') as file:
                    yaml.dump({"plates": self.plates}, file)
                return True
            except (IOError, OSError) as exc:
                _LOGGER.error(f"Error saving plates file: {exc}")
                return False
            except Exception as e:
                _LOGGER.error(f"Nieoczekiwany błąd podczas zapisu tablic: {e}")
                return False

        return await self.hass.async_add_executor_job(save_file)

    def _save_plates(self):
        """Save plates to YAML file synchronicznie."""
        try:
            directory = os.path.dirname(self.plates_file)
            os.makedirs(directory, exist_ok=True)
            
            with open(self.plates_file, 'w') as file:
                yaml.dump({"plates": self.plates}, file)
        except (IOError, OSError) as exc:
            _LOGGER.error(f"Error saving plates file: {exc}")
        except Exception as e:
            _LOGGER.error(f"Nieoczekiwany błąd podczas zapisu tablic: {e}")

    async def async_add_plate(self, plate, owner=""):
        """Add a plate to the list asynchronicznie."""
        if not self.is_valid_plate(plate):
            return False

        normalized_plate = plate.upper()
        self.plates[normalized_plate] = owner
        await self.async_save_plates()
        return True

    def add_plate(self, plate, owner=""):
        """Add a plate to the list synchronicznie."""
        if not self.is_valid_plate(plate):
            return False

        normalized_plate = plate.upper()
        self.plates[normalized_plate] = owner
        self._save_plates()
        return True

    async def async_remove_plate(self, plate):
        """Remove a plate from the list asynchronicznie."""
        normalized_plate = plate.upper()
        if normalized_plate in self.plates:
            del self.plates[normalized_plate]
            await self.async_save_plates()
            return True
        return False

    def remove_plate(self, plate):
        """Remove a plate from the list synchronicznie."""
        normalized_plate = plate.upper()
        if normalized_plate in self.plates:
            del self.plates[normalized_plate]
            self._save_plates()
            return True
        return False

    async def async_get_plates(self):
        """Get all plates with owners asynchronicznie."""
        return self.plates

    def get_plates(self):
        """Get all plates with owners synchronicznie."""
        return self.plates

    async def async_get_formatted_plates(self):
        """Get formatted plate list for display asynchronicznie."""
        return [f"{plate} - {owner}" if owner else plate for plate, owner in self.plates.items()]

    def get_formatted_plates(self):
        """Get formatted plate list for display synchronicznie."""
        return [f"{plate} - {owner}" if owner else plate for plate, owner in self.plates.items()]

    async def async_is_plate_recognized(self, plate):
        """Check if plate is in the known plates list asynchronicznie."""
        normalized_plate = plate.upper()
        return normalized_plate in self.plates

    def is_plate_recognized(self, plate):
        """Check if plate is in the known plates list synchronicznie."""
        normalized_plate = plate.upper()
        return normalized_plate in self.plates

    @staticmethod
    def is_valid_plate(plate):
        """Validate plate format."""
        pattern = r'^[a-zA-Z0-9]{2,10}$'
        return bool(re.match(pattern, plate))
