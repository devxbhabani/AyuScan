# AyuScan

A real-time wearable health monitoring system using ESP32-C6, BioAmp EXG Pill, and MAX30102.

## Hardware
- ESP32-C6 (BLE data acquisition)
- BioAmp EXG Pill (ECG)
- MAX30102 (PPG / SpO2)
- MLX90614 (Body Temperature)
- TCA9548A I2C Multiplexer

## Features
- Live ECG waveform streaming
- Heart Rate, SpO2, Temperature monitoring
- AI-based ECG condition detection (Normal, Bradycardia, Tachycardia, Arrhythmia)
- AI-based SpO2 trend analysis (Stable, Mild Decline, Rapid Decline, Critical)
- Blood Pressure estimation using ECG + PPG (XGBoost model)
- Real-time React dashboard via WebSocket
