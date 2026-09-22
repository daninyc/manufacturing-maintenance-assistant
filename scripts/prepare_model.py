from app.retrieval.embedding import MODEL_NAME, embed_texts

if __name__ == "__main__":
    vectors = embed_texts(["机器人工作半径"], query=True)
    print(f"model={MODEL_NAME}, dimensions={len(vectors[0])}")
