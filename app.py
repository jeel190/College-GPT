"""
College GPT - Intelligent Campus Knowledge Assistant
Flask Application Server with REST API & Capstone RAG Pipeline.
"""

import os
import sys
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Ensure root directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# Load environment from both CollegeGPT and parent Gen Ai
load_dotenv(os.path.join(PARENT_DIR, ".env"), override=False)
load_dotenv(os.path.join(BASE_DIR, ".env"), override=True)

from src.rag_pipeline import CollegeRAGPipeline

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static")
)
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32MB max file upload
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc"}

# Initialize Pipeline
pipeline = CollegeRAGPipeline(base_dir=BASE_DIR)

def reload_env_if_needed():
    """Reloads .env variables in case user edited them manually in Notepad."""
    parent_env = os.path.join(PARENT_DIR, ".env")
    base_env = os.path.join(BASE_DIR, ".env")
    
    for p in [parent_env, base_env]:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("GEMINI_API_KEY="):
                            val = line.split("=", 1)[1].strip()
                            if val:
                                os.environ["GEMINI_API_KEY"] = val
                        elif line.startswith("GEMINI_MODEL="):
                            val = line.split("=", 1)[1].strip()
                            if val:
                                os.environ["GEMINI_MODEL"] = val
                        elif line.startswith("DEFAULT_LLM_PROVIDER="):
                            val = line.split("=", 1)[1].strip()
                            if val:
                                os.environ["DEFAULT_LLM_PROVIDER"] = val
            except Exception:
                pass
    pipeline.llm_client.load_env()

# Auto-index on initial startup if store is empty
try:
    if pipeline.vector_store.collection.count() == 0:
        print("[College GPT] Empty vector store detected. Initializing inbuilt documents...")
        res = pipeline.index_all_documents()
        print(f"[College GPT] Initialized: {res['total_chunks_indexed']} chunks from {res['total_files']} files.")
except Exception as e:
    print(f"[College GPT] Startup index warning: {e}")


def is_allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS


@app.route("/")
def index():
    """Renders the College GPT Premium interface."""
    return render_template("index.html")


@app.route("/api/status", methods=["GET"])
def get_status():
    """Returns real-time status of RAG index, loaded files, and active LLM."""
    try:
        reload_env_if_needed()
        status_info = pipeline.get_status()
        return jsonify({"success": True, "data": status_info})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/chat", methods=["POST"])
def chat():
    """
    RAG Chat endpoint:
    Body: {"question": "...", "provider": "gemini"|"openai"|"groq"|"ollama"|null}
    """
    reload_env_if_needed()
    payload = request.get_json(silent=True) or request.form
    question = (payload.get("question") or payload.get("msg") or "").strip()
    provider = payload.get("provider")

    if not question:
        return jsonify({"success": False, "error": "Please enter a valid question."}), 400

    try:
        response = pipeline.query(question=question, n_results=4, provider=provider)
        if "error" in response and not response.get("answer"):
            return jsonify({
                "success": False,
                "error": response["error"]
            }), 400

        return jsonify({
            "success": True,
            "answer": response.get("answer", "I do not have information regarding the question asked in the college documents."),
            "sources": response.get("sources", []),
            "provider": response.get("provider", "College GPT"),
            "chunks_retrieved": response.get("chunks_retrieved", 0)
        })
    except Exception as e:
        print(f"[College GPT Error in /api/chat]: {e}", flush=True)
        return jsonify({
            "success": False,
            "error": f"Error generating answer: {str(e)}"
        }), 500


