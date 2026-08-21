/*
  Wearable Node — Seeed XIAO ESP32-C6
  --------------------------------------------------
  Sensors:
    - MAX30102 (PPG)  -> behind TCA9548A I2C mux, channel MAX30102_CH
      Gives: BPM (with contact-quality gating + cross-cycle smoothing),
             SpO2, HRV (SDNN + RMSSD from beat-to-beat intervals)
    - BioAmp EXG Pill  -> analog pin EXG_PIN (ADC)
      Gives: raw ECG waveform, streamed for plotting

  Design notes:
    - BPM uses the same "burst window + contact-quality gate + cross-cycle
      smoothing" idea as the Hydrocheck sketch, but rewritten to be
      NON-BLOCKING (millis()-based cycle instead of a 5s while-loop),
      so it doesn't stall the ECG timer or the WiFi/UDP loop.
    - HRV: rolling RR-interval buffer -> SDNN + RMSSD (bug from the
      Hydrocheck stdev calc fixed: no double division by N).
    - SpO2: Maxim block algorithm (spo2_algorithm.h), run every 100
      Red/IR samples (~1s at 100Hz).

  Networking:
    - ESP32 joins your WiFi (same network as your Raspberry Pi 5 / PC)
    - Sends UDP JSON packets to a central server, tagged with DEVICE_ID
      so you can run many of these at once and tell them apart.

  Libraries needed (Arduino Library Manager):
    - "SparkFun MAX3010x Pulse and Proximity Sensor Library"
      (provides MAX30105.h, heartRate.h, spo2_algorithm.h)
    - ESP32 board package (Seeed XIAO ESP32-C6) already gives you
      WiFi.h / WiFiUdp.h / Wire.h

  Board setup (Arduino IDE):
    Tools > Board > esp32 > XIAO_ESP32C6
*/

#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include "MAX30105.h"          // SparkFun lib, works for MAX30102
#include "heartRate.h"         // beat detection (for RR intervals / HRV)
#include "spo2_algorithm.h"    // Maxim SpO2 + HR algorithm

// ================== USER CONFIG ==================
#define DEVICE_ID     "patient_01"     // unique per device!

// Print raw ECG samples to Serial so you can view/graph them with the
// Arduino IDE's built-in Serial Plotter (Tools > Serial Plotter) while
// the device is also streaming data over WiFi/UDP.
// NOTE: at 250Hz this is a lot of Serial traffic. If you see WiFi/UDP
// timing get glitchy, either lower SERIAL_BAUD's usefulness by raising
// baud rate (already done below) or set this to 0.
#define SERIAL_PLOT_ECG   1

// ================== BLE CONFIG ==================
#define SERVICE_UUID           "4fafc201-1fb5-459e-8fcc-c5c9c331914b"
#define ECG_CHAR_UUID          "beb5483e-36e1-4688-b7f5-ea07361b26a8"
#define VITALS_CHAR_UUID       "e3223119-9445-4e96-a4a1-85358ce291d0"

BLEServer* pServer = NULL;
BLECharacteristic* pEcgCharacteristic = NULL;
BLECharacteristic* pVitalsCharacteristic = NULL;
bool deviceConnected = false;
bool oldDeviceConnected = false;

class MyServerCallbacks: public BLEServerCallbacks {
    void onConnect(BLEServer* pServer) {
      deviceConnected = true;
      Serial.println("BLE Client Connected");
    };
    void onDisconnect(BLEServer* pServer) {
      deviceConnected = false;
      Serial.println("BLE Client Disconnected");
    }
};

// ================== PIN CONFIG ==================
#define I2C_SDA      22
#define I2C_SCL      23
#define EXG_PIN      0          // BioAmp EXG Pill OUT (ADC-capable pin)

#define TCA_ADDR     0x70
#define MPU6050_CH   0            // unused here
#define MAX30102_CH  1

