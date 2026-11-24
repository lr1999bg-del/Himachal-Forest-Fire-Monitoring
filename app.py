from pathlib import Path
from datetime import timedelta
import sqlite3
import json
import os
from datetime import datetime

import joblib
import numpy as np
import pandas as pd
import requests
import serial
import streamlit as st

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "weather_history.db"
SERIAL_PORT = "COM15"
SERIAL_BAUD = 115200
STATION_ID = "Station 1"

# Initial demonstration thresholds; calibrate with your actual sensors.
TEMP_MODERATE_C = 32.0
TEMP_HIGH_C = 38.0
HUMIDITY_MODERATE_PCT = 35.0
HUMIDITY_HIGH_PCT = 25.0
SOIL_DRY_RAW = 45       # Your soil sensor increases as soil gets wetter.
SOIL_VERY_DRY_RAW = 30
MQ2_ELEVATED_RAW = 2800 # Provisional threshold; verify by testing.

st.set_page_config(
    page_title="Forest Fire Monitoring",
    page_icon="🌲",
    layout="wide",
)


# ---------------- DATABASE ----------------


def initialize_database():
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS station_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                station_id TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                temperature_c REAL,
                humidity_percent REAL,
                soil_raw INTEGER,
                mq2_raw INTEGER,
                fire_risk TEXT
            )
            """
        )
        columns = {row[1] for row in connection.execute("PRAGMA table_info(station_readings)")}
        if "fire_risk" not in columns:
            connection.execute("ALTER TABLE station_readings ADD COLUMN fire_risk TEXT")
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS station_alert_state (
                station_id TEXT PRIMARY KEY,
                high_alert_active INTEGER NOT NULL DEFAULT 0,
                last_alerted_risk TEXT NOT NULL DEFAULT 'LOW'
            )
            """
        )
        # Migrate databases created by earlier app versions.
        alert_columns = {
            row[1] for row in connection.execute(
                "PRAGMA table_info(station_alert_state)"
            )
        }
        if "last_alerted_risk" not in alert_columns:
            connection.execute(
                "ALTER TABLE station_alert_state "
                "ADD COLUMN last_alerted_risk TEXT NOT NULL DEFAULT 'LOW'"
            )
        connection.commit()


def calculate_fire_risk(data):
    temperature = float(data["temperature"])
    humidity = float(data["humidity"])
    soil = int(data["soil_moisture_raw"])
    smoke = data.get("smoke_raw")
    smoke = int(smoke) if smoke is not None else None

    score = 0
    reasons = []

    if temperature >= TEMP_HIGH_C:
        score += 2
        reasons.append("very high temperature")
    elif temperature >= TEMP_MODERATE_C:
        score += 1
        reasons.append("elevated temperature")

    if humidity <= HUMIDITY_HIGH_PCT:
        score += 2
        reasons.append("very low humidity")
    elif humidity <= HUMIDITY_MODERATE_PCT:
        score += 1
        reasons.append("low humidity")

    # Low raw reading means drier soil for this particular sensor.
    if soil <= SOIL_VERY_DRY_RAW:
        score += 2
        reasons.append("very dry soil")
    elif soil <= SOIL_DRY_RAW:
        score += 1
        reasons.append("dry soil")

    if smoke is not None and smoke >= MQ2_ELEVATED_RAW:
        score += 2
        reasons.append("elevated MQ-2 reading")

    risk = "HIGH" if score >= 4 else "MODERATE" if score >= 2 else "LOW"
    return risk, score, reasons


def send_telegram_alert(message):
    env_path = ROOT / ".env"
    if env_path.exists():
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

    token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("Set BOT_TOKEN and CHAT_ID in the project's .env file.")

    response = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": chat_id, "text": message},
        timeout=10,
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")


