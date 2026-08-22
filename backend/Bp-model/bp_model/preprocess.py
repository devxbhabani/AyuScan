import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

def butter_bandpass(lowcut, highcut, fs, order=3):
    nyquist = 0.5 * fs
    low = lowcut / nyquist
    high = highcut / nyquist
    b, a = butter(order, [low, high], btype='band')
    return b, a

def butter_lowpass(cutoff, fs, order=3):
    nyquist = 0.5 * fs
    normal_cutoff = cutoff / nyquist
    b, a = butter(order, normal_cutoff, btype='low', analog=False)
    return b, a

def filter_signal(data, lowcut, highcut, fs, order=3):
    b, a = butter_bandpass(lowcut, highcut, fs, order=order)
    return filtfilt(b, a, data)

def extract_features(ecg, ppg, art=None, fs=100):
    """
    Extracts features from 5-second windows of ECG and PPG.
    fs = 100 Hz by default from VitalDB downloader.
    """
    # 1. Filter signals
    ecg_filtered = filter_signal(ecg, 0.5, 40.0, fs)
    ppg_filtered = filter_signal(ppg, 0.5, 8.0, fs)
    
    # 2. Peak Detection
    # ECG R-peaks: usually > 0.5 threshold after normalization, min distance 0.5s (50 samples at 100Hz)
    ecg_norm = (ecg_filtered - np.mean(ecg_filtered)) / (np.std(ecg_filtered) + 1e-8)
    r_peaks, _ = find_peaks(ecg_norm, distance=int(0.5 * fs), height=0.5)
    
    # PPG peaks (systolic)
    ppg_norm = (ppg_filtered - np.mean(ppg_filtered)) / (np.std(ppg_filtered) + 1e-8)
    ppg_peaks, _ = find_peaks(ppg_norm, distance=int(0.5 * fs), height=0.2)
    
    # PPG feet (diastolic) - inverted peaks
    ppg_feet, _ = find_peaks(-ppg_norm, distance=int(0.5 * fs))

    # 3. Calculate Features
    ptts = []
    ppg_amps = []
    
    for r in r_peaks:
        # Find the next immediate PPG foot
        next_feet = ppg_feet[ppg_feet > r]
        if len(next_feet) > 0:
            foot = next_feet[0]
            ptt = (foot - r) / fs # in seconds
            # Physiological limit for PTT is roughly 100ms to 400ms (0.1 to 0.4s)
            if 0.1 <= ptt <= 0.5:
                ptts.append(ptt)
                
        # Find next immediate PPG peak for amplitude
        next_peaks = ppg_peaks[ppg_peaks > r]
        if len(next_peaks) > 0 and len(next_feet) > 0:
            peak = next_peaks[0]
            foot = next_feet[0]
            if foot < peak:
                amp = ppg_filtered[peak] - ppg_filtered[foot]
                ppg_amps.append(amp)
                
    if len(r_peaks) < 2 or len(ptts) == 0:
        return None # Bad window

    rr_intervals = np.diff(r_peaks) / fs
    hr = 60.0 / np.mean(rr_intervals)
    
    if hr < 40 or hr > 200:
        return None

    features = {
        "hr": hr,
        "ptt_mean": np.mean(ptts),
        "ptt_std": np.std(ptts) if len(ptts) > 1 else 0,
        "ppg_amp_mean": np.mean(ppg_amps) if len(ppg_amps) > 0 else 0,
        "rr_std": np.std(rr_intervals) if len(rr_intervals) > 1 else 0
    }
    
    # Extract ART labels if provided (training mode)
    if art is not None:
        # Lowpass ART to smooth out noise
        b, a = butter_lowpass(10.0, fs, order=3)
        art_smooth = filtfilt(b, a, art)
        
        sbp = np.max(art_smooth)
        dbp = np.min(art_smooth)
        
        if sbp > 220 or sbp < 70 or dbp > 130 or dbp < 40:
            return None # Invalid blood pressure physiologically
            
        features["sbp"] = sbp
        features["dbp"] = dbp
        
    return features
