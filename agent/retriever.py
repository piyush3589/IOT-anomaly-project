"""
RAG retriever — semantic search over the IoT remediation knowledge base.
Called by the agent's remediation node after anomaly is confirmed.
"""

import os
import chromadb
from chromadb.utils import embedding_functions
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

CHROMA_PATH = os.getenv("CHROMA_DB_PATH", "./chroma_db")


class RemediationRetriever:
    def __init__(self):
        self._client = None
        self._collection = None

    def _ensure_loaded(self):
        if self._collection is not None:
            return
        client = chromadb.PersistentClient(path=CHROMA_PATH)
      
        ef = DefaultEmbeddingFunction()
        self._collection = client.get_collection(
            name="iot_remediation_kb",
            embedding_function=ef,
        )

    def retrieve(self, query: str, n_results: int = 2) -> tuple[str, str, float]:
        """
        Returns (document_text, source_id, confidence_score).
        Confidence is 1 - cosine_distance (ChromaDB returns distances).
        """
        self._ensure_loaded()
        results = self._collection.query(
            query_texts=[query],
            n_results=n_results,
            include=["documents", "distances", "metadatas"],
        )

        docs = results["documents"][0]
        distances = results["distances"][0]
        ids = results["ids"][0]

        # Combine top results
        combined = "\n\n---\n\n".join(docs)
        best_id = ids[0]
        # ChromaDB L2 distance → normalise to 0-1 confidence (rough)
        confidence = round(max(0.0, 1.0 - distances[0] / 2.0), 2)

        return combined, best_id, confidence


# Singleton
retriever = RemediationRetriever()
