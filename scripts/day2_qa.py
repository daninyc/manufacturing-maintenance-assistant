import argparse
import json

from app.core.config import CHROMA_PATH, DAY2_COLLECTION, MAX_DISTANCE
from app.retrieval.vector_store import LocalChromaStore
from app.schemas.qa import AskRequest
from app.services.qa_service import answer_question


def main() -> None:
    parser = argparse.ArgumentParser(description="Day 2 可回查证据问答")
    parser.add_argument("--question", required=True)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--max-distance", type=float, default=MAX_DISTANCE)
    parser.add_argument("--mode", choices=["local", "deepseek"], default="local")
    args = parser.parse_args()
    store = LocalChromaStore(CHROMA_PATH, DAY2_COLLECTION, semantic=True)
    response = answer_question(store, AskRequest(question=args.question, top_k=args.top_k),
                               mode=args.mode, max_distance=args.max_distance)
    print(json.dumps(response.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
