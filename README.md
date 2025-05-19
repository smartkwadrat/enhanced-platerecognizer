# Enhanced PlateRecognizer

Fork of this integration: https://github.com/robmarkcole/HASS-plate-recognizer

**Version 0.2.3**

Example settings for configuration.yaml:

```yaml
# Rozpoznawanie tablic rejestracyjnych
image_processing:
  - platform: enhanced_platerecognizer
    api_token: "TWÓJ_TOKEN"
    regions:
      - pl
    save_file_folder: "/config/www/Tablice"
    save_timestamped_file: true
    always_save_latest_file: true
    max_images: 10
    consecutive_captures: 1
    capture_interval: 1.2
    tolerate_one_mistake: true
    source:
      - entity_id: camera.<Twoja_Kamera1>
    #  - entity_id: camera.<Twoja_Kamera2>
    # Podaj dokładnie te same encje co w konfiguracji integracji
```