def update_high_alert_state(risk, data, score, reasons):
    """
    Send one Telegram message whenever the station enters MODERATE or HIGH.
    A change from MODERATE to HIGH sends a new escalation message.
    Returning to LOW resets the state so a later risk episode alerts again.
    """
    initialize_database()

    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(
            "SELECT last_alerted_risk FROM station_alert_state WHERE station_id = ?",
            (STATION_ID,),
        ).fetchone()
        previous_risk = row[0] if row else "LOW"

        if risk == "LOW":
            connection.execute(
                """
                INSERT INTO station_alert_state
                    (station_id, high_alert_active, last_alerted_risk)
                VALUES (?, 0, 'LOW')
                ON CONFLICT(station_id) DO UPDATE SET
                    high_alert_active = 0,
                    last_alerted_risk = 'LOW'
                """,
                (STATION_ID,),
            )
            connection.commit()
            return

        if risk not in ("MODERATE", "HIGH") or risk == previous_risk:
            return

        heading = (
            "⚠️ MODERATE FIRE RISK"
            if risk == "MODERATE"
            else "🔥 HIGH FIRE RISK"
        )
        message = (
            f"{heading} — Station 1\\n"
            f"Temperature: {float(data['temperature']):.1f} °C\\n"
            f"Humidity: {float(data['humidity']):.1f}%\\n"
            f"Soil raw: {int(data['soil_moisture_raw'])}\\n"
            f"MQ-2 raw: {data.get('smoke_raw', 'N/A')}\\n"
            f"Risk score: {score}\\n"
            f"Factors: {', '.join(reasons) if reasons else 'Threshold reached'}"
        )

        # Update the database only after Telegram confirms successful delivery.
        # If sending fails, the next dashboard refresh will retry.
        send_telegram_alert(message)
        connection.execute(
            """
            INSERT INTO station_alert_state
                (station_id, high_alert_active, last_alerted_risk)
            VALUES (?, ?, ?)
            ON CONFLICT(station_id) DO UPDATE SET
                high_alert_active = excluded.high_alert_active,
                last_alerted_risk = excluded.last_alerted_risk
            """,
            (STATION_ID, 1 if risk == "HIGH" else 0, risk),
        )
        connection.commit()


def read_station_history(station_id):
    initialize_database()
    with sqlite3.connect(DB_PATH) as connection:
        return pd.read_sql_query(
            """
            SELECT recorded_at, temperature_c, humidity_percent, soil_raw, mq2_raw, fire_risk
            FROM station_readings
            WHERE station_id = ?
            ORDER BY recorded_at
            """,
            connection,
            params=(station_id,),
        )


