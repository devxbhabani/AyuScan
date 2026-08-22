import os
import pandas as pd
import numpy as np
from tqdm import tqdm
import sys

# Add bp_model to path
sys.path.append(os.path.join(os.path.dirname(__file__), 'bp_model'))
from preprocess import extract_features

DATASET_DIR = "dataset"
OUTPUT_CSV = "extracted_features.csv"
WINDOW_SIZE_SEC = 5
STEP_SIZE_SEC = 1
FS = 100 # 100Hz
MAX_SAMPLES = 100000

def main():
    if not os.path.exists(DATASET_DIR):
        print(f"Directory {DATASET_DIR} not found.")
        return
        
    csv_files = [f for f in os.listdir(DATASET_DIR) if f.endswith(".csv")]
    if not csv_files:
        print("No CSV files found.")
        return
        
    print(f"Found {len(csv_files)} cases. Starting feature extraction...")
    
    features_list = []
    
    window_samples = WINDOW_SIZE_SEC * FS
    step_samples = STEP_SIZE_SEC * FS
    
    for case_file in tqdm(csv_files):
        if len(features_list) >= MAX_SAMPLES:
            break
            
        df = pd.read_csv(os.path.join(DATASET_DIR, case_file))
        
        # Verify columns exist
        if not {'ECG_II', 'PLETH', 'ART'}.issubset(df.columns):
            continue
            
        # Drop rows where any of these are NaN
        df = df.dropna(subset=['ECG_II', 'PLETH', 'ART']).reset_index(drop=True)
        
        ecg_data = df['ECG_II'].values
        ppg_data = df['PLETH'].values
        art_data = df['ART'].values
        
        num_windows = (len(ecg_data) - window_samples) // step_samples
        
        for i in range(num_windows):
            start = i * step_samples
            end = start + window_samples
            
            ecg_win = ecg_data[start:end]
            ppg_win = ppg_data[start:end]
            art_win = art_data[start:end]
            
            # Simple check for flatlines
            if np.std(ecg_win) < 0.01 or np.std(ppg_win) < 0.01:
                continue
                
            features = extract_features(ecg_win, ppg_win, art_win, fs=FS)
            
            if features is not None:
                features['case_id'] = case_file.replace('.csv', '')
                features_list.append(features)
                
            if len(features_list) >= MAX_SAMPLES:
                break
                
    print(f"\nExtracted {len(features_list)} valid feature vectors.")
    out_df = pd.DataFrame(features_list)
    out_df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved to {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
