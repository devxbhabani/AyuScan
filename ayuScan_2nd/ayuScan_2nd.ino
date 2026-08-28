#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include "MAX30105.h"
#include "MPU6050.h"

#define DEVICE_ID "patient_02"

// --- Pins ---
#define ECG_PIN  32
#define LO_PLUS  34
#define LO_MINUS 33

// --- BLE UUIDs ---
#define SERVICE_UUID        "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define ECG_CHAR_UUID       "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define VITALS_CHAR_UUID    "e3223119-9445-4e96-a4a1-85358ce291d0"

BLEServer* pServer = NULL;
BLECharacteristic* pEcgCharacteristic = NULL;
BLECharacteristic* pVitalsCharacteristic = NULL;
bool deviceConnected = false;
bool oldDeviceConnected = false;

// --- Sensors ---
MAX30105 max30102;
MPU6050  mpu;
bool mpuAvailable = false;

// --- ECG Buffering (250 Hz) ---
#define ECG_SAMPLE_RATE_HZ 250
#define ECG_BATCH_SIZE 25 // 100ms
volatile bool ecgSampleReady = false;
int ecgBuffer[ECG_BATCH_SIZE];
int ecgIndex = 0;
hw_timer_t * ecgTimer = NULL;
portMUX_TYPE timerMux = portMUX_INITIALIZER_UNLOCKED;

// --- PPG Buffering (100 Hz) ---
#define PPG_SAMPLE_RATE_HZ 100
#define PPG_BATCH_SIZE 10 // 100ms
uint32_t redBuffer[PPG_BATCH_SIZE];
uint32_t irBuffer[PPG_BATCH_SIZE];
int ppgIndex = 0;

// --- Fall detection ────────────────────────────────────────────
bool     inFreefall    = false;
uint32_t freefallStart = 0;

// ================== BLE SERVER CALLBACKS ==================
class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
      deviceConnected = true;
      Serial.println("BLE Client Connected");
    }
    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      Serial.println("BLE Client Disconnected");
    }
};

void setupBLE() {
  BLEDevice::init("AyuScan_Node");
  BLEDevice::setMTU(512);
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService *pService = pServer->createService(SERVICE_UUID);

  pEcgCharacteristic = pService->createCharacteristic(
                      ECG_CHAR_UUID,
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
  pEcgCharacteristic->addDescriptor(new BLE2902());

  pVitalsCharacteristic = pService->createCharacteristic(
                      VITALS_CHAR_UUID,
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
  pVitalsCharacteristic->addDescriptor(new BLE2902());

  pService->start();
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);
  pAdvertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();
  Serial.println("BLE Advertising started...");
}

// ================== ECG TIMER ISR ==================
void IRAM_ATTR onTimer() {
  portENTER_CRITICAL_ISR(&timerMux);
  ecgSampleReady = true;
  portEXIT_CRITICAL_ISR(&timerMux);
}

// ================== SETUP ==================
void setup() {
  Serial.begin(115200);
  delay(100);
  Serial.println("\n--- Starting AyuScan 2nd Device ---");

  pinMode(ECG_PIN, INPUT);
  pinMode(LO_PLUS,  INPUT);
  pinMode(LO_MINUS, INPUT);
  analogReadResolution(12);

  Wire.begin(21, 22);
  Wire.setClock(400000);

  setupBLE();

  // MAX30102
  if (!max30102.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 not found.");
    while (1) delay(1000);
  }
  max30102.setup();
  max30102.setPulseAmplitudeRed(0x3F);
  max30102.setPulseAmplitudeIR(0x3F);
  max30102.setPulseAmplitudeGreen(0);
  Serial.println("MAX30102 configured");
  
  // Enable temperature reading
  max30102.enableDIETEMPRDY();

  // MPU6050
  mpu.initialize();
  if (mpu.testConnection()) {
      Serial.println("MPU6050 OK");
      mpuAvailable = true;
  } else {
      Serial.println("MPU6050 not found");
      mpuAvailable = false;
  }

  // ECG timer
  ecgTimer = timerBegin(1000000);
  timerAttachInterrupt(ecgTimer, &onTimer);
  timerAlarm(ecgTimer, 4000, true, 0); // 250Hz

  Serial.println("Setup complete.");
}

void sendECGPacket() {
  if (!deviceConnected) return;

  char payload[300];
  int offset = snprintf(payload, sizeof(payload), "{\"device\":\"%s\",\"type\":\"ecg\",\"fs\":%d,\"data\":[", DEVICE_ID, ECG_SAMPLE_RATE_HZ);
  for (int i = 0; i < ECG_BATCH_SIZE; i++) {
    offset += snprintf(payload + offset, sizeof(payload) - offset, "%d", ecgBuffer[i]);
    if (i < ECG_BATCH_SIZE - 1) {
      offset += snprintf(payload + offset, sizeof(payload) - offset, ",");
    }
  }
  snprintf(payload + offset, sizeof(payload) - offset, "]}");

  pEcgCharacteristic->setValue((uint8_t*)payload, strlen(payload));
  pEcgCharacteristic->notify();
}

void sendPPGPacket() {
  if (!deviceConnected) return;

  char payload[600];
  int offset = snprintf(payload, sizeof(payload), "{\"device\":\"%s\",\"type\":\"ppg_raw\",\"fs\":%d,\"red\":[", DEVICE_ID, PPG_SAMPLE_RATE_HZ);
  for (int i = 0; i < PPG_BATCH_SIZE; i++) {
    offset += snprintf(payload + offset, sizeof(payload) - offset, "%lu", redBuffer[i]);
    if (i < PPG_BATCH_SIZE - 1) offset += snprintf(payload + offset, sizeof(payload) - offset, ",");
  }
  offset += snprintf(payload + offset, sizeof(payload) - offset, "],\"ir\":[");
  for (int i = 0; i < PPG_BATCH_SIZE; i++) {
    offset += snprintf(payload + offset, sizeof(payload) - offset, "%lu", irBuffer[i]);
    if (i < PPG_BATCH_SIZE - 1) offset += snprintf(payload + offset, sizeof(payload) - offset, ",");
  }
  snprintf(payload + offset, sizeof(payload) - offset, "]}");

  pVitalsCharacteristic->setValue((uint8_t*)payload, strlen(payload));
  pVitalsCharacteristic->notify();
}

void detectFall() {
  if (!mpuAvailable) return;
  int16_t ax, ay, az, gx, gy, gz;
  mpu.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);
  float xg = ax/16384.0f, yg = ay/16384.0f, zg = az/16384.0f;
  float total = sqrt(xg*xg + yg*yg + zg*zg);
  if (!inFreefall && total < 0.4f) { inFreefall = true; freefallStart = millis(); }
  if (inFreefall) {
    if (total > 3.0f) {
      uint32_t dur = millis() - freefallStart;
      if (dur > 80 && dur < 1000) { 
        Serial.println("[FALL] Detected!"); 
        if (deviceConnected) {
          char payload[100];
          snprintf(payload, sizeof(payload), "{\"device\":\"%s\",\"type\":\"fall\"}", DEVICE_ID);
          pVitalsCharacteristic->setValue((uint8_t*)payload, strlen(payload));
          pVitalsCharacteristic->notify();
        }
      }
      inFreefall = false;
    }
    if (millis() - freefallStart > 1500) inFreefall = false;
  }
}

