#include <ESP8266WiFi.h>
#include <ESP8266HTTPClient.h>

// ESP32 hotspot credentials
const char* ssid = "ForestFire_Network";
const char* password = "ForestFire123";

// ESP32 server address
const char* serverURL = "http://192.168.4.1/data";

WiFiClient client;

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println();
  Serial.println("Forest Fire Monitoring RX Started");

  WiFi.begin(ssid, password);

  Serial.print("Connecting to ESP32");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("Connected to ESP32 Wi-Fi!");
  Serial.print("RX IP Address: ");
  Serial.println(WiFi.localIP());
}

void loop() {

  if (WiFi.status() == WL_CONNECTED) {

    HTTPClient http;

    http.begin(client, serverURL);

    int httpCode = http.GET();

    if (httpCode == HTTP_CODE_OK) {

      String payload = http.getString();

      Serial.println("STATION 1 DATA:");
      Serial.println(payload);

    } else {
      Serial.print("HTTP Error: ");
      Serial.println(httpCode);
    }

    http.end();

  } else {
    Serial.println("Wi-Fi disconnected. Reconnecting...");
    WiFi.begin(ssid, password);
  }

  delay(2000);
}
