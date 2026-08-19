import { useState, useEffect } from 'react';

// Simulate realistic vital fluctuations
const generateNoise = (base, variance) => {
  return base + (Math.random() * variance * 2 - variance);
};

export function useSimulatedDevices() {
  const [devices, setDevices] = useState([]);
  const [historyData, setHistoryData] = useState({}); // { deviceId: { ecg: [], spo2: [] } }

  // Add a new device
  const assignDevice = (patientName, patientId, bedNo) => {
    const newDevice = {
      id: `dev_${Date.now()}`,
      patientName,
      patientId,
      bedNo,
      connectedAt: new Date().toISOString(),
      vitals: {
        hr: 75,
        spo2: 98,
        sys: 120,
        dia: 80,
        temp: 37.0
      }
    };
    
    setDevices(prev => [...prev, newDevice]);
    setHistoryData(prev => ({
      ...prev,
      [newDevice.id]: {
        ecg: Array(50).fill(0).map((_, i) => ({ x: i, y: 0 })),
        spo2: Array(50).fill(0).map((_, i) => ({ x: i, y: 98 }))
      }
    }));
  };

  // Simulate live data updates
  useEffect(() => {
    if (devices.length === 0) return;

    let timeStep = 0;
    
    const interval = setInterval(() => {
      timeStep += 1;
      
      setDevices(prevDevices => 
        prevDevices.map(device => {
          // Add some randomness to vitals
          return {
            ...device,
            vitals: {
              hr: Math.round(generateNoise(device.vitals.hr, 2)),
              spo2: Math.min(100, Math.max(90, Math.round(generateNoise(device.vitals.spo2, 0.5)))),
              sys: Math.round(generateNoise(device.vitals.sys, 1)),
              dia: Math.round(generateNoise(device.vitals.dia, 1)),
              temp: Number(generateNoise(device.vitals.temp, 0.1).toFixed(1))
            }
          };
        })
      );

      // Simulate waveform data
      setHistoryData(prevHistory => {
        const newHistory = { ...prevHistory };
        Object.keys(newHistory).forEach(id => {
          // ECG Simulation (periodic spike)
          const ecgPoint = timeStep % 20 === 0 ? 80 : (timeStep % 20 === 1 ? -40 : generateNoise(0, 5));
          const newEcg = [...newHistory[id].ecg.slice(1), { x: timeStep, y: ecgPoint }];
          
          // SPO2 Trend Simulation (slow moving)
          const lastSpo2 = newHistory[id].spo2[newHistory[id].spo2.length - 1].y;
          const spo2Point = Math.min(100, Math.max(90, generateNoise(lastSpo2, 0.5)));
          const newSpo2 = [...newHistory[id].spo2.slice(1), { x: timeStep, y: spo2Point }];

          newHistory[id] = { ecg: newEcg, spo2: newSpo2 };
        });
        return newHistory;
      });

    }, 1000); // Update every second

    return () => clearInterval(interval);
  }, [devices.length]);

  return { devices, historyData, assignDevice };
}
