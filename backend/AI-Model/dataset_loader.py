import os
import ast
import pandas as pd
import numpy as np
import wfdb
import torch
from torch.utils.data import Dataset, DataLoader

# Mapping from PTB-XL scp_codes to our 4 target classes
# 0: Normal, 1: Bradycardia, 2: Tachycardia, 3: Arrhythmia
CLASS_MAPPING = {
    'NORM': 0,
    'SBRAD': 1,
    'STACH': 2,
    'SVTAC': 2,
    'PSVT': 2,
    'AFIB': 3,
    'AFLT': 3,
    'SARRH': 3,
    'SVARR': 3,
    'BIGU': 3,
    'TRIGU': 3
}

def load_ptbxl_metadata(dataset_path):
    print("Loading PTB-XL metadata...")
    df = pd.read_csv(os.path.join(dataset_path, 'ptbxl_database.csv'), index_col='ecg_id')
    
    # scp_codes is a string representation of a dictionary, parse it
    df.scp_codes = df.scp_codes.apply(lambda x: ast.literal_eval(x))
    
    # Extract the target label for each record
    labels = []
    valid_indices = []
    
    for idx, row in df.iterrows():
        # Get all scp_codes for this patient
        codes = row['scp_codes'].keys()
        
        # Find which of our target classes it belongs to
        target_class = -1
        # Priority: Brady/Tachy/Arrhythmia over Normal
        for code in codes:
            if code in CLASS_MAPPING:
                # If we find a non-normal class, pick it.
                if CLASS_MAPPING[code] != 0:
                    target_class = CLASS_MAPPING[code]
                    break
                else:
                    target_class = 0 # NORM
                    
        if target_class != -1:
            labels.append(target_class)
            valid_indices.append(idx)
            
    # Filter dataframe to only include records that matched our classes
    df = df.loc[valid_indices]
    df['target'] = labels
    print(f"Found {len(df)} records matching the target classes.")
    return df

class PTBXLDataset(Dataset):
    def __init__(self, df, dataset_path, lead_index=2):
        """
        lead_index=2 means Lead III.
        Lead indices in PTB-XL are typically: 0:I, 1:II, 2:III, 3:AVR, 4:AVL, 5:AVF, 6:V1...
        """
        self.df = df
        self.dataset_path = dataset_path
        self.lead_index = lead_index

    def __len__(self):
        return len(self.df)

    def __getitem__(self, idx):
        row = self.df.iloc[idx]
        file_path = os.path.join(self.dataset_path, row['filename_lr'])
        
        # Load the WFDB record
        record, meta = wfdb.rdsamp(file_path)
        
        # Extract the specific lead (lead_index 2 = Lead III)
        signal = record[:, self.lead_index]
        
        # Bandpass filter (0.5Hz to 40Hz)
        from scipy.signal import butter, filtfilt
        nyquist = 0.5 * 100.0 # PTB-XL lr is 100Hz
        low = 0.5 / nyquist
        high = 40.0 / nyquist
        b, a = butter(3, [low, high], btype='band')
        signal = filtfilt(b, a, signal)
        
        # Normalize the signal to have zero mean and unit variance
        if np.std(signal) != 0:
            signal = (signal - np.mean(signal)) / np.std(signal)
            
        # Convert to PyTorch tensor (Shape: [Channels, Sequence Length] -> [1, 1000])
        signal_tensor = torch.tensor(signal, dtype=torch.float32).unsqueeze(0)
        label_tensor = torch.tensor(row['target'], dtype=torch.long)
        
        return signal_tensor, label_tensor

def get_dataloaders(dataset_path, batch_size=32, lead_index=2, train_split=0.8):
    df = load_ptbxl_metadata(dataset_path)
    
    # Shuffle dataframe
    df = df.sample(frac=1, random_state=42).reset_index(drop=True)
    
    # Split into train and validation
    split_idx = int(len(df) * train_split)
    train_df = df.iloc[:split_idx]
    val_df = df.iloc[split_idx:]
    
    train_dataset = PTBXLDataset(train_df, dataset_path, lead_index)
    val_dataset = PTBXLDataset(val_df, dataset_path, lead_index)
    
    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False, num_workers=0)
    
    return train_loader, val_loader

if __name__ == "__main__":
    # Test the loader
    d_path = "d:/AyuScan/backend/AI-model/dataset"
    train_l, val_l = get_dataloaders(d_path, batch_size=16)
    for signals, labels in train_l:
        print("Signal shape:", signals.shape)
        print("Labels shape:", labels.shape)
        break
