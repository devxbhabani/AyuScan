import React, { useState } from 'react';

const DeviceAssignmentModal = ({ isOpen, onClose, onAssign }) => {
  const [patientName, setPatientName] = useState('');
  const [patientId, setPatientId] = useState('');
  const [bedNo, setBedNo] = useState('');
  const [physicalId, setPhysicalId] = useState('');

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    if (patientName && patientId && bedNo && physicalId) {
      onAssign(patientName, patientId, bedNo, physicalId);
      setPatientName('');
      setPatientId('');
      setBedNo('');
      setPhysicalId('');
      onClose();
    }
  };

  return (
    <div className="modal-overlay">
      <div className="modal-content">
        <h2>Assign New Device</h2>
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label>Patient Name</label>
            <input 
              type="text" 
              value={patientName} 
              onChange={(e) => setPatientName(e.target.value)}
              placeholder="e.g. John Doe"
              required
            />
          </div>
          <div className="form-group">
            <label>Patient ID</label>
            <input 
              type="text" 
              value={patientId} 
              onChange={(e) => setPatientId(e.target.value)}
              placeholder="e.g. PID-12345"
              required
            />
          </div>
          <div className="form-group">
            <label>Bed Number</label>
            <input 
              type="text" 
              value={bedNo} 
              onChange={(e) => setBedNo(e.target.value)}
              placeholder="e.g. 104-A"
              required
            />
          </div>
          <div className="form-group">
            <label>Physical Device ID</label>
            <input 
              type="text" 
              value={physicalId} 
              onChange={(e) => setPhysicalId(e.target.value)}
              placeholder="e.g. patient_01"
              required
            />
          </div>
          <div className="modal-actions">
            <button type="button" className="btn-modal cancel" onClick={onClose}>Cancel</button>
            <button type="submit" className="btn-modal submit">Assign Device</button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default DeviceAssignmentModal;
