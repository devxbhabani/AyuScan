import time
import math
import numpy as np

class PPGProcessor:
    def __init__(self, fs=100):
        self.fs = fs
        self.bpm_history = []
        self.bpm_history_size = 4
        self.rr_intervals = []
        self.rr_history_len = 30
        
        self.current_bpm = 0
        self.last_good_bpm = 0
        self.cycles_since_good_contact = 0
        self.max_hold_cycles = 10 # hold for 10 evaluation cycles if finger shifts
        
        self.hrv_sdnn = 0.0
        self.hrv_rmssd = 0.0
        
        # Buffers for Maxim SpO2 (100 samples at 25Hz effective rate)
        self.spo2_ir_buffer = []
        self.spo2_red_buffer = []
        self.spo2_sample_counter = 0
        self.last_spo2 = 0
        
        # Beat detection state
        self.last_beat_time = 0
        self.ir_avg = 0
        
        # Cycle evaluation
        self.cycle_total_samples = 0
        self.cycle_good_contact = 0
        self.cycle_bpm_readings = []
        
        # State machine for peak detection (SparkFun PBA Algorithm)
        self.IR_AC_Max = 20
        self.IR_AC_Min = -20
        self.IR_AC_Signal_Current = 0
        self.IR_AC_Signal_Previous = 0
        self.IR_AC_Signal_min = 0
        self.IR_AC_Signal_max = 0
        self.IR_Average_Estimated = 0
        
        self.positiveEdge = 0
        self.negativeEdge = 0
        self.ir_avg_reg = 0.0
        
        self.cbuf = [0] * 32
        self.offset = 0
        self.FIRCoeffs = [172, 321, 579, 927, 1360, 1858, 2390, 2916, 3391, 3768, 4012, 4096]
        
    def add_rr_interval(self, rr_ms):
        if rr_ms < 300 or rr_ms > 2000:
            return
            
        self.rr_intervals.append(rr_ms)
        if len(self.rr_intervals) > self.rr_history_len:
            self.rr_intervals.pop(0)
            
        self._compute_hrv()
        
    def _compute_hrv(self):
        if len(self.rr_intervals) < 3:
            self.hrv_sdnn = 0
            self.hrv_rmssd = 0
            return
            
        # SDNN
        mean_rr = np.mean(self.rr_intervals)
        sum_sq_diff = sum((rr - mean_rr)**2 for rr in self.rr_intervals)
        self.hrv_sdnn = math.sqrt(sum_sq_diff / len(self.rr_intervals))
        
        # RMSSD
        sum_sq_succ_diff = 0
        pairs = 0
        for i in range(1, len(self.rr_intervals)):
            diff = self.rr_intervals[i] - self.rr_intervals[i - 1]
            sum_sq_succ_diff += diff * diff
            pairs += 1
            
        if pairs > 0:
            self.hrv_rmssd = math.sqrt(sum_sq_succ_diff / pairs)
            
    def _smooth_bpm(self, new_bpm):
        if new_bpm <= 0:
            return -1
            
        self.bpm_history.append(new_bpm)
        if len(self.bpm_history) > self.bpm_history_size:
            self.bpm_history.pop(0)
            
        return sum(self.bpm_history) / len(self.bpm_history)
        
    def _average_dc_estimator(self, sample):
        self.ir_avg_reg += (sample - self.ir_avg_reg) / 16.0
        return int(self.ir_avg_reg)
        
    def _low_pass_fir_filter(self, din):
        self.cbuf[self.offset] = din
        
        z = self.FIRCoeffs[11] * self.cbuf[(self.offset - 11) & 0x1F]
        for i in range(11):
            z += self.FIRCoeffs[i] * (self.cbuf[(self.offset - i) & 0x1F] + self.cbuf[(self.offset - 22 + i) & 0x1F])
            
        self.offset += 1
        self.offset %= 32
        
        return z >> 15
        
    def _check_for_beat(self, sample):
        # Exact port of SparkFun MAX30105 heartRate.cpp
        beat_detected = False
        
        self.IR_AC_Signal_Previous = self.IR_AC_Signal_Current
        self.IR_Average_Estimated = self._average_dc_estimator(sample)
        self.IR_AC_Signal_Current = self._low_pass_fir_filter(sample - self.IR_Average_Estimated)
        
        # Detect positive zero crossing (rising edge)
        if (self.IR_AC_Signal_Previous < 0) and (self.IR_AC_Signal_Current >= 0):
            self.IR_AC_Max = self.IR_AC_Signal_max
            self.IR_AC_Min = self.IR_AC_Signal_min
            
            self.positiveEdge = 1
            self.negativeEdge = 0
            self.IR_AC_Signal_max = 0
            
            ac_diff = self.IR_AC_Max - self.IR_AC_Min
            if 20 < ac_diff < 1000:
                beat_detected = True
                
        # Detect negative zero crossing (falling edge)
        if (self.IR_AC_Signal_Previous > 0) and (self.IR_AC_Signal_Current <= 0):
            self.positiveEdge = 0
            self.negativeEdge = 1
            self.IR_AC_Signal_min = 0
            
        # Find Maximum value in positive cycle
        if self.positiveEdge and (self.IR_AC_Signal_Current > self.IR_AC_Signal_Previous):
            self.IR_AC_Signal_max = self.IR_AC_Signal_Current
            
        # Find Minimum value in negative cycle
        if self.negativeEdge and (self.IR_AC_Signal_Current < self.IR_AC_Signal_Previous):
            self.IR_AC_Signal_min = self.IR_AC_Signal_Current
                
        return beat_detected

    def _maxim_spo2(self):
        if len(self.spo2_ir_buffer) < 100 or len(self.spo2_red_buffer) < 100:
            return self.last_spo2
            
        ir_data = np.array(self.spo2_ir_buffer[-100:], dtype=np.float64)
        red_data = np.array(self.spo2_red_buffer[-100:], dtype=np.float64)
        
        ir_dc = np.mean(ir_data)
        red_dc = np.mean(red_data)
        
        if ir_dc < 10000 or red_dc < 10000:
            return self.last_spo2
            
        ir_ac = ir_data - ir_dc
        red_ac = red_data - red_dc
        
        ir_rms = np.sqrt(np.mean(ir_ac**2))
        red_rms = np.sqrt(np.mean(red_ac**2))
        
        if ir_rms > 0:
            ratio = (red_rms / red_dc) / (ir_rms / ir_dc)
            spo2 = -45.060 * (ratio**2) + 30.354 * ratio + 94.845
            
            if 0 <= spo2 <= 100:
                self.last_spo2 = int(spo2)
                
        return self.last_spo2

    def process_samples(self, ir_array, red_array):
        for i in range(len(ir_array)):
            ir_val = ir_array[i]
            red_val = red_array[i]
            
            self.cycle_total_samples += 1
            if ir_val > 50000:
                self.cycle_good_contact += 1
                
                if self._check_for_beat(ir_val):
                    now = int(time.time() * 1000)
                    if self.last_beat_time != 0:
                        delta = now - self.last_beat_time
                        if 400 < delta < 1500:
                            if len(self.cycle_bpm_readings) < 10:
                                self.cycle_bpm_readings.append(60000.0 / delta)
                            self.add_rr_interval(float(delta))
                    self.last_beat_time = now
            
            if self.spo2_sample_counter % 4 == 0:
                self.spo2_ir_buffer.append(ir_val)
                self.spo2_red_buffer.append(red_val)
                if len(self.spo2_ir_buffer) > 100:
                    self.spo2_ir_buffer.pop(0)
                    self.spo2_red_buffer.pop(0)
            self.spo2_sample_counter += 1
            
        spo2 = self._maxim_spo2()
        
        # Evaluate cycle every 250 samples (2.5 seconds)
        if self.cycle_total_samples >= 250:
            self.evaluate_cycle()
            
        return self.current_bpm, spo2, self.hrv_sdnn, self.hrv_rmssd
        
    def evaluate_cycle(self):
        good_contact = (self.cycle_total_samples > 0) and (self.cycle_good_contact >= int(self.cycle_total_samples * 0.7))
        
        raw_cycle_bpm = 0
        if good_contact and len(self.cycle_bpm_readings) >= 2:
            raw_cycle_bpm = sum(self.cycle_bpm_readings) / len(self.cycle_bpm_readings)
            
        if not good_contact:
            self.cycles_since_good_contact += 1
        else:
            self.cycles_since_good_contact = 0
            
        smoothed = self._smooth_bpm(raw_cycle_bpm)
        
        if smoothed > 0:
            self.current_bpm = int(smoothed)
            self.last_good_bpm = self.current_bpm
        elif self.cycles_since_good_contact < self.max_hold_cycles:
            self.current_bpm = self.last_good_bpm
        else:
            self.current_bpm = 0
            self.last_good_bpm = 0
            self.bpm_history.clear()
            self.rr_intervals.clear()
            self.hrv_sdnn = 0
            self.hrv_rmssd = 0
            
        self.cycle_total_samples = 0
        self.cycle_good_contact = 0
        self.cycle_bpm_readings.clear()