void loop() {
  static unsigned long tempLastRead = 0;
  static unsigned long fallLastRead = 0;
  unsigned long currentMillis = millis();

  // Read Temp 1Hz
  if (currentMillis - tempLastRead >= 1000) {
    tempLastRead = currentMillis;
    float rawTemp = max30102.readTemperature();
    float correctedTemp = rawTemp - 2.5f;
    Serial.printf("[Temp] %.2fC\n", correctedTemp);

    if (deviceConnected && pVitalsCharacteristic != NULL) {
      char payload[120];
      snprintf(payload, sizeof(payload),
        "{\"device\":\"%s\",\"type\":\"temp\",\"val\":%.2f}",
        DEVICE_ID, correctedTemp);
      pVitalsCharacteristic->setValue((uint8_t*)payload, strlen(payload));
      pVitalsCharacteristic->notify();
    }
  }

  // Fall detection 20Hz (every 50ms)
  if (currentMillis - fallLastRead >= 50) {
      fallLastRead = currentMillis;
      detectFall();
  }

  // BLE Reconnection
  if (!deviceConnected && oldDeviceConnected) {
      delay(500);
      pServer->startAdvertising();
      Serial.println("BLE Client Disconnected. Restarting advertising...");
      oldDeviceConnected = deviceConnected;
  }
  if (deviceConnected && !oldDeviceConnected) {
      oldDeviceConnected = deviceConnected;
  }

  // Read ECG
  if (ecgSampleReady) {
    portENTER_CRITICAL(&timerMux);
    ecgSampleReady = false;
    portEXIT_CRITICAL(&timerMux);

    if (digitalRead(LO_PLUS) || digitalRead(LO_MINUS)) {
      ecgBuffer[ecgIndex++] = 0;
    } else {
      ecgBuffer[ecgIndex++] = analogRead(ECG_PIN);
    }

    if (ecgIndex >= ECG_BATCH_SIZE) {
      sendECGPacket();
      ecgIndex = 0;
    }
  }

  // Read PPG
  max30102.check();
  while (max30102.available()) {
    irBuffer[ppgIndex]  = max30102.getFIFOIR();
    redBuffer[ppgIndex] = max30102.getFIFORed();
    max30102.nextSample();

    ppgIndex++;
    if (ppgIndex >= PPG_BATCH_SIZE) {
      sendPPGPacket();
      ppgIndex = 0;
    }
  }
}
