import { useState, useEffect, useRef } from 'react';

const WEBSOCKET_URL = 'ws://localhost:8080';

export function useLiveDevices() {
  const [devices, setDevices] = useState([]);
  const [historyData, setHistoryData] = useState({});
  const wsRef = useRef(null);

  // Device structure lookup by Physical Device ID
  const deviceLookup = useRef({});

  const assignDevice = (patientName, patientId, bedNo, physicalId) => {
    // Check if we already have this device assigned
    if (deviceLookup.current[physicalId]) {
      console.warn(`Device ${physicalId} is already assigned.`);
      return;
    }

    const newDevice = {
      id: physicalId,
      patientName,
      patientId,
      bedNo,
      connectedAt: new Date().toISOString(),
      vitals: {
        hr: '--',
        spo2: '--',
        sys: '--',
        dia: '--',
        temp: '--'
      }
    };
    
    deviceLookup.current[physicalId] = newDevice;
    setDevices(prev => [...prev, newDevice]);
    setHistoryData(prev => ({
      ...prev,
      [physicalId]: {
        ecg: [],
        spo2: []
      }
    }));
  };

  useEffect(() => {
    // Establish WebSocket connection
    const connectWs = () => {
      const ws = new WebSocket(WEBSOCKET_URL);
      
      ws.onopen = () => {
        console.log("Connected to WebSocket Server");
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          const deviceId = data.device;
          
          // Ignore data if device is not assigned yet
          if (!deviceLookup.current[deviceId]) return;

          if (data.type === 'ppg') {
            // Update Vitals
            setDevices(prevDevices => 
              prevDevices.map(d => {
                if (d.id === deviceId) {
                  return {
                    ...d,
                    vitals: {
                      ...d.vitals,
                      hr: data.bpm,
                      spo2: data.spo2,
                      // Simulated values for BP and Temp since ESP32 doesn't send them yet
                      sys: d.vitals.sys === '--' ? 120 : d.vitals.sys,
                      dia: d.vitals.dia === '--' ? 80 : d.vitals.dia,
                      temp: d.vitals.temp === '--' ? 36.5 : d.vitals.temp
                    }
                  };
                }
                return d;
              })
            );

            // Update SPO2 trend
            setHistoryData(prevHistory => {
              const currentDeviceHistory = prevHistory[deviceId] || { ecg: [], spo2: [] };
              const newSpo2 = [...currentDeviceHistory.spo2, { x: Date.now(), y: data.spo2 }];
              if (newSpo2.length > 50) newSpo2.shift(); // Keep last 50 points
              
              return {
                ...prevHistory,
                [deviceId]: {
                  ...currentDeviceHistory,
                  spo2: newSpo2
                }
              };
            });
          } 
          else if (data.type === 'diagnosis') {
            setDevices(prevDevices => 
              prevDevices.map(d => {
                if (d.id === deviceId) {
                  return { ...d, diagnosis: data.condition };
                }
                return d;
              })
            );
          }
          else if (data.type === 'temp') {
            setDevices(prevDevices => 
              prevDevices.map(d => {
                if (d.id === deviceId) {
                  return {
                    ...d,
                    vitals: {
                      ...d.vitals,
                      temp: Number(data.val).toFixed(1)
                    }
                  };
                }
                return d;
              })
            );
          }
          else if (data.type === 'ecg') {
            // Update ECG waveform
            setHistoryData(prevHistory => {
              const currentDeviceHistory = prevHistory[deviceId] || { ecg: [], spo2: [] };
              
              // data.data contains an array of points (raw numbers)
              const newPoints = data.data;
              const newEcg = [...currentDeviceHistory.ecg, ...newPoints];
              
              // Keep a sliding window of 750 points (3 seconds at 250Hz sampling rate)
              if (newEcg.length > 750) newEcg.splice(0, newEcg.length - 750);
              
              return {
                ...prevHistory,
                [deviceId]: {
                  ...currentDeviceHistory,
                  ecg: newEcg
                }
              };
            });
          }
        } catch (err) {
          console.error("Error parsing WS data:", err);
        }
      };

      ws.onclose = () => {
        console.log("WebSocket Disconnected. Reconnecting in 3s...");
        setTimeout(connectWs, 3000);
      };

      ws.onerror = (err) => {
        console.error("WebSocket error:", err);
        ws.close();
      };

      wsRef.current = ws;
    };

    connectWs();

    return () => {
      if (wsRef.current) wsRef.current.close();
    };
  }, []);

  return { devices, historyData, assignDevice };
}
