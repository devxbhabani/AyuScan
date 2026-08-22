import React, { useState, useEffect } from 'react';
import { Heart, Activity, Thermometer, Droplet } from 'lucide-react';

// A simple simulated Waveform chart using SVG
const WaveformChart = ({ data, color, yMin, yMax, showGrid }) => {
  if (!data || data.length === 0) return null;

  // Normalize data points to SVG coordinates (0-100% width/height)
  const width = 300; // SVG viewBox width
  const height = 100; // SVG viewBox height
  
  const minX = 0;
  const maxX = data.length > 1 ? data.length - 1 : 1;
  
  let currentYMin = yMin;
  let currentYMax = yMax;

  if (currentYMin === undefined || currentYMax === undefined) {
    const yValues = data.map(d => typeof d === 'object' ? d.y : d);
    currentYMin = currentYMin !== undefined ? currentYMin : Math.min(...yValues);
    currentYMax = currentYMax !== undefined ? currentYMax : Math.max(...yValues);
    const padding = (currentYMax - currentYMin) * 0.1 || 10;
    currentYMin -= padding;
    currentYMax += padding;
  }
  
  const points = data.map((d, index) => {
    const yVal = typeof d === 'object' ? d.y : d;
    const normX = ((index - minX) / (maxX - minX)) * width;
    // Invert Y because SVG coordinates go down
    const normY = height - (((yVal - currentYMin) / (currentYMax - currentYMin)) * height);
    return `${normX},${normY}`;
  }).join(' ');

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="waveform-svg" preserveAspectRatio="none" style={{ backgroundColor: 'transparent', borderRadius: '4px', overflow: 'hidden' }}>
      {showGrid && (
        <defs>
          <pattern id="minorGrid" width="6" height="6" patternUnits="userSpaceOnUse">
            <path d="M 6 0 L 0 0 0 6" fill="none" stroke="rgba(255, 255, 255, 0.05)" strokeWidth="0.5" />
          </pattern>
          <pattern id="majorGrid" width="30" height="30" patternUnits="userSpaceOnUse">
            <rect width="30" height="30" fill="url(#minorGrid)" />
            <path d="M 30 0 L 0 0 0 30" fill="none" stroke="rgba(255, 255, 255, 0.15)" strokeWidth="1" />
          </pattern>
        </defs>
      )}
      {showGrid && <rect width="100%" height="100%" fill="url(#majorGrid)" />}
      
      <polyline 
        points={points} 
        fill="none" 
        stroke={color} 
        strokeWidth="1.5"
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

  const hasWarning = device.diagnosis && device.diagnosis !== 'Normal' && device.diagnosis !== 'Unknown';
  const hasSpo2Warning = device.spo2Diagnosis && device.spo2Diagnosis !== 'Stable' && device.spo2Diagnosis !== 'Unknown';
  const hasBpWarning = device.bpStatus && (device.bpStatus === 'Crisis' || device.bpStatus === 'Hypertension Stage 2');

  return (
    <div className={`patient-card ${isExpanded ? 'expanded' : ''} ${onClick ? 'clickable' : ''} ${(hasWarning || hasSpo2Warning || hasBpWarning) ? 'has-warning' : ''}`} onClick={onClick}>
      {(hasWarning || hasSpo2Warning || hasBpWarning) && (
        <div className="warning-overlay">
          {hasWarning && (
            <div className="warning-badge">
              <Activity size={24} className="warning-icon pulse-animation" />
              <span>WARNING: ECG {device.diagnosis.toUpperCase()} DETECTED</span>
            </div>
          )}
          {hasSpo2Warning && (
            <div className="warning-badge" style={{ marginTop: hasWarning ? '10px' : '0' }}>
              <Droplet size={24} className="warning-icon pulse-animation" />
              <span>WARNING: SpO2 {device.spo2Diagnosis.toUpperCase()}</span>
            </div>
          )}
          {hasBpWarning && (
            <div className="warning-badge" style={{ marginTop: (hasWarning || hasSpo2Warning) ? '10px' : '0' }}>
              <Activity size={24} className="warning-icon pulse-animation" />
              <span>WARNING: BP {device.bpStatus.toUpperCase()}</span>
            </div>
          )}
        </div>
      )}
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
            {device.bpStatus && (
              <div className="bp-status" style={{ fontSize: '0.75rem', marginTop: '4px', color: (device.bpStatus === 'Normal' ? '#4CAF50' : '#FF9800') }}>
                {device.bpStatus}
              </div>
            )}
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
               <WaveformChart data={history?.ecg} color="#d32f2f" showGrid={true} />
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