// ================== ECG SAMPLING ==================
#define ECG_SAMPLE_RATE_HZ   250
#define ECG_BATCH_SIZE       25   // samples per UDP packet (=10 packets/sec)

hw_timer_t *ecgTimer = NULL;
volatile bool ecgSampleReady = false;

int ecgBuffer[ECG_BATCH_SIZE];
int ecgIndex = 0;

void IRAM_ATTR onEcgTimer() {
  ecgSampleReady = true;
}

// ================== TCA9548A MUX ==================
void tcaSelect(uint8_t channel) {
  if (channel > 7) return;
  Wire.beginTransmission(TCA_ADDR);
  Wire.write(1 << channel);
  Wire.endTransmission();
}

// ================== MAX30102 ==================
MAX30105 maxSensor;

// ---- SpO2 (Maxim block algorithm) ----
#define PPG_BUFFER_SIZE 100      // ~1s @ 100Hz
uint32_t irBuffer[PPG_BUFFER_SIZE];
uint32_t redBuffer[PPG_BUFFER_SIZE];
int ppgFillIdx = 0;
unsigned long lastPPGCollect = 0;

int32_t spo2Value = 0;
int8_t  spo2Valid = 0;
int32_t maximHRValue = 0;   // HR as computed by the Maxim algorithm (cross-check)
int8_t  maximHRValid = 0;
int32_t lastGoodSpO2 = 0;   // Hold valid readings to prevent -999 UI glitches

// ---- Beat detection / RR intervals ----
unsigned long lastBeatTime = 0;

#define RR_HISTORY_LEN 30
float rrIntervals[RR_HISTORY_LEN];   // ms
int   rrCount = 0;
int   rrWriteIdx = 0;

float hrv_sdnn  = 0;
float hrv_rmssd = 0;

// ---- Non-blocking "burst cycle" contact-quality BPM gating ----
// Instead of a 5s blocking while-loop, we accumulate stats for
// CYCLE_DURATION_MS and evaluate/reset on each cycle boundary.
const unsigned long CYCLE_DURATION_MS = 5000;
unsigned long cycleStart = 0;

int  cycleTotalSamples   = 0;
int  cycleGoodContact    = 0;
float cycleBpmReadings[10];
int  cycleBpmCount       = 0;

const int BPM_HISTORY_SIZE = 4;
float bpmHistory[BPM_HISTORY_SIZE] = {0};
int bpmHistoryIndex = 0;
int bpmHistoryCount = 0;

float lastGoodBpm = 0;
int cyclesSinceGoodContact = 0;
const int MAX_HOLD_CYCLES = 2; // invalidate BPM if no good contact for this many cycles

float currentBPM = 0;          // what gets reported/sent

float smoothBpm(float newBpm) {
  if (newBpm <= 0) return -1; // no update this cycle
  bpmHistory[bpmHistoryIndex] = newBpm;
  bpmHistoryIndex = (bpmHistoryIndex + 1) % BPM_HISTORY_SIZE;
  if (bpmHistoryCount < BPM_HISTORY_SIZE) bpmHistoryCount++;

  float sum = 0;
  for (int i = 0; i < bpmHistoryCount; i++) sum += bpmHistory[i];
  return sum / bpmHistoryCount;
}

void addRRInterval(float rr_ms) {
  if (rr_ms < 300 || rr_ms > 2000) return; // reject physiologically implausible intervals
  rrIntervals[rrWriteIdx] = rr_ms;
  rrWriteIdx = (rrWriteIdx + 1) % RR_HISTORY_LEN;
  if (rrCount < RR_HISTORY_LEN) rrCount++;
}

