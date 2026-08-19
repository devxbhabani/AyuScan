import React, { useState, useEffect } from 'react';
import { Heart, Activity, Thermometer, Droplet } from 'lucide-react';

// A simple simulated Waveform chart using SVG
const WaveformChart = ({ data, color, yMin, yMax }) => {
  if (!data || data.length === 0) return null;

  // Normalize data points to SVG coordinates (0-100% width/height)
  const width = 300; // SVG viewBox width
  const height = 100; // SVG viewBox height
  
  const minX = data[0].x;
  const maxX = data[data.length - 1].x;
  
  const points = data.map(d => {
    const normX = ((d.x - minX) / (maxX - minX)) * width;
    // Invert Y because SVG coordinates go down
    const normY = height - (((d.y - yMin) / (yMax - yMin)) * height);
    return `${normX},${normY}`;
  }).join(' ');

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="waveform-svg" preserveAspectRatio="none">
      <polyline 
        points={points} 
        fill="none" 
        stroke={color} 
        strokeWidth="2"
        strokeLinejoin="round"
      />
    </svg>
  );
};

const PatientCard = ({ device, history, isExpanded, onClick }) => {
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  const timeStr = now.toLocaleTimeString();
  const dateStr = now.toLocaleDateString();

  return (
    <div className={`patient-card ${isExpanded ? 'expanded' : ''} ${onClick ? 'clickable' : ''}`} onClick={onClick}>
      <div className="card-header">
        <div className="patient-info-inline">
          <span className="patient-name">{device.patientName}</span>
          <span className="patient-id">ID: {device.patientId}</span>
          <span className="bed-badge">Bed {device.bedNo}</span>
        </div>
        <div className="meta-info">
          <span>{dateStr}</span>
          <span>{timeStr}</span>
        </div>
      </div>

      <div className="card-body">
        <div className="metrics-grid">
          <div className="metric-box hr">
            <div className="metric-header">
              <span>Heart Rate</span>
              <Heart className="icon" size={14} />
            </div>
            <div className="metric-value">
              {device.vitals.hr} <span className="metric-unit">bpm</span>
            </div>
          </div>

          <div className="metric-box bp">
            <div className="metric-header">
              <span>BP</span>
              <Activity className="icon" size={14} />
            </div>
            <div className="metric-value">
              {device.vitals.sys}/{device.vitals.dia}
            </div>
          </div>
          
          <div className="metric-box spo2">
            <div className="metric-header">
              <span>SpO2</span>
              <Droplet className="icon" size={14} />
            </div>
            <div className="metric-value">
              {device.vitals.spo2} <span className="metric-unit">%</span>
            </div>
          </div>

          <div className="metric-box temp">
            <div className="metric-header">
              <span>Temp</span>
              <Thermometer className="icon" size={14} />
            </div>
            <div className="metric-value">
              {device.vitals.temp} <span className="metric-unit">°C</span>
            </div>
          </div>
        </div>

        <div className="waveforms-container">
          <div className="waveform-box">
            <div className="waveform-title">ECG</div>
            <div className="waveform-canvas-container">
               <WaveformChart data={history?.ecg} color="var(--accent-success)" yMin={-100} yMax={100} />
            </div>
          </div>
          <div className="waveform-box">
            <div className="waveform-title">SpO2 Trend</div>
            <div className="waveform-canvas-container">
               <WaveformChart data={history?.spo2} color="var(--accent-spo2)" yMin={80} yMax={100} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PatientCard;
