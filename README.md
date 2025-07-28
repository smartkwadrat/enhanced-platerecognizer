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
| Multi-language: Polish & English  | ❌                           | ✔️ (auto, translation system with 🇵🇱 hardcode) |
| Dashboard helpers (input_text, select) | ❌                     | ✔️ Full add/remove plate UI  |
| Tolerate single OCR mistake       | ❌                           | ✔️                           |
| Manual add/remove plates (input_text/select) | ❌                 | ✔️                           |
| Special sensors (last recognized, recognized, formatted) | ❌     | ✔️ (`sensor.last_recognized_car`, `sensor.recognized_car`, `sensor.formatted_car_plates`) |
| Events after plate/vehicle detection | ❌                      | ✔️ (`enhanced_platerecognizer_image_processed`, `enhanced_platerecognizer_plate_added`, `enhanced_platerecognizer_plate_removed`) |
| Custom per-country detection      | ✔️ limited                   | ✔️ Add new regions easily   |
| Configurable detection rules/API server | ❌                    | ✔️ (`detection_rule`, `server`)      |
| Save plate–owner pairs            | ❌                           | ✔️ (`plates.yaml`)           |
| Multiple camera dashboard out-of-the-box | ❌                  | ✔️                           |
| Consecutive captures with delay   | ❌                           | ✔️ (option for increased reliability) |
| Polish helper entity names/UX/hints | ❌                        | ✔️                           |
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

1. **Download** this repository and manually copy into your Home Assistant `custom_components/enhanced_platerecognizer` directory.
2. **Restart** Home Assistant.
3. **Set up configuration** as below.

---

## ⚙️ Example Configuration (`configuration.yaml`)

Add the following to your `configuration.yaml` (adapt paths/entities/api_token as needed):

```yaml
image_processing:
platform: enhanced_platerecognizer
api_token: your_api_token_here
regions: pl
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
entity_id: camera.brama_snapshots_clear
entity_id: camera.droga_snapshots_clear_2

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
type: entity
name: Last recognized plates
entity: sensor.last_recognized_car
style: "--primary-font-size: 10px"

type: entity
name: Recognized plates
entity: sensor.recognized_car

type: entity
entity: sensor.plate_recognition_camera_1

type: entity
entity: sensor.plate_recognition_camera_2

type: markdown
content: >
The car that just arrived
<span style="font-size: 1.5em;"> {% if states('sensor.recognized_car') %} {{ states('sensor.recognized_car') }} {% else %} No plates recognized {% endif %} </span>
type: entities
title: Plates management
entities:

entity: input_text.add_plate_owner
name: Add plates owner

entity: input_text.add_new_plate
name: Add new license plates

entity: input_select.remove_plate
name: Remove plates

type: markdown
content: >-
{{ state_attr('sensor.formatted_car_plates', 'formatted_list') | safe }}
title: Recorded license plates
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