import React from 'react';
import PatientCard from './PatientCard';

const PatientDetailsModal = ({ device, history, onClose }) => {
  if (!device) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content expanded-patient-modal" onClick={e => e.stopPropagation()}>
        <button className="close-btn" onClick={onClose}>&times;</button>
        <PatientCard device={device} history={history} isExpanded={true} />
      </div>
    </div>
  );
};

export default PatientDetailsModal;
