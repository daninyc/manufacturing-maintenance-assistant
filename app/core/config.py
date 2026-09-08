import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHROMA_PATH = PROJECT_ROOT / os.getenv("CHROMA_PATH", "data/chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "day1_baseline")
TOP_K = int(os.getenv("TOP_K", "3"))
