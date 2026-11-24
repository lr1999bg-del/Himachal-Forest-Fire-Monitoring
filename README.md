# Himachal Forest Fire Monitoring

IoT- and ML-based forest-fire monitoring and early-warning prototype for Himachal Pradesh.

## Project overview

The project combines a live sensor station with a Streamlit dashboard. The dashboard reads JSON sensor data from an RX NodeMCU over USB serial, estimates a station-level risk band, stores readings in SQLite, and can send Telegram alerts when the risk band changes. It also displays current weather for Sundernagar, Mandi, and includes an experimental regional next-day hotspot-candidate estimate when a compatible model file is available.

> **Important:** This is an educational prototype, not a certified fire-detection or emergency-warning system. Risk thresholds are provisional and must be calibrated and validated before any real-world use. The weather-based model estimates relative satellite-hotspot candidate likelihood; it does not confirm fires.

## Hardware used

- TX NodeMCU sensor station
- RX NodeMCU connected to the computer by USB
- DHT22 temperature/humidity sensor
- Soil-moisture sensor
- MQ-2 gas/smoke sensor
- LoRa modules used for station-to-receiver communication in the hardware setup

The RX NodeMCU should output one JSON object per serial line, for example:

```json
{"station":"Station_1","temperature":15.1,"humidity":60.8,"soil_moisture_raw":69,"smoke_raw":2559}
```

## Software requirements

- Python 3.10 or later recommended
- Arduino IDE and the appropriate NodeMCU board support for firmware
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

6. Connect the RX NodeMCU by USB. Close Arduino IDE Serial Monitor so the dashboard can access the serial port.
7. If your receiver uses a port other than `COM15`, edit `SERIAL_PORT` near the top of `app.py`. The configured baud rate is `115200`.
8. Start the dashboard:

   ```powershell
   streamlit run app.py
   ```

## Station risk bands

The current demonstration scoring rules use temperature, relative humidity, soil raw ADC value, and MQ-2 raw ADC value:

- **LOW:** score 0–1
- **MODERATE:** score 2–3
- **HIGH:** score 4 or more

For this soil sensor, a lower raw reading indicates drier soil. The MQ-2 threshold is provisional. Both soil and MQ-2 values are raw readings, not calibrated moisture percentages or smoke concentrations.

Telegram notifications are sent when the station enters MODERATE or HIGH and when it changes between those bands. Returning to LOW resets the alert state for the next risk episode.

## Data and model files

- Live readings are stored locally in `weather_history.db` (created automatically).
- The experimental hotspot estimate expects a compatible model package under `models/`, named `himachal_calibrated_hotspot_*.pkl` or `himachal_nextday_hotspot_*.pkl`.
- The model package must contain the feature list and model object expected by `app.py`; calibrated packages may also include a calibrator and risk-band thresholds.
- If no compatible model file is present, the live station dashboard continues to work and the experimental panel displays a warning.

Do not commit private credentials, local databases, virtual environments, or generated cache files.

## Current limitations

- Only Station 1 is configured in the current dashboard.
- Serial port is configured as `COM15` by default and may need changing on another computer.
- Sensor thresholds require calibration against actual sensor measurements and local conditions.
- MQ-2 readings are affected by warm-up, environment, and sensor characteristics.
- The regional hotspot estimate depends on an externally supplied compatible model and live weather forecast data.
- This prototype should not replace official forest department alerts, satellite monitoring, or emergency services.

## Repository structure

```text
.
├── app.py
├── requirements.txt
├── README.md
├── .env.example
└── .gitignore
```

Firmware source and the trained model artifact should be added in their own folders when ready. Do not upload secrets or private data.
