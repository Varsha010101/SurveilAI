#include <WiFi.h>
#include <WebServer.h>

const char* ssid = "Varsha";
const char* password = "varsha0125";
const int buzzerPin = 5; // Change this to the GPIO pin connected to your buzzer
const int ledPin = 2; // Onboard LED (usually GPIO 2 on ESP32)

WebServer server(80);

void handleBuzz() {
    if (server.hasArg("buzz")) {
        String buzzState = server.arg("buzz");
        if (buzzState == "on") {
            digitalWrite(buzzerPin, HIGH);
            delay(1000); // Buzzer on for 1 second
            digitalWrite(buzzerPin, LOW);
            server.send(200, "text/plain", "Buzzer activated");
            return;
        }
    }
    server.send(400, "text/plain", "Invalid Request");
}

void setup() {
    Serial.begin(115200);
    pinMode(buzzerPin, OUTPUT);
    pinMode(ledPin, OUTPUT);
    digitalWrite(buzzerPin, LOW);
    digitalWrite(ledPin, LOW);

    // Connect to Wi-Fi
    WiFi.begin(ssid, password);
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(1000);
        Serial.print(".");
    }
    Serial.println("\nConnected to WiFi");
    Serial.println(WiFi.localIP());

    // Turn on onboard LED to indicate successful Wi-Fi connection
    digitalWrite(ledPin, HIGH);

    // Define Web Server Route
    server.on("/buzz", handleBuzz);

    // Start server
    server.begin();
}

void loop() {
    server.handleClient();
}