void computeHRV() {
  if (rrCount < 3) { hrv_sdnn = 0; hrv_rmssd = 0; return; }

  // SDNN: standard deviation of RR intervals (fixed: single division by N)
  float mean = 0;
  for (int i = 0; i < rrCount; i++) mean += rrIntervals[i];
  mean /= rrCount;

  float sumSqDiff = 0;
  for (int i = 0; i < rrCount; i++) {
    float d = rrIntervals[i] - mean;
    sumSqDiff += d * d;
  }
  hrv_sdnn = sqrt(sumSqDiff / rrCount);

  // RMSSD: root mean square of successive differences
  float sumSqSuccDiff = 0;
  int pairs = 0;
  for (int i = 1; i < rrCount; i++) {
    float diff = rrIntervals[i] - rrIntervals[i - 1];
    sumSqSuccDiff += diff * diff;
    pairs++;
  }
  hrv_rmssd = (pairs > 0) ? sqrt(sumSqSuccDiff / pairs) : 0;
}

// Called once per cycle boundary (every CYCLE_DURATION_MS) to
// resolve this cycle's contact-quality-gated, smoothed BPM.
void evaluateCycle() {
  bool goodContact = (cycleTotalSamples > 0) &&
                      (cycleGoodContact >= (int)(cycleTotalSamples * 0.7));

  float rawCycleBpm = 0;
  if (goodContact && cycleBpmCount >= 2) {
    float sum = 0;
    for (int i = 0; i < cycleBpmCount; i++) sum += cycleBpmReadings[i];
    rawCycleBpm = sum / cycleBpmCount;
  }

  if (!goodContact) cyclesSinceGoodContact++;
  else cyclesSinceGoodContact = 0;

  float smoothed = smoothBpm(rawCycleBpm);
  if (smoothed > 0) {
    currentBPM = smoothed;
    lastGoodBpm = smoothed;
  } else if (cyclesSinceGoodContact < MAX_HOLD_CYCLES) {
    currentBPM = lastGoodBpm; // brief dropout, hold last known good value
  } else {
    // contact lost too long: reset everything, nothing left to trust
    currentBPM = 0;
    lastGoodBpm = 0;
    bpmHistoryCount = 0;
    bpmHistoryIndex = 0;
    rrCount = 0;
    rrWriteIdx = 0;
    hrv_sdnn = 0;
    hrv_rmssd = 0;
  }

  // reset per-cycle accumulators
  cycleTotalSamples = 0;
  cycleGoodContact  = 0;
  cycleBpmCount     = 0;
}

void updatePPGSampling() {
  tcaSelect(MAX30102_CH);
  maxSensor.check(); // Read from sensor FIFO
  
  while (maxSensor.available()) {
    long irValue = maxSensor.getFIFOIR();
    long redValue = maxSensor.getFIFORed();
    maxSensor.nextSample(); // Advance to next sample

    cycleTotalSamples++;
    if (irValue > 50000) { // confirmed skin contact
      cycleGoodContact++;
      if (checkForBeat(irValue)) {
        unsigned long now = millis();
        if (lastBeatTime != 0) {
          long delta = now - lastBeatTime;
          if (delta > 400 && delta < 1500) { // ~40-150 bpm plausible range
            if (cycleBpmCount < 10) {
              cycleBpmReadings[cycleBpmCount++] = 60000.0 / delta;
            }
            addRRInterval((float)delta);
            computeHRV();
          }
        }
        lastBeatTime = now;
      }
    }

    // Accumulate for SpO2 (downsample 4:1 from 100Hz to 25Hz for Maxim algorithm)
    static long irSum = 0;
    static long redSum = 0;
    static int downsampleCount = 0;

    irSum += irValue;
    redSum += redValue;
    downsampleCount++;

    if (downsampleCount >= 4) {
      irBuffer[ppgFillIdx] = irSum / 4;
      redBuffer[ppgFillIdx] = redSum / 4;
      ppgFillIdx++;
      irSum = 0;
      redSum = 0;
      downsampleCount = 0;

      if (ppgFillIdx >= PPG_BUFFER_SIZE) {
        maxim_heart_rate_and_oxygen_saturation(
          irBuffer, PPG_BUFFER_SIZE, redBuffer,
          &spo2Value, &spo2Valid, &maximHRValue, &maximHRValid);
          
        if (spo2Valid && spo2Value > 0 && spo2Value <= 100) {
          lastGoodSpO2 = spo2Value;
        }

        // Shift the last 75 samples to the start of the buffer
        for (byte i = 25; i < 100; i++) {
          redBuffer[i - 25] = redBuffer[i];
          irBuffer[i - 25] = irBuffer[i];
        }
        // Reset index to 75 so we collect 25 new samples (~1s) before calculating again
        ppgFillIdx = 75;
      }
    }
  }

  // cycle boundary check
  if (millis() - cycleStart >= CYCLE_DURATION_MS) {
    cycleStart = millis();
    evaluateCycle();
  }
}

