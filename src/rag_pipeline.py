"""
RAG Pipeline for College GPT (Capstone Architecture).
Coordinates document ingestion, chunking, vector indexing, retrieval, and generation.
"""

import os
import glob
import re
from typing import List, Dict, Any, Optional

from src.document_processor import extract_document, chunk_text
from src.vector_store import CollegeVectorStore
from src.llm_client import CollegeLLMClient

COMMON_COLLEGE_TYPOS = [
    (r"\bjango\b", "django"),
    (r"\bpyton\b|\bphyton\b|\bpyhton\b", "python"),
    (r"\bpostgre\b|\bpostgress\b|\bpostgres\b", "postgresql"),
    (r"\breactjs\b", "react"),
    (r"\bsem\b|\bsemister\b|\bsemster\b", "semester"),
    (r"\bsylabus\b|\bsyllbus\b|\bsyllabous\b", "syllabus"),
    (r"\batendance\b|\battedance\b|\battandance\b", "attendance"),
    (r"\btimetbl\b|\btime table\b", "timetable"),
    (r"\bsched\b|\bscheduel\b", "schedule"),
    (r"\bsub\b|\bsubjet\b|\bsubjets\b", "subject subjects"),
]

def normalize_query_typos(text: str) -> str:
    cleaned = text
    for pattern, repl in COMMON_COLLEGE_TYPOS:
        cleaned = re.sub(pattern, repl, cleaned, flags=re.IGNORECASE)
    return cleaned


