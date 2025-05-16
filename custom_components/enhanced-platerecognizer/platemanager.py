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
        self.plates = {}  # {plate: owner}
        self._load_plates()

    def _load_plates(self):
        """Load plates from YAML file."""
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

    def _save_plates(self):
        """Save plates to YAML file."""
        try:
            with open(self.plates_file, 'w') as file:
                yaml.dump({"plates": self.plates}, file)
        except IOError as exc:
            _LOGGER.error(f"Error saving plates file: {exc}")

    def add_plate(self, plate, owner=""):
        """Add a plate to the list."""
        if not self.is_valid_plate(plate):
            return False
        normalized_plate = plate.upper()
        self.plates[normalized_plate] = owner
        self._save_plates()
        return True

    def remove_plate(self, plate):
        """Remove a plate from the list."""
        normalized_plate = plate.upper()
        if normalized_plate in self.plates:
            del self.plates[normalized_plate]
            self._save_plates()
            return True
        return False

    def get_plates(self):
        """Get all plates with owners."""
        return self.plates

    def get_formatted_plates(self):
        """Get formatted plate list for display."""
        return [f"{plate} - {owner}" if owner else plate for plate, owner in self.plates.items()]

    def is_plate_recognized(self, plate):
        """Check if plate is in the known plates list."""
        normalized_plate = plate.upper()
        return normalized_plate in self.plates

    @staticmethod
    def is_valid_plate(plate):
        """Validate plate format."""
        pattern = r'^[a-zA-Z0-9]{2,10}$'
        return bool(re.match(pattern, plate))