// ================== BLE ==================
void setupBLE() {
  BLEDevice::init("AyuScan_Node");
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

void sendPPGPacket() {
  if (!deviceConnected) return;
  char msg[220];
  snprintf(msg, sizeof(msg),
    "{\"device\":\"%s\",\"type\":\"ppg\",\"bpm\":%d,\"spo2\":%d,"
    "\"hrv_sdnn\":%.1f,\"hrv_rmssd\":%.1f}",
    DEVICE_ID,
    (int)currentBPM,
    (int)lastGoodSpO2,
    hrv_sdnn, hrv_rmssd);

  pVitalsCharacteristic->setValue((uint8_t*)msg, strlen(msg));
  pVitalsCharacteristic->notify();
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


// ================== SETUP ==================
void setup() {
  // Higher baud rate matters here since we're printing every ECG
  // sample (250/sec) as well as WiFi/UDP status. 115200 can lag.
  Serial.begin(921600);
  delay(300);

  pinMode(EXG_PIN, INPUT);

  Wire.begin(I2C_SDA, I2C_SCL);
  Wire.setClock(400000);

  setupBLE();

  // --- init MAX30102 through the mux ---
  tcaSelect(MAX30102_CH);
  if (!maxSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 not found. Check wiring / mux channel.");
    while (1) delay(1000);
  }
  maxSensor.setup();
  maxSensor.setPulseAmplitudeRed(0x1F);   // strong LED drive for wrist tissue
  maxSensor.setPulseAmplitudeIR(0x1F);
  maxSensor.setPulseAmplitudeGreen(0);

  cycleStart = millis();

  // --- ECG sample timer (250 Hz) ---
  ecgTimer = timerBegin(1000000); // 1 MHz timer
  timerAttachInterrupt(ecgTimer, &onEcgTimer);
  timerAlarm(ecgTimer, 1000000 / ECG_SAMPLE_RATE_HZ, true, 0);

  Serial.println("Setup complete.");
}

// ================== LOOP ==================
void loop() {
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

  // ---------- ECG: fast, timer-driven ----------
  if (ecgSampleReady) {
    ecgSampleReady = false;
    int val = analogRead(EXG_PIN);
    ecgBuffer[ecgIndex++] = val;

#if SERIAL_PLOT_ECG
    // Single bare number per line = Arduino IDE Serial Plotter draws
    // this as a live scrolling line graph automatically.
    Serial.println(val);
#endif

    if (ecgIndex >= ECG_BATCH_SIZE) {
      ecgIndex = 0;
      sendECGPacket();
    }
  }

  // ---------- PPG: non-blocking contact-gated BPM + SpO2 + HRV ----------
  updatePPGSampling();

  // ---------- Send PPG/HRV summary packet every 1s ----------
  static unsigned long lastPPGSend = 0;
  if (millis() - lastPPGSend >= 1000) {
    lastPPGSend = millis();
    sendPPGPacket();

    // "label:value,label:value" format is what the Arduino IDE Serial
    // Plotter uses to draw multiple named traces at once.
    Serial.printf("BPM:%d,SpO2:%d,SDNN:%.1f,RMSSD:%.1f\n",
                  (int)currentBPM, (int)spo2Value, hrv_sdnn, hrv_rmssd);
  }
}
