# 🚗 Enhanced Plate Recognizer for Home Assistant

[![GitHub Repo](https://img.shields.io/github/stars/smartkwadrat/enhanced-platerecognizer?style=social)](https://github.com/smartkwadrat/enhanced-platerecognizer)
[![hacs_badge](https://img.shields.io/badge/HACS-Default-orange.svg)](https://github.com/hacs/integration)

---

> **ℹ️ This integration is a fork of [`robmarkcole/HASS-plate-recognizer`](https://github.com/robmarkcole/HASS-plate-recognizer).  
> 💙 Huge thanks to [robmarkcole](https://github.com/robmarkcole) for their excellent original work and inspiration!  
> Without their pioneering integration, this enhanced version would not exist.
>
> This fork adds many new features and improvements—see below for a full comparison!

---

## 🆕 Key Features & Enhancements over the Original

| Feature                          | Original                     | Enhanced (this fork)         |
|-----------------------------------|------------------------------|------------------------------|
| Multiple camera support           | ✔️                           | ✔️                           |
| Save images with overlays         | ✔️ limited                   | ✔️ with timestamp/latest, ROI, owner |
| API statistics sensor             | ❌                           | ✔️                           |
| Multi-language                    | ❌                           | ✔️ (PL and EN) |
| Dashboard cards                   | ❌                           | ✔️                           |
| Tolerate single OCR mistake       | ❌                           | ✔️                           |
| Plates managmenet over dashboard  | ❌                           | ✔️                           |
| Save plate–owner pairs            | ❌                           | ✔️                           |
| Multiple camera dashboard out-of-the-box | ❌                  | ✔️                           |
| Consecutive captures with delay   | ❌                           | ✔️ (option for increased reliability) |
| Home Assistant event-based sensors | ❌                        | ✔️                           |

---

## 🚀 How it works

- Integrates Home Assistant with [Platerecognizer.com](https://platerecognizer.com/) API
- Recognizes license plates from camera images
- Tracks known, recognized, and last seen plates
- Advanced event-driven sensors and helpers for automations!
- Easy web dashboard for adding/removing plates and seeing matches

---

## 🛠️ Installation

### Via HACS (Recommended)

1. Install HACS (Home Assistant Community Store) if you haven't already.
2. In Home Assistant Community Store click the `...` button on the top-right correnr.
3. Add custom repository URL: https://github.com/smartkwadrat/enhanced-platerecognizer
4. Search for enhanced-platerecognizer and click **Download**.
5. Restart Home Assistant.
6. Add new settings to configuration.yaml


## ⚙️ Example Configuration (`configuration.yaml`)

Add the following to your `configuration.yaml` (adapt paths/entities/api_token as needed):

```yaml
image_processing:
  - platform: enhanced_platerecognizer
    api_token: your_api_token_here
    regions:
      - pl
      - gb
      - ie
    save_file_folder: /media/image/platerecognizer
    save_timestamped_file: true
    always_save_latest_file: true
    detection_rule: none
    mmc: false
    region: none
    server: https://api.platerecognizer.com/v1/plate-reader/
    consecutive_captures: false
    tolerate_one_mistake: true
    source:
      - entity_id: camera.camera1_snapshots_clear
      - entity_id: camera.camera2_snapshots_clear

input_text:
  add_new_plate:
  name: Add New Plate
  min: 0
  max: 255

add_plate_owner:
  name: Add Plate Owner
  min: 0
  max: 255

input_select:
  remove_plate:
    name: Remove plate
    options:
      - "Select plates to remove"
```



## 🖥️ Example Minimal Dashboard (Lovelace YAML)

```yaml
title: License Plate Recognition
cards:
  - type: vertical-stack
    cards:
      - type: horizontal-stack
        cards:
          - type: entity
            name: Last Recognized Plate
            entity: sensor.last_recognized_plate
            style:
              "--primary-font-size": 10px
          - type: entity
            name: Currently Recognized Plate(s)
            entity: sensor.current_recognized_plates
      - type: entity
        entity: sensor.plate_recognition_camera_1
        name: Camera 1 Plate Status
      - type: entity
        entity: sensor.plate_recognition_camera_2
        name: Camera 2 Plate Status
      - type: markdown
        content: >
          ## Vehicle Just Detected

          <span style="font-size: 1.5em;">
          {% if states('sensor.current_recognized_plates') %}
            {{ states('sensor.current_recognized_plates') }}
          {% else %}
            No plates recognized.
          {% endif %}
          </span>
      - type: entities
        title: Manage Known Plates
        entities:
          - entity: input_text.add_plate_owner
            name: Enter Plate Owner
          - entity: input_text.add_new_plate
            name: Add New License Plate
          - entity: input_select.remove_plate
            name: Remove Plate
      - type: markdown
        title: Saved Plates List
        content: >-
          {{ state_attr('sensor.known_license_plates', 'formatted_list') | safe }}
type: custom:vertical-layout
```


## ⚡ Example Automations

### 🚦 Open Gate When Recognized Plate Detected

```yaml
alias: Open Gate for Recognized Plate
description: "Opens the gate when a known license plate is recognized."
trigger:
  - platform: state
    entity_id: sensor.recognized_car
condition:
  - condition: template
    value_template: >
      {{ 'Recognized' in states('sensor.recognized_car') }}
  - condition: state
    entity_id: binary_sensor.gate_open_contact
    state: "off"
action:
  - service: switch.turn_on
    target:
      entity_id: switch.gate_open_trigger
mode: single
```


### 🛑 Run Scan on Vehicle Detection

```yaml
alias: Trigger Plate Scan on Vehicle Detection
description: "Initiates license plate scanning when a vehicle is detected."
trigger:
  - platform: state
    entity_id: binary_sensor.vehicle_detected
    from: "off"
    to: "on"
condition: []
action:
  - service: image_processing.scan
    target:
      entity_id: image_processing.enhanced_platerecognizer_yourcamera
mode: queued
```

### 3️⃣ Send Notification When a New Unknown Plate is Recognized

```yaml
alias: Notify on Unknown Plate Recognition
description: "Sends a notification when an unknown license plate is recognized."
trigger:
  - platform: state
    entity_id: sensor.last_recognized_car
condition:
  - condition: template
    value_template: >
      {{ state_attr('sensor.last_recognized_car', 'is_known') == False }}
action:
  - service: notify.mobile_app_your_phone
    data:
      message: "Unknown license plate detected: {{ states('sensor.last_recognized_car') }}"
      title: "Unknown Plate Alert"
mode: parallel
```

Customize the entity IDs (e.g., switch.gate_open_trigger, binary_sensor.vehicle_detected, image_processing.enhanced_platerecognizer_yourcamera) to fit your system! These are meant as clear, general examples for your own use.


## 📝 Notes

- Supported languages: PL and EN
- API token required from [platerecognizer.com](https://platerecognizer.com/).
- You can configure which region's plates to recognize.
- All entities use Home Assistant naming best practices and should auto-appear after correct configuration.
- All configuration is done via YAML; no config flow UI.