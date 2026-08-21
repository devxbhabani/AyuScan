import os
import urllib.request

DATA_DIR = "spo2-dataset"
os.makedirs(DATA_DIR, exist_ok=True)

base_url = "https://physionet.org/files/bidmc/1.0.0/"
files_to_download = [f"bidmc_{str(i).zfill(2)}_Numerics.csv" for i in range(1, 54)]

print(f"Downloading {len(files_to_download)} files from PhysioNet BIDMC dataset...")

for filename in files_to_download:
    url = base_url + filename
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        try:
            print(f"Downloading {filename}...")
            urllib.request.urlretrieve(url, filepath)
        except Exception as e:
            print(f"Failed to download {filename}: {e}")
    else:
        print(f"File {filename} already exists.")

print("Download complete.")
