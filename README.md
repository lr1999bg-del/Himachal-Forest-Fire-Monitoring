# Himachal Forest Fire Monitoring

An IoT- and ML-based forest-fire monitoring and early-warning prototype for Himachal Pradesh.

## Project overview

The project combines a live sensor station with a Streamlit dashboard. An ESP32 transmitter reads temperature, humidity, soil-moisture and smoke-sensor values. It creates a Wi-Fi hotspot and serves the latest readings over HTTP. An ESP8266 NodeMCU receiver connects to that hotspot, fetches the JSON data and forwards it to the computer over USB serial. The Streamlit dashboard reads the serial data, estimates a station-level risk band, stores readings in SQLite and can send Telegram alerts when the risk band changes.

The dashboard also displays current weather for Sundernagar, Mandi, and includes an experimental regional next-day hotspot-candidate estimate when a compatible model file is available.

> **Important:** This is an educational prototype, not a certified fire-detection or emergency-warning system. Risk thresholds are provisional and must be calibrated and validated before any real-world use. The weather-based model estimates relative satellite-hotspot candidate likelihood; it does not confirm fires.

## Dashboard report

A PDF report containing dashboard pages, live sensor readings, station status, fire-risk assessment, reading-history charts, local weather and the experimental hotspot-prediction panel is available here:

[View the Forest Fire Monitoring dashboard report](reports/Forest-Fire-Monitoring.pdf)

**Note:** The hotspot model score shown in the report is experimental and should not be interpreted as a verified probability of an active fire.

## Hardware

- **Transmitter:** ESP32 Dev Module
- **Receiver:** ESP8266 NodeMCU connected to the computer by USB
- **Temperature and humidity:** DHT22
- **Soil moisture:** analog soil-moisture sensor
- **Smoke/gas:** MQ-2 analog output
- **Communication:** ESP32 Wi-Fi Access Point + HTTP; no LoRa or external router is required

### Current ESP32 pin configuration

| Sensor signal | ESP32 GPIO |
| --- | --- |
| DHT22 DATA | GPIO 4 |
| Soil-moisture AO | GPIO 34 |
| MQ-2 AO | GPIO 35 |

Ensure every analog signal connected to the ESP32 is within its allowed input-voltage range (maximum 3.3 V). If the MQ-2 module is powered from 5 V, use an appropriate voltage divider/level-conditioning circuit on AO before connecting it to the ESP32.

### Wi-Fi and data format

The ESP32 creates this hotspot:

- SSID: `ForestFire_Network`
- Password: `ForestFire123`
- ESP32 address: `192.168.4.1`
- HTTP endpoint: `http://192.168.4.1/data`

The RX NodeMCU connects to the hotspot and prints one JSON object per serial line, for example:

```json
{"station":"Station_1","temperature":15.1,"humidity":60.8,"soil_moisture_raw":69,"smoke_raw":2559}
```

The receiver serial baud rate is **115200**. The dashboard's default serial port is **COM15** and may need changing in `app.py` on another computer.

## Firmware

- Transmitter: [`firmware/TX_ESP32/TX_ESP32.ino`](firmware/TX_ESP32/TX_ESP32.ino)
- Receiver: [`firmware/RX_NodeMCU/RX_NodeMCU.ino`](firmware/RX_NodeMCU/RX_NodeMCU.ino)

Open each sketch in Arduino IDE and select the matching board:
- TX: **ESP32 Dev Module**
- RX: **NodeMCU 1.0 (ESP-12E Module)**

The TX sketch requires the **DHT sensor library by Adafruit** and **Adafruit Unified Sensor** library.

## Software requirements

- Python 3.10 or later recommended
- Arduino IDE with ESP32 and ESP8266 board support
- A Telegram bot and chat ID (optional, for notifications)

## Setup

1. Clone or download this repository.
2. Open a terminal in the project folder.
3. Create and activate a virtual environment:

   **Windows PowerShell**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

4. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

5. Copy `.env.example` to `.env` and enter your Telegram credentials:

   ```env
   BOT_TOKEN=your_telegram_bot_token
   CHAT_ID=your_telegram_chat_id
   ```

   Keep `.env` private. It is excluded from Git by `.gitignore`. Never commit bot tokens or other secrets.

6. Upload the TX firmware to the ESP32 and the RX firmware to the NodeMCU.
7. Power the ESP32 transmitter. Confirm that its hotspot is available, then power/connect the RX NodeMCU.
8. Connect the RX NodeMCU to the computer by USB. Close Arduino IDE Serial Monitor so the dashboard can access the serial port.
9. If the receiver uses a port other than `COM15`, edit `SERIAL_PORT` near the top of `app.py`. The configured baud rate is `115200`.
10. Start the dashboard:

   ```powershell
   streamlit run app.py
   ```

## Station risk bands

The current demonstration scoring rules use temperature, relative humidity, soil raw ADC value, and MQ-2 raw ADC value:

- **LOW:** score 0–1
- **MODERATE:** score 2–3
- **HIGH:** score 4 or more

For this soil sensor, a lower raw reading indicates drier soil. The MQ-2 threshold is provisional. Soil and MQ-2 values are raw readings, not calibrated moisture percentages or smoke concentrations.

Telegram notifications are sent when the station enters MODERATE or HIGH and when it changes between those bands. Returning to LOW resets the alert state for the next risk episode.

## Data and model files

- Live readings are stored locally in `weather_history.db` (created automatically).
- The experimental hotspot estimate expects a compatible model package under `models/`, named `himachal_calibrated_hotspot_*.pkl` or `himachal_nextday_hotspot_*.pkl`.
- The model package must contain the feature list and model object expected by `app.py`; calibrated packages may also include a calibrator and risk-band thresholds.
- If no compatible model file is present, the live station dashboard continues to work and the experimental panel displays a warning.

Do not commit private credentials, local databases, virtual environments, or generated cache files.

## Current limitations

- Only Station 1 is configured in the current dashboard.
- The serial port defaults to `COM15` and may need changing on another computer.
- Sensor thresholds require calibration against actual sensor measurements and local conditions.
- MQ-2 readings are affected by warm-up, environment and sensor characteristics.
- The regional hotspot estimate depends on an externally supplied compatible model and live weather forecast data.
- This prototype should not replace official forest department alerts, satellite monitoring or emergency services.

## Repository structure

```text
.
├── app.py
├── requirements.txt
├── README.md
├── .env.example
├── .gitignore
├── reports/
│   └── Forest-Fire-Monitoring.pdf
└── firmware/
    ├── TX_ESP32/
    │   └── TX_ESP32.ino
    └── RX_NodeMCU/
        └── RX_NodeMCU.ino
```
