import os
import pandas as pd
from tqdm import tqdm
import vitaldb

vitaldb.login(
    "bsjana3400@gmail.com",
    "Bhabani@2006"
)

# ==========================
# Configuration
# ==========================

OUTPUT_FOLDER = "dataset"
MAX_CASES = 100

# ECG, PPG and Arterial Blood Pressure
TRACKS = [
    "ECG_II",
    "PLETH",
    "ART"
]

# Sampling interval (0.01 = 100 Hz)
INTERVAL = 0.01

# ==========================
# Create Output Folder
# ==========================

os.makedirs(OUTPUT_FOLDER, exist_ok=True)

print("=" * 60)
print("Searching for cases containing ECG + PPG + ART...")
print("=" * 60)

# --------------------------
# Find matching cases
# --------------------------

case_ids = vitaldb.find_cases(TRACKS)

print(f"\nFound {len(case_ids)} valid cases.")

if len(case_ids) == 0:
    print("No matching cases found.")
    exit()

print(f"\nDownloading first {min(MAX_CASES, len(case_ids))} cases...\n")

downloaded = 0

for caseid in tqdm(case_ids):

    if downloaded >= MAX_CASES:
        break

    try:

        data = vitaldb.load_case(
            caseid,
            TRACKS,
            interval=INTERVAL
        )

        if data is None:
            continue

        if len(data) == 0:
            continue

        df = pd.DataFrame(data, columns=TRACKS)

        filename = os.path.join(
            OUTPUT_FOLDER,
            f"case_{caseid}.csv"
        )

        df.to_csv(filename, index=False)

        downloaded += 1

    except Exception as e:

        print(f"\nSkipped Case {caseid}")
        print(e)

print("\n" + "=" * 60)
print(f"Finished!")
print(f"Downloaded {downloaded} cases.")
print(f"Saved in: {OUTPUT_FOLDER}")
print("=" * 60)