#include <Wire.h>
#include "MAX30105.h"
#include <Adafruit_MLX90614.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

#define DEVICE_ID "patient_01"

// --- I2C / Mux Settings ---
#define I2C_SDA 22
#define I2C_SCL 23
#define TCA9548A_ADDRESS 0x70
#define MAX30102_CH 1
#define MLX90614_CH 2

// --- Pins ---
#define EXG_PIN 0

// --- BLE UUIDs ---
#define SERVICE_UUID        "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define ECG_CHAR_UUID       "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define PPG_RAW_CHAR_UUID   "e3223119-9445-4e96-a4a1-85358ce291d0"

BLEServer* pServer = NULL;
BLECharacteristic* pEcgCharacteristic = NULL;
BLECharacteristic* pPpgCharacteristic = NULL;
bool deviceConnected = false;
bool oldDeviceConnected = false;

// --- Sensors ---
MAX30105 maxSensor;
Adafruit_MLX90614 mlx = Adafruit_MLX90614();
bool mlxAvailable = false; // set true only if MLX found at startup (Hydrocheck pattern)

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
  BLEDevice::setMTU(512); // Prevent JSON packet truncation
  pServer = BLEDevice::createServer();
  pServer->setCallbacks(new MyServerCallbacks());

  BLEService *pService = pServer->createService(SERVICE_UUID);

  pEcgCharacteristic = pService->createCharacteristic(
                      ECG_CHAR_UUID,
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
  pEcgCharacteristic->addDescriptor(new BLE2902());

  pPpgCharacteristic = pService->createCharacteristic(
                      PPG_RAW_CHAR_UUID,
                      BLECharacteristic::PROPERTY_NOTIFY
                    );
  pPpgCharacteristic->addDescriptor(new BLE2902());

  pService->start();
  BLEAdvertising *pAdvertising = BLEDevice::getAdvertising();
  pAdvertising->addServiceUUID(SERVICE_UUID);
  pAdvertising->setScanResponse(true);
  pAdvertising->setMinPreferred(0x06);
  pAdvertising->setMinPreferred(0x12);
  BLEDevice::startAdvertising();
  Serial.println("BLE Advertising started...");
}

// ================== MUX HELPER ==================
void tcaSelect(uint8_t channel) {
  if (channel > 7) return;
  Wire.beginTransmission(TCA9548A_ADDRESS);
  Wire.write(1 << channel);
  Wire.endTransmission();
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
  delay(1000);
  Serial.println("\n--- Starting AyuScan Raw ---");

  pinMode(EXG_PIN, INPUT);
  Serial.println("PinMode set");

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);
  Serial.println("Wire started");

  setupBLE();
  Serial.println("BLE configured");

  // --- init MAX30102 ---
  tcaSelect(MAX30102_CH);
  Serial.println("TCA selected");

  if (!maxSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 not found.");
    while (1) delay(1000);
  }
  Serial.println("MAX30102 found");

  maxSensor.setup();
  maxSensor.setPulseAmplitudeRed(0x3F);
  maxSensor.setPulseAmplitudeIR(0x3F);
  maxSensor.setPulseAmplitudeGreen(0);
  Serial.println("MAX30102 configured");

  // --- init MLX90614 (Hydrocheck pattern: tcaSelect -> begin -> flag) ---
  tcaSelect(MLX90614_CH);
  Wire.setClock(100000); // MLX90614 (SMBus/PEC) is unreliable above 100kHz
  if (mlx.begin()) {
    Serial.println("MLX90614 OK");
    mlxAvailable = true;
  } else {
    Serial.println("MLX90614 NOT FOUND - temperature disabled");
    mlxAvailable = false;
  }
  Wire.setClock(400000); // restore fast clock for MAX30102
  // Always switch back to MAX30102 after touching the mux
  tcaSelect(MAX30102_CH);

  // --- ECG timer (250 Hz) ---
  ecgTimer = timerBegin(1000000);
  timerAttachInterrupt(ecgTimer, &onTimer);
  timerAlarm(ecgTimer, 4000, true, 0);
  Serial.println("Timer configured");

  Serial.println("Setup complete.");
}

// ================== DATA SENDER ==================
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

  pPpgCharacteristic->setValue((uint8_t*)payload, strlen(payload));
  pPpgCharacteristic->notify();
}

// ================== LOOP ==================
void loop() {
  // --- Read Temperature 1Hz ---
  // FIX: reading + Serial printing now happens regardless of BLE
  // connection state. Only the BLE *notify* is gated behind
  // deviceConnected. Previously the whole block (including the
  // Serial.printf) was gated behind deviceConnected, so if no BLE
  // client was connected you'd never see any [Temp] output at all,
  // even if the sensor itself was working fine.
  static unsigned long tempLastRead = 0;
  unsigned long currentMillis = millis();
  if (currentMillis - tempLastRead >= 1000) {
    tempLastRead = currentMillis;
    if (mlxAvailable) {
      tcaSelect(MLX90614_CH);
      Wire.setClock(100000);   // MLX90614 (SMBus/PEC) is unreliable above 100kHz
      float objTemp  = mlx.readObjectTempC();
      float ambTemp  = mlx.readAmbientTempC();
      Wire.setClock(400000);   // restore fast clock for MAX30102
      tcaSelect(MAX30102_CH); // switch back immediately (Hydrocheck pattern)

      // Always print, regardless of BLE connection state
      Serial.printf("[Temp] Object: %.2fC  Ambient: %.2fC\n", objTemp, ambTemp);

      // Only notify over BLE if a client is actually connected
      if (deviceConnected && pPpgCharacteristic != NULL) {
        char payload[120];
        snprintf(payload, sizeof(payload),
          "{\"device\":\"%s\",\"type\":\"temp\",\"val\":%.2f,\"ambient\":%.2f}",
          DEVICE_ID, objTemp, ambTemp);
        pPpgCharacteristic->setValue((uint8_t*)payload, strlen(payload));
        pPpgCharacteristic->notify();
      }
    } else {
      Serial.println("[Temp] MLX90614 not available (mlxAvailable=false)");
    }
  }

  // --- BLE Reconnection Logic ---
  if (!deviceConnected && oldDeviceConnected) {
      delay(500);
      pServer->startAdvertising();
      Serial.println("BLE Client Disconnected. Restarting advertising...");
      oldDeviceConnected = deviceConnected;
  }
  if (deviceConnected && !oldDeviceConnected) {
      oldDeviceConnected = deviceConnected;
  }

  // --- 1. Read ECG ---
  if (ecgSampleReady) {
    portENTER_CRITICAL(&timerMux);
    ecgSampleReady = false;
    portEXIT_CRITICAL(&timerMux);

    ecgBuffer[ecgIndex++] = analogRead(EXG_PIN);
    if (ecgIndex >= ECG_BATCH_SIZE) {
      sendECGPacket();
      ecgIndex = 0;
    }
  }

  // --- 2. Read PPG (MAX30102) FIFO ---
  tcaSelect(MAX30102_CH);
  maxSensor.check();
  while (maxSensor.available()) {
    irBuffer[ppgIndex] = maxSensor.getFIFOIR();
    redBuffer[ppgIndex] = maxSensor.getFIFORed();
    maxSensor.nextSample();

    ppgIndex++;
    if (ppgIndex >= PPG_BATCH_SIZE) {
      sendPPGPacket();
      ppgIndex = 0;
    }
  }
}
