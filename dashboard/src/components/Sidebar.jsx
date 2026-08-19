import React from 'react';
import { X, User } from 'lucide-react';

const Sidebar = ({ isOpen, onClose, devices, onSelectDevice }) => {
  return (
    <>
      {isOpen && (
        <div className="sidebar-overlay" onClick={onClose}></div>
      )}
      <div className={`sidebar-panel ${isOpen ? 'open' : ''}`}>
        <div className="sidebar-header">
          <h2>Connected Devices</h2>
          <button className="sidebar-close-btn" onClick={onClose}>
            <X size={24} />
          </button>
        </div>
        <div className="sidebar-content">
          {devices.length === 0 ? (
            <div className="no-devices-msg">No devices connected</div>
          ) : (
            <ul className="device-list">
              {devices.map((device) => (
                <li 
                  key={device.id} 
                  className="device-list-item" 
                  onClick={() => onSelectDevice(device)}
                >
                  <div className="device-avatar">
                    <User size={20} />
                  </div>
                  <div className="device-info">
                    <div className="device-name">{device.patientName}</div>
                    <div className="device-meta">
                      ID: {device.patientId} • Bed: {device.bedNo}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </>
  );
};

export default Sidebar;
