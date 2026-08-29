import React, { useState, useEffect } from 'react';
import { Activity, Menu } from 'lucide-react';
import PatientCard from './components/PatientCard';
import DeviceAssignmentModal from './components/DeviceAssignmentModal';
import { useLiveDevices } from './hooks/useLiveDevices';
import PatientDetailsModal from './components/PatientDetailsModal';
import Sidebar from './components/Sidebar';

function App() {
  const { devices, historyData, assignDevice, removeDevice } = useLiveDevices();
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  const [currentPage, setCurrentPage] = useState(0);
  const [selectedDeviceId, setSelectedDeviceId] = useState(null);

  const selectedDevice = devices.find(d => d.id === selectedDeviceId);

  const numDevices = devices.length;
  const maxDevicesPerPage = 4;
  const numPages = Math.ceil(numDevices / maxDevicesPerPage);

  // Pagination / Carousel Logic for >= 5 devices
  useEffect(() => {
    let interval;
    if (numDevices >= 5) {
      interval = setInterval(() => {
        setCurrentPage((prev) => (prev + 1) % numPages);
      }, 10000);
    } else {
      setCurrentPage(0); // Reset to first page if devices drop below 5 (not possible in this sim but good practice)
    }
    return () => clearInterval(interval);
  }, [numDevices, numPages]);

  // Determine grid layout class
  let layoutClass = 'layout-1';
  if (numDevices === 2) layoutClass = 'layout-2';
  if (numDevices >= 3) layoutClass = 'layout-4';

  // Get current page devices
  const startIndex = currentPage * maxDevicesPerPage;
  const visibleDevices = devices.slice(startIndex, startIndex + maxDevicesPerPage);

  const handleDeviceSelectFromSidebar = (device) => {
    setSelectedDeviceId(device.id);
    setIsSidebarOpen(false);
  };

  return (
    <div className="app-container">
      <header className="top-bar">
        <div className="header-left">
          <button className="btn-icon hamburger-btn" onClick={() => setIsSidebarOpen(true)}>
            <Menu size={24} />
          </button>
          <h1><Activity className="logo-icon" size={28} /> AyuScan Monitor</h1>
        </div>
        <button className="btn-primary" onClick={() => setIsModalOpen(true)}>
          + Assign Device
        </button>
      </header>

      {numDevices === 0 ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-secondary)' }}>
          <p>No devices connected. Click "Assign Device" to start.</p>
        </div>
      ) : (
        <main className={`dashboard-grid ${layoutClass}`}>
          {visibleDevices.map(device => (
            <PatientCard 
              key={device.id} 
              device={device} 
              history={historyData[device.id]} 
              onClick={() => setSelectedDeviceId(device.id)}
            />
          ))}
        </main>
      )}

      {/* Carousel Indicators for >= 5 devices */}
      {numDevices >= 5 && (
        <div className="carousel-indicators">
          {Array.from({ length: numPages }).map((_, idx) => (
            <div 
              key={idx} 
              className={`indicator ${idx === currentPage ? 'active' : ''}`}
            />
          ))}
        </div>
      )}

      <DeviceAssignmentModal 
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onAssign={assignDevice}
      />

      {selectedDevice && (
        <PatientDetailsModal 
          device={selectedDevice}
          history={historyData[selectedDevice.id]}
          onClose={() => setSelectedDeviceId(null)}
        />
      )}

      <Sidebar 
        isOpen={isSidebarOpen} 
        onClose={() => setIsSidebarOpen(false)} 
        devices={devices} 
        onSelectDevice={handleDeviceSelectFromSidebar} 
      />
    </div>
  );
}

export default App;
