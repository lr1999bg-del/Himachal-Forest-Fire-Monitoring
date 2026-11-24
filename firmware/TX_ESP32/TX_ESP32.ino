#include <WiFi.h>
#include <WebServer.h>
#include <DHT.h>

// Wi-Fi hotspot settings
const char* ssid = "ForestFire_Network";
const char* password = "ForestFire123";

// Sensor pins
#define DHTPIN 4
#define DHTTYPE DHT22

#define SOIL_PIN 34
#define MQ2_PIN 35

DHT dht(DHTPIN, DHTTYPE);
WebServer server(80);

// Latest sensor readings
float temperature = 0;
float humidity = 0;
int soilMoisture = 0;
int smoke = 0;

void sendSensorData() {
  String json = "{";
  json += "\"station\":\"Station_1\",";
  json += "\"temperature\":" + String(temperature, 1) + ",";
  json += "\"humidity\":" + String(humidity, 1) + ",";
  json += "\"soil_moisture_raw\":" + String(soilMoisture) + ",";
  json += "\"smoke_raw\":" + String(smoke);
  json += "}";

  server.send(200, "application/json", json);
}

void setup() {
  Serial.begin(115200);

  dht.begin();

  pinMode(SOIL_PIN, INPUT);
  pinMode(MQ2_PIN, INPUT);

  // Create ESP32 Wi-Fi hotspot
  WiFi.softAP(ssid, password);

  Serial.println();
  Serial.println("Forest Fire Monitoring TX Started");
  Serial.print("Wi-Fi IP: ");
  Serial.println(WiFi.softAPIP());

  server.on("/data", HTTP_GET, sendSensorData);
  server.begin();

  Serial.println("HTTP Server Started");
}

void loop() {
  server.handleClient();

  static unsigned long lastRead = 0;

  if (millis() - lastRead >= 2000) {
    lastRead = millis();

    float t = dht.readTemperature();
    float h = dht.readHumidity();

    if (!isnan(t) && !isnan(h)) {
      temperature = t;
      humidity = h;
    }

    soilMoisture = analogRead(SOIL_PIN);
    smoke = analogRead(MQ2_PIN);

    Serial.println("----- SENSOR READINGS -----");
    Serial.print("Temperature: ");
    Serial.println(temperature);

    Serial.print("Humidity: ");
    Serial.println(humidity);

    Serial.print("Soil Moisture: ");
    Serial.println(soilMoisture);

    Serial.print("MQ2: ");
    Serial.println(smoke);
  }
}