class CollegeRAGPipeline:
    def __init__(self, base_dir: Optional[str] = None):
        if base_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.base_dir = base_dir
        self.inbuilt_dir = os.path.join(self.base_dir, "data", "inbuilt")

        is_vercel = os.getenv("VERCEL") == "1" or os.path.exists("/var/task")
        if is_vercel:
            self.persist_dir = "/tmp/chroma_db"
            self.uploads_dir = "/tmp/uploads"
            # In Vercel serverless, copy pre-indexed ChromaDB to writable /tmp
            bundled_db = os.path.join(self.base_dir, "chroma_db")
            if not os.path.exists(self.persist_dir) and os.path.exists(bundled_db):
                try:
                    import shutil
                    shutil.copytree(bundled_db, self.persist_dir, dirs_exist_ok=True)
                except Exception as e:
                    print(f"[College GPT] Vercel /tmp chroma copy: {e}")
        else:
            self.persist_dir = os.path.join(self.base_dir, "chroma_db")
            self.uploads_dir = os.path.join(self.base_dir, "data", "uploads")

        try:
            os.makedirs(self.inbuilt_dir, exist_ok=True)
        except OSError:
            pass
        try:
            os.makedirs(self.uploads_dir, exist_ok=True)
        except OSError:
            pass

        self.vector_store = CollegeVectorStore(persist_dir=self.persist_dir)
        self.llm_client = CollegeLLMClient()

    def index_all_documents(self) -> Dict[str, Any]:
        """
        Indexes all files in data/inbuilt and data/uploads.
        """
        indexed_files = []
        total_chunks = 0
        all_files = (
            glob.glob(os.path.join(self.inbuilt_dir, "*.pdf")) +
            glob.glob(os.path.join(self.inbuilt_dir, "*.docx")) +
            glob.glob(os.path.join(self.inbuilt_dir, "*.doc")) +
            glob.glob(os.path.join(self.uploads_dir, "*.pdf")) +
            glob.glob(os.path.join(self.uploads_dir, "*.docx")) +
            glob.glob(os.path.join(self.uploads_dir, "*.doc"))
        )

        for file_path in all_files:
            try:
                chunks_added = self.index_single_file(file_path)
                indexed_files.append({
                    "filename": os.path.basename(file_path),
                    "chunks": chunks_added,
                    "status": "success"
                })
                total_chunks += chunks_added
            except Exception as e:
                indexed_files.append({
                    "filename": os.path.basename(file_path),
                    "error": str(e),
                    "status": "failed"
                })

        return {
            "total_files": len(all_files),
            "indexed_files": indexed_files,
            "total_chunks_indexed": total_chunks,
            "total_vectors_in_store": self.vector_store.collection.count()
        }

    def index_single_file(self, file_path: str) -> int:
        """
        Processes and indexes a single PDF or Word document into the vector database.
        """
        pages_data = extract_document(file_path)
        if not pages_data:
            return 0
        chunks = chunk_text(pages_data, chunk_size=900, chunk_overlap=100)
        return self.vector_store.add_chunks(chunks)

    def remove_document(self, filename: str) -> bool:
        """
        Deletes document vectors from ChromaDB and file from uploads folder if present.
        """
        # Delete from vector store
        deleted_count = self.vector_store.delete_document(filename)

        # Delete physical file if in uploads
        upload_path = os.path.join(self.uploads_dir, filename)
        if os.path.exists(upload_path):
            try:
                os.remove(upload_path)
            except Exception as e:
                print(f"Could not remove physical file {upload_path}: {e}")

        return deleted_count > 0

    def query(self, question: str, n_results: int = 8, provider: Optional[str] = None, target_doc: Optional[str] = None) -> Dict[str, Any]:
        """
        Complete RAG inference cycle:
        1. Retrieve top-k semantic matches (with optional document filtering)
        2. Format source citations
        3. Call LLM for grounded answer
        """
        clean_q = question.strip()
        if not clean_q:
            return {
                "error": "Question cannot be empty.",
                "answer": "",
                "sources": []
            }

        q_lower = clean_q.lower()
        auto_target = target_doc
        if not auto_target:
            # If inquiry is about an uploaded or general pdf/file, auto-target the most recent upload if available
            if any(w in q_lower for w in ["pdf", "uploaded", "this document", "this file", "the document", "the file", "attached"]):
                upload_files = [os.path.basename(f) for f in glob.glob(os.path.join(self.uploads_dir, "*.*"))]
                if upload_files:
                    auto_target = upload_files[-1]

        # Use 8 chunks normally, or 10 chunks for document summaries and full schedules
        is_broad_q = any(w in q_lower for w in ["what is", "about", "summary", "summarize", "overview", "cover", "full info", "complete info", "timetable", "schedule"])
        effective_n = max(n_results, 10 if is_broad_q else 8)

        # Check for common typos and merge chunks if normalized query differs
        normalized_q = normalize_query_typos(clean_q)
        retrieved_chunks = self.vector_store.query(clean_q, n_results=effective_n, filter_source=auto_target)

        if normalized_q.lower() != clean_q.lower():
            extra_chunks = self.vector_store.query(normalized_q, n_results=effective_n, filter_source=auto_target)
            existing_ids = {c.get("id") for c in retrieved_chunks}
            for ec in extra_chunks:
                if ec.get("id") not in existing_ids:
                    retrieved_chunks.append(ec)
                    existing_ids.add(ec.get("id"))

        if not retrieved_chunks:
            return {
                "answer": "I do not have information regarding the question asked in the college documents.",
                "sources": [],
                "provider": "None",
                "chunks_retrieved": 0
            }

        # Deduplicate and extract sources for UI
        sources = []
        seen = set()
        for c in retrieved_chunks:
            meta = c.get("metadata", {})
            src = meta.get("source", "document")
            page = meta.get("page", 1)
            doc_type = meta.get("doc_type", "pdf")
            key = (src, page)
            if key not in seen:
                seen.add(key)
                # 200 char snippet for preview
                snippet = c.get("text", "")[:240].replace("\n", " ").strip()
                if len(c.get("text", "")) > 240:
                    snippet += "..."
                sources.append({
                    "file": src,
                    "page": page,
                    "doc_type": doc_type,
                    "excerpt": snippet,
                    "similarity": c.get("similarity", 0.0)
                })

        # Generate grounded response
        answer, provider_used = self.llm_client.generate_response(
            question=clean_q,
            retrieved_chunks=retrieved_chunks,
            custom_provider=provider
        )

        # If answer indicates out-of-syllabus, clear any irrelevant retrieved sources
        if "I do not have information regarding the question asked" in answer:
            sources = []

        return {
            "answer": answer,
            "sources": sources,
            "provider": provider_used,
            "chunks_retrieved": len(retrieved_chunks) if sources else 0
        }

    def get_status(self) -> Dict[str, Any]:
        """
        Returns full health and indexing status for the UI dashboard.
        """
        stats = self.vector_store.get_stats()
        inbuilt_files = [os.path.basename(f) for f in glob.glob(os.path.join(self.inbuilt_dir, "*.*"))]
        upload_files = [os.path.basename(f) for f in glob.glob(os.path.join(self.uploads_dir, "*.*"))]

        return {
            "status": "ready",
            "total_chunks": stats["total_chunks"],
            "total_documents": stats["total_documents"],
            "inbuilt_files": inbuilt_files,
            "uploaded_files": upload_files,
            "active_provider": self.llm_client.get_active_provider(),
            "indexed_documents": stats["documents"]
        }
