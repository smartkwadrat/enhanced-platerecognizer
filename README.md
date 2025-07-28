# Enhanced PlateRecognizer

Fork of this integration: https://github.com/robmarkcole/HASS-plate-recognizer

**Version 0.3.9**

Example settings for configuration.yaml:

```yaml
image_processing:
  - platform: enhanced_platerecognizer
    api_token: "TWÓJ_TOKEN"
    regions:
      - pl
    save_file_folder: /media/image/platerecognizer
    save_timestamped_file: True
    always_save_latest_file: True
    detection_rule: none
    mmc: False
    region: none
    server: https://api.platerecognizer.com/v1/plate-reader/
    consecutive_captures: False
    tolerate_one_mistake: true
    source:
      - entity_id: camera.<Twoja_Kamera1>
    #  - entity_id: camera.<Twoja_Kamera2>
```