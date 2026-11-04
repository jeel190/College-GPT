"""
Vector Store Manager for College GPT using ChromaDB.
Handles document indexing, dynamic updates, deletion, and semantic similarity search.
"""

import os
import chromadb
from chromadb.config import Settings
from typing import List, Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PERSIST_DIR = os.path.join(BASE_DIR, "chroma_db")
COLLECTION_NAME = "college_gpt_knowledge"

# Keep ONNX model cache inside repository directory so Render builds retain it
try:
    from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2
    ONNXMiniLM_L6_V2.DOWNLOAD_PATH = os.path.join(BASE_DIR, "chroma_models", "all-MiniLM-L6-v2")
except Exception:
    pass

class CollegeVectorStore:
    def __init__(self, persist_dir: str = DEFAULT_PERSIST_DIR):
        self.persist_dir = persist_dir
        os.makedirs(self.persist_dir, exist_ok=True)
        
        # Initialize Persistent Chroma Client
        self.client = chromadb.PersistentClient(
            path=self.persist_dir,
            settings=Settings(anonymized_telemetry=False)
        )
        
        # Get or create collection with default embedding function (ONNX all-MiniLM-L6-v2)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "College GPT Academic Knowledge Base (Capstone RAG)"}
        )

    def add_chunks(self, chunks: List[Dict[str, Any]]) -> int:
        """
        Adds text chunks to the Chroma vector store.
        Each chunk dict has: {'id': str, 'text': str, 'metadata': dict}
        """
        if not chunks:
            return 0

        ids = []
        documents = []
        metadatas = []

        for c in chunks:
            ids.append(c["id"])
            documents.append(c["text"])
            # Chroma metadata must have primitive values (str, int, float, bool)
            meta = {k: str(v) if not isinstance(v, (str, int, float, bool)) else v 
                    for k, v in c["metadata"].items()}
            metadatas.append(meta)

        # Chroma upsert ensures idempotency
        # Batch in chunks of 15 for ultra-low memory, cloud-safe execution
        batch_size = 15
        for i in range(0, len(ids), batch_size):
            end = i + batch_size
            self.collection.upsert(
                ids=ids[i:end],
                documents=documents[i:end],
                metadatas=metadatas[i:end]
            )

        return len(chunks)

    def query(self, query_text: str, n_results: int = 5) -> List[Dict[str, Any]]:
        """
        Queries the vector store for top-k semantically relevant chunks.
        Returns list of dicts with text, metadata, and distance.
        """
        total = self.collection.count()
        if total == 0:
            return []

        actual_n = min(n_results, total)
        results = self.collection.query(
            query_texts=[query_text],
            n_results=actual_n
        )

        formatted_results = []
        if results and "documents" in results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0] if "metadatas" in results and results["metadatas"] else [{}] * len(docs)
            distances = results["distances"][0] if "distances" in results and results["distances"] else [0.0] * len(docs)
            ids = results["ids"][0] if "ids" in results and results["ids"] else [""] * len(docs)

            for doc, meta, dist, chunk_id in zip(docs, metas, distances, ids):
                formatted_results.append({
                    "id": chunk_id,
                    "text": doc,
                    "metadata": meta,
                    "distance": dist,
                    # Approximate similarity score (for cosine/L2)
                    "similarity": round(max(0.0, 1.0 - (dist if dist is not None else 0.5)), 3)
                })

        return formatted_results

    def delete_document(self, filename: str) -> int:
        """
        Removes all chunks associated with a specific file from the vector store.
        """
        try:
            # Query IDs with source == filename
            results = self.collection.get(
                where={"source": filename}
            )
            if results and results.get("ids"):
                ids_to_del = results["ids"]
                self.collection.delete(ids=ids_to_del)
                return len(ids_to_del)
        except Exception as e:
            print(f"Error deleting {filename}: {e}")
        return 0

    def get_indexed_documents(self) -> List[Dict[str, Any]]:
        """
        Returns list of all unique documents currently indexed in ChromaDB with chunk counts.
        """
        try:
            all_records = self.collection.get(include=["metadatas"])
            if not all_records or not all_records.get("metadatas"):
                return []

            doc_counts: Dict[str, Dict[str, Any]] = {}
            for meta in all_records["metadatas"]:
                source = meta.get("source", "Unknown")
                doc_type = meta.get("doc_type", "pdf")
                if source not in doc_counts:
                    doc_counts[source] = {
                        "name": source,
                        "type": doc_type,
                        "chunks": 0
                    }
                doc_counts[source]["chunks"] += 1

            return list(doc_counts.values())
        except Exception as e:
            print(f"Error fetching indexed documents: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """
        Returns total chunks and count of indexed documents.
        """
        docs = self.get_indexed_documents()
        return {
            "total_chunks": self.collection.count(),
            "total_documents": len(docs),
            "documents": docs
        }

    def reset_collection(self):
        """
        Deletes and recreates the collection.
        """
        self.client.delete_collection(name=COLLECTION_NAME)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "College GPT Academic Knowledge Base (Capstone RAG)"}
        )
