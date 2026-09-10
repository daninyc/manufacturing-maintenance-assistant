import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CHROMA_PATH = PROJECT_ROOT / os.getenv("CHROMA_PATH", "data/chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "day1_baseline")
TOP_K = int(os.getenv("TOP_K", "3"))
DAY2_COLLECTION = "day2_semantic_v1"
# 实验参数：五题开发集上检查过，未声称是通用最佳阈值。
MAX_DISTANCE = 0.50
