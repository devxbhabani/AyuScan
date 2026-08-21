import os
import pandas as pd
import numpy as np

DATA_DIR = "spo2-dataset/bidmc_csv"
WINDOW_SIZE = 60
FUTURE_WINDOW = 30

def create_dataset():
    X = []
    y = []

    files = [f for f in os.listdir(DATA_DIR) if f.endswith("Numerics.csv")]
    
    for file in files:
        df = pd.read_csv(os.path.join(DATA_DIR, file))
        if " SpO2" not in df.columns:
            continue
            
        spo2_values = df[" SpO2"].values
        
        # Slide through the time series
        for i in range(len(spo2_values) - WINDOW_SIZE - FUTURE_WINDOW):
            current_window = spo2_values[i : i + WINDOW_SIZE]
            future_window = spo2_values[i + WINDOW_SIZE : i + WINDOW_SIZE + FUTURE_WINDOW]
            
            # Handle NaN or 0 values which might mean sensor error
            if np.any(np.isnan(current_window)) or np.any(current_window == 0):
                continue
            if np.any(np.isnan(future_window)) or np.any(future_window == 0):
                continue
                
            # Current state
            current_spo2 = current_window[-1]
            min_future = np.min(future_window)
            max_future = np.max(future_window)
            mean_current = np.mean(current_window)
            
            # Label logic
            if current_spo2 < 90 or min_future < 90:
                label = 3 # Critical
            elif (current_spo2 - min_future) >= 3:
                label = 2 # Rapid Decline
            elif (current_spo2 - min_future) >= 1.5:
                label = 1 # Mild Decline
            else:
                label = 0 # Stable
                
            X.append(current_window)
            y.append(label)

    X = np.array(X)
    y = np.array(y)
    
    # Balance classes minimally by undersampling the majority class (Stable)
    stable_indices = np.where(y == 0)[0]
    other_indices = np.where(y != 0)[0]
    
    if len(stable_indices) > len(other_indices) * 3:
        np.random.seed(42)
        sampled_stable = np.random.choice(stable_indices, size=len(other_indices)*3, replace=False)
        keep_indices = np.concatenate([sampled_stable, other_indices])
        X = X[keep_indices]
        y = y[keep_indices]
    
    # Reshape for 1D CNN / GRU: [samples, timesteps, features]
    X = np.expand_dims(X, axis=-1)
    
    print(f"Generated {len(X)} samples.")
    print("Class distribution:")
    unique, counts = np.unique(y, return_counts=True)
    for c, count in zip(unique, counts):
        print(f"Class {c}: {count}")
        
    np.savez("spo2_dataset.npz", X=X, y=y)
    print("Saved to spo2_dataset.npz")

if __name__ == "__main__":
    create_dataset()