def save_station_reading(data, risk):
    initialize_database()
    recorded_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with sqlite3.connect(DB_PATH) as connection:
        connection.execute(
            """
            INSERT INTO station_readings
            (station_id, recorded_at, temperature_c, humidity_percent, soil_raw, mq2_raw, fire_risk)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                STATION_ID,
                recorded_at,
                float(data["temperature"]),
                float(data["humidity"]),
                int(data["soil_moisture_raw"]),
                int(data["smoke_raw"]) if data.get("smoke_raw") is not None else None,
                risk,
            ),
        )
        connection.commit()
    return recorded_at


class StationSerialReader:
    """Background serial reader that keeps COM15 open and stores the newest valid JSON."""

    def __init__(self, port, baud):
        import threading
        self.port = port
        self.baud = baud
        self.latest_data = None
        self.last_received = None
        self.last_error = None
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()

    def _read_loop(self):
        import time
        while not self.stop_event.is_set():
            try:
                with serial.Serial(self.port, self.baud, timeout=1) as connection:
                    self.last_error = None
                    while not self.stop_event.is_set():
                        raw_line = connection.readline()
                        if not raw_line:
                            continue
                        line = raw_line.decode("utf-8", errors="replace").strip()

                        # Accept plain JSON or a line containing a label plus JSON.
                        left = line.find("{")
                        right = line.rfind("}")
                        if left < 0 or right <= left:
                            continue
                        try:
                            candidate = json.loads(line[left:right + 1])
                        except json.JSONDecodeError:
                            continue

                        required = ("temperature", "humidity", "soil_moisture_raw")
                        if not all(key in candidate for key in required):
                            continue
                        candidate.setdefault("station", "Station_1")
                        with self.lock:
                            self.latest_data = candidate
                            self.last_received = time.time()
            except Exception as error:
                self.last_error = str(error)
                time.sleep(2)

    def get_latest(self):
        import time
        with self.lock:
            data = dict(self.latest_data) if self.latest_data else None
            received = self.last_received
        if data is None or received is None or time.time() - received > 12:
            detail = self.last_error or "No valid sensor JSON received in the last 12 seconds."
            raise TimeoutError(detail)
        return data


@st.cache_resource
def get_station_serial_reader():
    # Keep one reader as the sole owner of COM15 across Streamlit reruns.
    return StationSerialReader(SERIAL_PORT, SERIAL_BAUD)


def get_live_station_data():
    return get_station_serial_reader().get_latest()


# ---------------- WEATHER ----------------

def get_current_weather():
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": 31.5332,
            "longitude": 76.8923,
            "current": (
                "temperature_2m,relative_humidity_2m,"
                "precipitation,wind_speed_10m"
            ),
            "timezone": "Asia/Kolkata",
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["current"]


FORECAST_LOCATIONS = [
    (31.1048, 77.1734),  # Shimla
    (31.7089, 76.9320),  # Mandi
    (31.9579, 77.1095),  # Kullu
    (32.2190, 76.3234),  # Dharamshala
    (31.5370, 78.2690),  # Reckong Peo
]


# ---------------- EXISTING HOTSPOT MODEL ----------------

@st.cache_resource
def load_hotspot_model():
    model_files = list((ROOT / "models").glob("himachal_calibrated_hotspot_*.pkl"))
    if not model_files:
        model_files = list((ROOT / "models").glob("himachal_nextday_hotspot_*.pkl"))
    model_files.sort(key=lambda path: path.stat().st_mtime)
    if not model_files:
        raise FileNotFoundError("No Himachal next-day hotspot model was found.")
    return joblib.load(model_files[-1])


@st.cache_data(ttl=3600)
def get_forecast_features():
    forecast_day = pd.Timestamp.now(tz="UTC").normalize()
    hourly_variables = [
        "temperature_2m",
        "relative_humidity_2m",
        "dew_point_2m",
        "precipitation",
        "wind_speed_10m",
        "soil_moisture_0_to_7cm",
        "soil_moisture_7_to_28cm",
    ]
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": ",".join(str(point[0]) for point in FORECAST_LOCATIONS),
            "longitude": ",".join(str(point[1]) for point in FORECAST_LOCATIONS),
            "hourly": ",".join(hourly_variables),
            "forecast_days": 2,
            "timezone": "UTC",
            "wind_speed_unit": "kmh",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    locations = payload if isinstance(payload, list) else [payload]
    if len(locations) != len(FORECAST_LOCATIONS):
        raise ValueError("Weather service returned an unexpected number of locations.")

    point_rows = []
    for location in locations:
        hourly = pd.DataFrame(location["hourly"])
        hourly["time"] = pd.to_datetime(hourly["time"], utc=True)
        day_rows = hourly.loc[hourly["time"].dt.date == forecast_day.date()]
        if day_rows.empty:
            raise ValueError("No forecast hours were returned for today (UTC).")

        point_rows.append({
            "temperature_2m_mean": pd.to_numeric(day_rows["temperature_2m"], errors="coerce").mean(),
            "relative_humidity_2m_mean": pd.to_numeric(day_rows["relative_humidity_2m"], errors="coerce").mean(),
            "dew_point_2m_mean": pd.to_numeric(day_rows["dew_point_2m"], errors="coerce").mean(),
            "precipitation_sum": pd.to_numeric(day_rows["precipitation"], errors="coerce").sum(),
            "wind_speed_10m_mean": pd.to_numeric(day_rows["wind_speed_10m"], errors="coerce").mean(),
            "soil_moisture_0_to_7cm_mean": pd.to_numeric(day_rows["soil_moisture_0_to_7cm"], errors="coerce").mean(),
            "soil_moisture_7_to_28cm_mean": pd.to_numeric(day_rows["soil_moisture_7_to_28cm"], errors="coerce").mean(),
        })

    regional = pd.DataFrame(point_rows).mean(numeric_only=True)
    if not np.isfinite(regional.to_numpy(dtype=float)).all():
        raise ValueError("The forecast contains missing weather values.")

    day_of_year = forecast_day.day_of_year
    features = regional.to_dict()
    features["season_sin"] = float(np.sin(2 * np.pi * day_of_year / 365.25))
    features["season_cos"] = float(np.cos(2 * np.pi * day_of_year / 365.25))
    return {name: float(value) for name, value in features.items()}, forecast_day.date()


# ---------------- PAGE ----------------

st.title("🌲 Forest Fire Monitoring")
st.caption("Live sensor monitoring dashboard — Station 1")
with st.expander("How station fire risk is calculated"):
    st.write(
        "LOW = score 0–1; MODERATE = 2–3; HIGH = 4 or more. "
        "High temperature, low humidity, low soil raw values (drier soil), "
        "and elevated MQ-2 readings increase the score."
    )
    st.caption(
        "These are provisional demonstration thresholds, not validated fire-detection limits. "
        "Calibrate the soil and MQ-2 thresholds with actual dry/wet and clean-air/smoke tests."
    )


@st.fragment(run_every="3s")
def live_station_panel():
    st.subheader("Station 1 — Live Sensor Readings")

    try:
        live_data = get_live_station_data()
        risk, risk_score, risk_reasons = calculate_fire_risk(live_data)
        saved_time = save_station_reading(live_data, risk)

        try:
            update_high_alert_state(risk, live_data, risk_score, risk_reasons)
        except Exception as telegram_error:
            st.warning(f"Telegram alert could not be sent: {telegram_error}")

        st.success(f"Station 1 is ONLINE — receiving live data from RX NodeMCU ({SERIAL_PORT}).")
        st.caption(f"Last received: {saved_time}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Temperature", f"{float(live_data['temperature']):.1f} °C")
        c2.metric("Humidity", f"{float(live_data['humidity']):.1f}%")
        c3.metric("Soil sensor (raw)", f"{int(live_data['soil_moisture_raw'])}")
        smoke_value = live_data.get("smoke_raw")
        c4.metric("MQ-2 (raw)", str(int(smoke_value)) if smoke_value is not None else "No data")
        if risk == "HIGH":
            st.error(f"🔥 FIRE RISK: {risk} (score {risk_score})")
        elif risk == "MODERATE":
            st.warning(f"⚠️ FIRE RISK: {risk} (score {risk_score})")
        else:
            st.success(f"🟢 FIRE RISK: {risk} (score {risk_score})")
        st.caption("Risk factors: " + (", ".join(risk_reasons) if risk_reasons else "No elevated factors detected."))

        st.caption(
            "Sensor values are displayed as received. Soil and MQ-2 values are raw ADC readings, "
            "not calibrated moisture percentage or smoke concentration."
        )

    except Exception as error:
        st.error(
            f"Station 1 is OFFLINE or no valid serial data was received on {SERIAL_PORT}. "
            "Close Arduino IDE Serial Monitor and check that the RX NodeMCU is connected. "
            f"Details: {error}"
        )

    st.divider()
    st.subheader("Station 1 reading history")
    history = read_station_history(STATION_ID)

    if history.empty:
        st.info("No saved readings yet. Waiting for the first successful serial reading.")
        return

    history["recorded_at"] = pd.to_datetime(history["recorded_at"], errors="coerce")
    history = history.dropna(subset=["recorded_at"]).set_index("recorded_at")

    graph1, graph2 = st.columns(2)
    with graph1:
        st.caption("Temperature")
        st.line_chart(history[["temperature_c"]])
    with graph2:
        st.caption("Humidity")
        st.line_chart(history[["humidity_percent"]])

    graph3, graph4 = st.columns(2)
    with graph3:
        st.caption("Soil sensor raw reading")
        st.line_chart(history[["soil_raw"]])
    with graph4:
        st.caption("MQ-2 raw reading")
        st.line_chart(history[["mq2_raw"]])

    st.subheader("Saved readings")
    display_history = history.sort_index(ascending=False).copy()
    # Multiple readings can share the same second-level timestamp. Styler
    # requires unique index labels, so make the timestamp an ordinary column
    # and reset the display index before applying row colours.
    display_history.insert(
        0,
        "recorded_at",
        display_history.index.strftime("%Y-%m-%d %H:%M:%S"),
    )
    display_history = display_history.reset_index(drop=True)

    def colour_risk_row(row):
        risk_value = str(row.get("fire_risk", "")).upper()
        if risk_value == "HIGH":
            return ["background-color: #ffd6d6; color: #8b0000"] * len(row)
        if risk_value == "MODERATE":
            return ["background-color: #fff2cc; color: #7f6000"] * len(row)
        if risk_value == "LOW":
            return ["background-color: #d9ead3; color: #274e13"] * len(row)
        return [""] * len(row)

    st.dataframe(
        display_history.style.apply(colour_risk_row, axis=1),
        use_container_width=True,
    )

    csv_data = display_history.to_csv().encode("utf-8")
    st.download_button(
        "Download station history as CSV",
        data=csv_data,
        file_name="station_1_readings.csv",
        mime="text/csv",
        key="download_station_history",
    )


live_station_panel()


st.divider()
st.subheader("Local Weather — Sundernagar, Mandi")

if st.button("Refresh weather"):
    get_current_weather.clear() if hasattr(get_current_weather, "clear") else None
    st.cache_data.clear()

try:
    weather = get_current_weather()
    st.caption(f"Weather time: {weather['time']}")

    w1, w2, w3, w4 = st.columns(4)
    w1.metric("Temperature", f"{weather['temperature_2m']} °C")
    w2.metric("Humidity", f"{weather['relative_humidity_2m']}%")
    w3.metric("Wind speed", f"{weather['wind_speed_10m']} km/h")
    w4.metric("Precipitation", f"{weather['precipitation']} mm")

    st.caption("Area weather estimate; not measured by the station sensors.")

except Exception as error:
    st.error(f"Could not load current weather: {error}")


st.divider()
with st.container(border=True):
    st.subheader("Experimental next-day hotspot estimate")
    st.caption(
        "Weather-based estimate for satellite hotspot candidates across five Himachal locations."
    )

    if st.button("Refresh hotspot estimate"):
        get_forecast_features.clear()

    try:
        model_package = load_hotspot_model()
        forecast_values, forecast_day = get_forecast_features()
        model_input = pd.DataFrame([forecast_values])[model_package["features"]]
        raw_score = float(model_package["model"].predict_proba(model_input)[0, 1])
        calibrator = model_package.get("calibrator")
        if calibrator is not None:
            clipped_score = float(np.clip(raw_score, 1e-6, 1 - 1e-6))
            score_logit = np.log(clipped_score / (1 - clipped_score))
            score = float(calibrator.predict_proba([[score_logit]])[0, 1])
        else:
            score = raw_score

        thresholds = model_package.get("risk_band_thresholds", {})
        if thresholds:
            if score < thresholds["low_max_score"]:
                relative_band = "Low"
            elif score < thresholds["moderate_max_score"]:
                relative_band = "Moderate"
            else:
                relative_band = "High"
        else:
            relative_band = "Uncalibrated"

        target_day = forecast_day + timedelta(days=1)
        if relative_band == "High":
            st.error("HIGH RELATIVE HOTSPOT-CANDIDATE BAND")
        elif relative_band == "Moderate":
            st.warning("MODERATE RELATIVE HOTSPOT-CANDIDATE BAND")
        elif relative_band == "Low":
            st.success("LOW RELATIVE HOTSPOT-CANDIDATE BAND")

        if relative_band != "Uncalibrated":
            st.markdown(f"**Relative score band: {relative_band}**")
        st.metric(f"Next-day model score · {target_day}", f"{score:.1%}", border=True)

        test_rates = model_package.get("held_out_test_band_detection_rates", {})
        band_key = relative_band.lower()
        band_result = test_rates.get(band_key, {})
        detection_rate = band_result.get("candidate_detection_rate")
        if detection_rate is not None:
            st.caption(
                f"In the held-out test data, the {relative_band.lower()} band had a FIRMS "
                f"hotspot candidate detected on {detection_rate:.1%} of days."
            )
        st.caption(
            "Experimental, validation-calibrated score. Relative bands come from validation data. "
            "It predicts satellite hotspot candidates, not confirmed fires, and does not use MQ-2 "
            "readings. Live station sensor readings are displayed separately and are not inputs "
            "to this model. Live forecast weather may differ from historical training data. "
            "Not an operational fire alarm."
        )
    except Exception as error:
        st.warning(f"Could not load the next-day estimate: {error}")


st.divider()
st.caption(
    "Soil and MQ-2 charts show raw sensor readings. They need calibration before "
    "they can be interpreted as moisture percentage or smoke concentration."
)
