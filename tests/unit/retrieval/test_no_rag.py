"""src/ must not depend on embedding / vector index libraries."""

from __future__ import annotations

from pathlib import Path

FORBIDDEN = (
    "chromadb",
    "faiss",
    "langchain",
    "sentence_transformers",
    "pinecone",
    "openai.embeddings",
    "vectorstore",
    "embedding",
)


def test_no_rag_dependencies_in_source():
    root = Path("src")
    blob = "\n".join(p.read_text() for p in root.rglob("*.py"))
    lowered = blob.lower()
    for token in ("chromadb", "faiss", "langchain", "pinecone", "vectorstore", "sentence_transformers"):
        assert token not in lowered
