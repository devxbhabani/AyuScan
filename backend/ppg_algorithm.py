import time
import math
import numpy as np
from scipy.signal import butter, filtfilt, find_peaks

class PPGProcessor:
    def __init__(self, fs=100):
        self.fs = fs
        self.current_bpm = 0
        self.last_good_bpm = 0
        self.bpm_history = []
        self.bpm_history_size = 8
        self.cycles_since_good_contact = 0
        self.max_hold_cycles = 10

        self.hrv_sdnn = 0.0
        self.hrv_rmssd = 0.0
        self.rr_intervals = []
        self.rr_history_len = 30

        # Rolling IR buffer for peak-based BPM detection (5 seconds @ 100Hz)
        self.ir_buffer = []
        self.IR_BUFFER_SIZE = 500

        # Buffers for SpO2 calculation
        self.spo2_ir_buffer = []
        self.spo2_red_buffer = []
        self.spo2_sample_counter = 0
        self.last_spo2 = 0

        # SpO2 smoothing
        self.spo2_history = []
        self.spo2_history_size = 8
        self.spo2_ema = 0.0
        self.spo2_ema_alpha = 0.2
        self.MIN_IR_STRENGTH = 30000
        self.MIN_AC_RATIO = 0.001

        # Cycle evaluation
        self.cycle_total_samples = 0
        self.cycle_good_contact = 0

    # ---- HRV ----
    def _update_rr(self, rr_intervals_sec):
        """Update RR intervals and recompute HRV metrics."""
        rr_ms = [r * 1000 for r in rr_intervals_sec if 500 < r * 1000 < 1200]
        self.rr_intervals.extend(rr_ms)
        if len(self.rr_intervals) > self.rr_history_len:
            self.rr_intervals = self.rr_intervals[-self.rr_history_len:]
        self._compute_hrv()

    def _compute_hrv(self):
        if len(self.rr_intervals) < 3:
            self.hrv_sdnn = 0.0
            self.hrv_rmssd = 0.0
            return
        mean_rr = np.mean(self.rr_intervals)
        self.hrv_sdnn = float(np.sqrt(np.mean((np.array(self.rr_intervals) - mean_rr) ** 2)))
        diffs = np.diff(self.rr_intervals)
        self.hrv_rmssd = float(np.sqrt(np.mean(diffs ** 2))) if len(diffs) > 0 else 0.0

    # ---- BPM via scipy find_peaks ----
    def _compute_bpm_from_buffer(self):
        """
        Bandpass-filter the last 5s of IR, then use find_peaks to find
        systolic peaks and compute BPM from median inter-peak interval.
        Much more robust than the FIR zero-crossing port for bursty FIFO data.
        """
        if len(self.ir_buffer) < self.IR_BUFFER_SIZE:
            return 0, []

        ir = np.array(self.ir_buffer[-self.IR_BUFFER_SIZE:], dtype=np.float64)

        # Gate: require DC level indicating finger contact
        if np.mean(ir) < self.MIN_IR_STRENGTH:
            return 0, []

        # Bandpass 0.75–2.5 Hz  (45–150 bpm) - narrower to reject harmonics
        nyq = 0.5 * self.fs
        b, a = butter(2, [0.75 / nyq, 2.5 / nyq], btype='band')
        filtered = filtfilt(b, a, ir)

        # min_dist = 0.5s → max 120 bpm (increased from 0.4s to skip dicrotic notch)
        # width = min 8 samples (80ms) → rejects narrow dicrotic notch peaks
        # prominence = 0.3*std → rejects small noise peaks
        min_dist = int(0.5 * self.fs)
        peaks, _ = find_peaks(
            filtered,
            distance=min_dist,
            prominence=0.3 * np.std(filtered),
            width=int(0.08 * self.fs)   # systolic peaks are wide (~200ms); dicrotic is narrow
        )

        if len(peaks) < 2:
            return 0, []

        # Inter-peak intervals in seconds
        rr = np.diff(peaks) / self.fs
        # Accept only physiological range (50–120 bpm = 0.5–1.2s)
        valid_rr = rr[(rr >= 0.5) & (rr <= 1.2)]

        if len(valid_rr) == 0:
            return 0, []

        bpm = 60.0 / np.median(valid_rr)

        # Diagnostic: show exactly what peaks were found
        rr_bpms = [round(60.0 / r, 1) for r in valid_rr]
        print(f"[BPM Debug] peaks_found={len(peaks)}, intervals_bpm={rr_bpms}, result={bpm:.1f}")

        return float(bpm), list(valid_rr)

    def _smooth_bpm(self, new_bpm):
        if new_bpm <= 0:
            return -1
        self.bpm_history.append(new_bpm)
        if len(self.bpm_history) > self.bpm_history_size:
            self.bpm_history.pop(0)
        return float(np.mean(self.bpm_history))

    # ---- SpO2 ----
    def _maxim_spo2(self):
        if len(self.spo2_ir_buffer) < 100 or len(self.spo2_red_buffer) < 100:
            return self.last_spo2

        ir_data  = np.array(self.spo2_ir_buffer[-100:], dtype=np.float64)
        red_data = np.array(self.spo2_red_buffer[-100:], dtype=np.float64)

        ir_dc  = np.mean(ir_data)
        red_dc = np.mean(red_data)

        # Gate 1: require finger contact (sufficient DC level)
        if ir_dc < self.MIN_IR_STRENGTH or red_dc < 10000:
            return self.last_spo2

        # Bandpass-filter both channels before extracting AC component.
        # This removes baseline wander and motion artifacts — the #1 cause
        # of false low SpO2 readings. Range: 0.5–3.5 Hz (30–210 bpm).
        nyq = 0.5 * 25.0  # SpO2 buffer is at 25 Hz (downsampled 4:1 from 100Hz)
        b, a = butter(2, [0.5 / nyq, 3.5 / nyq], btype='band')
        try:
            ir_ac_filt  = filtfilt(b, a, ir_data)
            red_ac_filt = filtfilt(b, a, red_data)
        except Exception:
            return self.last_spo2

        ir_rms  = np.sqrt(np.mean(ir_ac_filt  ** 2))
        red_rms = np.sqrt(np.mean(red_ac_filt ** 2))

        # Gate 2: require pulsatile signal (AC/DC ratio check)
        if ir_rms / ir_dc < self.MIN_AC_RATIO:
            return self.last_spo2

        if ir_rms <= 0:
            return self.last_spo2

        ratio = (red_rms / red_dc) / (ir_rms / ir_dc)

        # Gate 3: physiological ratio range.
        # At SpO2=100%: ratio≈0.4; at SpO2=80%: ratio≈1.0.
        # Values outside 0.3–1.2 are motion artifacts, not physiology.
        if not (0.3 <= ratio <= 1.2):
            return self.last_spo2

        spo2_raw = -45.060 * (ratio ** 2) + 30.354 * ratio + 94.845

        # Gate 4: physiological SpO2 range for a healthy person
        if not (85 <= spo2_raw <= 100):
            return self.last_spo2

        # Gate 5: tight outlier rejection — reject if deviates > 3% from history
        if len(self.spo2_history) >= 3:
            median_val = float(np.median(self.spo2_history))
            if abs(spo2_raw - median_val) > 3:
                return self.last_spo2

        # EMA smoothing (alpha=0.1: very slow, very stable)
        if self.spo2_ema == 0.0:
            self.spo2_ema = spo2_raw
        else:
            self.spo2_ema = 0.1 * spo2_raw + 0.9 * self.spo2_ema

        self.spo2_history.append(spo2_raw)
        if len(self.spo2_history) > self.spo2_history_size:
            self.spo2_history.pop(0)

        self.last_spo2 = int(round(self.spo2_ema))
        return self.last_spo2


    # ---- Main entry point ----
    def process_samples(self, ir_array, red_array):
        if not ir_array:
            return self.current_bpm, self.last_spo2, self.hrv_sdnn, self.hrv_rmssd

        for i, (ir_val, red_val) in enumerate(zip(ir_array, red_array)):
            self.cycle_total_samples += 1
            if ir_val > self.MIN_IR_STRENGTH:
                self.cycle_good_contact += 1

            # Accumulate rolling IR buffer for BPM
            self.ir_buffer.append(ir_val)
            if len(self.ir_buffer) > self.IR_BUFFER_SIZE:
                self.ir_buffer.pop(0)

            # Downsample 4:1 for SpO2 (25 Hz effective)
            if self.spo2_sample_counter % 4 == 0:
                self.spo2_ir_buffer.append(ir_val)
                self.spo2_red_buffer.append(red_val)
                if len(self.spo2_ir_buffer) > 100:
                    self.spo2_ir_buffer.pop(0)
                    self.spo2_red_buffer.pop(0)
            self.spo2_sample_counter += 1

        spo2 = self._maxim_spo2()

        # Evaluate BPM every 250 samples (2.5 s)
        if self.cycle_total_samples >= 250:
            self._evaluate_cycle()

        return self.current_bpm, spo2, self.hrv_sdnn, self.hrv_rmssd

    def _evaluate_cycle(self):
        good_contact = (self.cycle_total_samples > 0 and
                        self.cycle_good_contact >= int(self.cycle_total_samples * 0.5))

        if not good_contact:
            self.cycles_since_good_contact += 1
        else:
            self.cycles_since_good_contact = 0

        if good_contact:
            raw_bpm, valid_rr = self._compute_bpm_from_buffer()
            if valid_rr:
                self._update_rr(valid_rr)

            smoothed = self._smooth_bpm(raw_bpm)
            if smoothed > 0:
                self.current_bpm = int(round(smoothed))
                self.last_good_bpm = self.current_bpm
            elif self.cycles_since_good_contact < self.max_hold_cycles:
                self.current_bpm = self.last_good_bpm
            else:
                self._reset()
        elif self.cycles_since_good_contact < self.max_hold_cycles:
            self.current_bpm = self.last_good_bpm
        else:
            self._reset()

        self.cycle_total_samples  = 0
        self.cycle_good_contact   = 0

    def _reset(self):
        self.current_bpm   = 0
        self.last_good_bpm = 0
        self.bpm_history.clear()
        self.rr_intervals.clear()
        self.hrv_sdnn  = 0.0
        self.hrv_rmssd = 0.0
