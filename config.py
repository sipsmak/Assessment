from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
INPUT_DIR = BASE_DIR / "data" / "input"
OUTPUT_DIR = BASE_DIR / "data" / "output"

BATCH_FILES = [
    INPUT_DIR / "bookings_batch1_2025-09-01.csv",
    INPUT_DIR / "bookings_batch2_2025-09-02.csv",
]
PROPERTIES_FILE = INPUT_DIR / "properties.csv"
FX_FILE = INPUT_DIR / "fx_rates.csv"

MAX_GUESTS = 20
VALID_STATUSES = {"confirmed", "pending", "cancelled"}
