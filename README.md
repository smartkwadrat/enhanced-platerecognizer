# Enhanced PlateRecognizer

Fork of this integration: https://github.com/robmarkcole/HASS-plate-recognizer

**Version 0.2.3**

Example settings for configuration.yaml:

```yaml
image_processing:
  - platform: enhanced_platerecognizer
    api_key: "TWÓJ_API_KEY"
    region: "pl"
    save_file_folder: "/config/www/Tablice"
    max_images: 10
    consecutive_captures: 1
    capture_interval: 1.2
    save_timestamped_file: true
    always_save_latest_file: true
    tolerate_one_mistake: false
    source:
      - entity_id: camera.<Twoja_Kamera1>
    #  - entity_id: camera.<Twoja_Kamera2>
    # Podaj dokładnie te same encje co w konfiguracji integracji
```