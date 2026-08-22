import os
import joblib
import numpy as np
import pandas as pd
from .preprocess import extract_features

# Load models globally
MODEL_DIR = os.path.dirname(__file__)
SBP_MODEL_PATH = os.path.join(MODEL_DIR, "sbp_xgboost.pkl")
DBP_MODEL_PATH = os.path.join(MODEL_DIR, "dbp_xgboost.pkl")

sbp_model = None
dbp_model = None

try:
    if os.path.exists(SBP_MODEL_PATH) and os.path.exists(DBP_MODEL_PATH):
        sbp_model = joblib.load(SBP_MODEL_PATH)
        dbp_model = joblib.load(DBP_MODEL_PATH)
        print("Blood Pressure XGBoost models loaded successfully.")
    else:
        print("BP models not found. Waiting for training...")
except Exception as e:
    print(f"Error loading BP models: {e}")

def get_bp_status(sbp, dbp):
    """
    Map SBP and DBP to AHA categories.
    """
    if sbp > 180 or dbp > 120:
        return "Crisis"
    if sbp >= 140 or dbp >= 90:
        return "Hypertension Stage 2"
    if (130 <= sbp <= 139) or (80 <= dbp <= 89):
        return "Hypertension Stage 1"
    if (120 <= sbp <= 129) and dbp < 80:
        return "Elevated"
    return "Normal"

def predict_bp(ecg_window, ppg_window, fs=100):
    """
    Predict SBP and DBP from a 5-second window of ECG and PPG.
    Returns:
    {
        "sbp": 120.5,
        "dbp": 79.2,
        "status": "Normal"
    }
    """
    if sbp_model is None or dbp_model is None:
        return None
        
    features = extract_features(np.array(ecg_window), np.array(ppg_window), fs=fs)
    
    if features is None:
        return None # No valid peaks found
        
    # Features match training: ['hr', 'ptt_mean', 'ptt_std', 'ppg_amp_mean', 'rr_std']
    feature_vector = np.array([[
        features['hr'],
        features['ptt_mean'],
        features['ptt_std'],
        features['ppg_amp_mean'],
        features['rr_std']
    ]])
    
    pred_sbp = float(sbp_model.predict(feature_vector)[0])
    pred_dbp = float(dbp_model.predict(feature_vector)[0])
    
    # Simple post-processing bounds
    pred_sbp = max(70.0, min(220.0, pred_sbp))
    pred_dbp = max(40.0, min(130.0, pred_dbp))
    
    status = get_bp_status(pred_sbp, pred_dbp)
    
    return {
        "sbp": round(pred_sbp, 1),
        "dbp": round(pred_dbp, 1),
        "status": status
    }
