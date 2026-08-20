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
#include <WiFi.h>
#include <WiFiUdp.h>
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

const char* WIFI_SSID = "Bhabani-Laptop";
const char* WIFI_PASS = "bsj898909";

IPAddress   SERVER_IP(192, 168, 137, 1);  // <-- your Raspberry Pi / PC IP
const uint16_t SERVER_PORT = 5005;

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

// Called every main-loop pass (fast, non-blocking) to feed the
// current cycle's contact/beat stats.
void updatePPGSampling() {
  tcaSelect(MAX30102_CH);
  long irValue = maxSensor.getIR();
  long redValue = maxSensor.getRed();

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

  // feed the SpO2 block buffer at ~100Hz
  if (millis() - lastPPGCollect >= 10) {
    lastPPGCollect = millis();
    irBuffer[ppgFillIdx]  = irValue;
    redBuffer[ppgFillIdx] = redValue;
    ppgFillIdx++;

    if (ppgFillIdx >= PPG_BUFFER_SIZE) {
      ppgFillIdx = 0;
      maxim_heart_rate_and_oxygen_saturation(
        irBuffer, PPG_BUFFER_SIZE, redBuffer,
        &spo2Value, &spo2Valid, &maximHRValue, &maximHRValid);
    }
  }

  // cycle boundary check
  if (millis() - cycleStart >= CYCLE_DURATION_MS) {
    cycleStart = millis();
    evaluateCycle();
  }
}

// ================== WIFI / UDP ==================
WiFiUDP udp;

void connectWiFi() {
  Serial.print("Connecting to WiFi");
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) {
    delay(400);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("Connected. IP: ");
  Serial.println(WiFi.localIP());
}

void sendPPGPacket() {
  char msg[220];
  snprintf(msg, sizeof(msg),
    "{\"device\":\"%s\",\"type\":\"ppg\",\"bpm\":%d,\"spo2\":%d,"
    "\"hrv_sdnn\":%.1f,\"hrv_rmssd\":%.1f}",
    DEVICE_ID,
    (int)currentBPM,
    (int)spo2Value,
    hrv_sdnn, hrv_rmssd);

  udp.beginPacket(SERVER_IP, SERVER_PORT);
  udp.print(msg);
  int result = udp.endPacket();
  Serial.printf("[UDP] PPG packet send result: %d (1=success, 0=fail)\n", result);
}

void sendECGPacket() {
  char header[80];
  snprintf(header, sizeof(header),
    "{\"device\":\"%s\",\"type\":\"ecg\",\"fs\":%d,\"data\":[",
    DEVICE_ID, ECG_SAMPLE_RATE_HZ);

  udp.beginPacket(SERVER_IP, SERVER_PORT);
  udp.print(header);
  for (int i = 0; i < ECG_BATCH_SIZE; i++) {
    udp.print(ecgBuffer[i]);
    if (i < ECG_BATCH_SIZE - 1) udp.print(",");
  }
  udp.print("]}");
  udp.endPacket();
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

  connectWiFi();
  WiFi.setSleep(false);   // disable WiFi modem sleep — fixes high latency /
                          // dropped packets common on ESP32 when idle between sends

  // --- init MAX30102 through the mux ---
  tcaSelect(MAX30102_CH);
  if (!maxSensor.begin(Wire, I2C_SPEED_FAST)) {
    Serial.println("MAX30102 not found. Check wiring / mux channel.");
    while (1) delay(1000);
  }
  maxSensor.setup();
  maxSensor.setPulseAmplitudeRed(0x3F);   // strong LED drive for wrist tissue
  maxSensor.setPulseAmplitudeIR(0x3F);
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