@app.route("/api/upload", methods=["POST"])
def upload_file():
    """
    Upload and index a PDF or Word document (.pdf, .docx, .doc).
    Immediately chunks and indexes vectors into ChromaDB.
    """
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file attached in the request."}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"success": False, "error": "No file selected."}), 400

    if not is_allowed_file(file.filename):
        return jsonify({
            "success": False,
            "error": "Invalid format! Only PDF (.pdf) and Word documents (.docx, .doc) are permitted."
        }), 400

    # Read binary content
    file_bytes = file.read()
    if len(file_bytes) == 0:
        return jsonify({
            "success": False,
            "error": "The selected file is empty (0 bytes). Please choose a valid document."
        }), 400

    import time
    orig_ext = os.path.splitext(file.filename)[1].lower()
    raw_base = os.path.splitext(file.filename)[0]
    safe_base = secure_filename(raw_base)
    if not safe_base:
        safe_base = f"doc_{int(time.time())}"
    safe_name = f"{safe_base}{orig_ext}"

    save_path = os.path.join(pipeline.uploads_dir, safe_name)
    try:
        # Write bytes cleanly
        with open(save_path, "wb") as f_out:
            f_out.write(file_bytes)

        # Clear any previous stale vectors with same filename
        pipeline.vector_store.delete_document(safe_name)

        # Immediately index newly uploaded document
        chunks_added = pipeline.index_single_file(save_path)
        if chunks_added == 0:
            if os.path.exists(save_path):
                try: os.remove(save_path)
                except Exception: pass
            return jsonify({
                "success": False,
                "error": f"No readable text could be extracted from '{safe_name}'. The file may be image-only/scanned or encrypted."
            }), 400

        return jsonify({
            "success": True,
            "filename": safe_name,
            "chunks_added": chunks_added,
            "message": f"Successfully indexed '{safe_name}' with {chunks_added} chunks into the vector store."
        })
    except Exception as e:
        # If indexing failed, remove the un-indexable file so it doesn't break future loads
        if os.path.exists(save_path):
            try: os.remove(save_path)
            except Exception: pass
        return jsonify({
            "success": False,
            "error": f"Failed to process and index document: {str(e)}"
        }), 400


@app.route("/api/delete-doc", methods=["POST"])
def delete_document():
    """Deletes an uploaded document and removes its vectors from ChromaDB."""
    payload = request.get_json(silent=True) or request.form
    filename = (payload.get("filename") or "").strip()

    if not filename:
        return jsonify({"success": False, "error": "Filename is required."}), 400

    # Inbuilt files protection (optional, can be deleted or kept)
    inbuilt_path = os.path.join(pipeline.inbuilt_dir, filename)
    if os.path.exists(inbuilt_path):
        # We allow deleting from vector store if user wants
        pass

    try:
        pipeline.remove_document(filename)
        return jsonify({
            "success": True,
            "message": f"Document '{filename}' vectors removed from College GPT knowledge base."
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/reindex", methods=["POST"])
def reindex_all():
    """Reindexes all inbuilt and uploaded documents from scratch."""
    try:
        pipeline.vector_store.reset_collection()
        res = pipeline.index_all_documents()
        return jsonify({
            "success": True,
            "message": f"Re-indexing complete. {res['total_chunks_indexed']} chunks indexed across {res['total_files']} files.",
            "data": res
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/settings", methods=["POST"])
def update_settings():
    """Updates Google AI Studio API key on the fly and syncs .env."""
    data = request.get_json(silent=True) or {}
    gemini_key = data.get("gemini_key")

    env_paths = [os.path.join(BASE_DIR, ".env"), os.path.join(PARENT_DIR, ".env")]

    for p in env_paths:
        try:
            current_env = {}
            if os.path.exists(p):
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        if "=" in line and not line.strip().startswith("#"):
                            k, v = line.strip().split("=", 1)
                            current_env[k.strip()] = v.strip()

            if gemini_key is not None:
                current_env["GEMINI_API_KEY"] = gemini_key.strip()
                os.environ["GEMINI_API_KEY"] = gemini_key.strip()

            current_env.setdefault("DEFAULT_LLM_PROVIDER", "gemini")
            current_env.setdefault("GEMINI_MODEL", "gemini-1.5-flash")
            current_env.setdefault("PORT", "8080")

            with open(p, "w", encoding="utf-8") as f:
                f.write("# Google AI Studio Configuration\n")
                for k, v in current_env.items():
                    f.write(f"{k}={v}\n")
        except Exception as e:
            print(f"Notice writing env to {p}: {e}")

    pipeline.llm_client.load_env()
    return jsonify({
        "success": True,
        "message": "Google AI Studio API Key saved successfully.",
        "active_provider": pipeline.llm_client.get_active_provider()
    })


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    print(f"[College GPT] Server starting on http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)
