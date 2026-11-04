"""
Document Processor for College GPT
Extracts and chunks text from PDF and Word (.docx/.doc) files.
"""

import os
import re
import hashlib
from typing import List, Dict, Any

try:
    import pypdf
except ImportError:
    pypdf = None

try:
    import docx
except ImportError:
    docx = None


def extract_text_from_pdf(file_path: str) -> List[Dict[str, Any]]:
    """
    Extracts text from each page of a PDF file.
    Returns a list of dicts: [{'text': page_text, 'page': page_num, 'source': filename, 'type': 'pdf'}]
    """
    if not pypdf:
        raise ImportError("pypdf is required to process PDF files. Please install pypdf.")

    filename = os.path.basename(file_path)

    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        raise ValueError(f"File '{filename}' is empty (0 bytes). Please select a valid PDF.")

    pages_data = []

    try:
        with open(file_path, "rb") as f:
            reader = pypdf.PdfReader(f)
            total_pages = len(reader.pages)
            if total_pages == 0:
                raise ValueError(f"The PDF '{filename}' contains 0 pages.")

            for i, page in enumerate(reader.pages):
                try:
                    text = page.extract_text() or ""
                except Exception:
                    text = ""
                # Clean up extra whitespace and control chars
                text = re.sub(r"[ \t]+", " ", text).strip()
                if text:
                    pages_data.append({
                        "text": text,
                        "page": i + 1,
                        "total_pages": total_pages,
                        "source": filename,
                        "doc_type": "pdf",
                        "file_path": file_path
                    })
    except ValueError as ve:
        raise ve
    except Exception as e:
        raise ValueError(f"Failed to read PDF '{filename}': {str(e)}")

    if not pages_data:
        raise ValueError(
            f"No readable text could be extracted from '{filename}'. "
            f"If this is a scanned/image-only PDF, please upload a text-based PDF or Word document."
        )

    return pages_data


def extract_text_from_docx(file_path: str) -> List[Dict[str, Any]]:
    """
    Extracts text from Word documents (.docx).
    Groups paragraphs into logical sections/pages.
    """
    if not docx:
        raise ImportError("python-docx is required to process Word documents. Please install python-docx.")

    filename = os.path.basename(file_path)

    if not os.path.exists(file_path) or os.path.getsize(file_path) == 0:
        raise ValueError(f"File '{filename}' is empty (0 bytes). Please select a valid document.")

    try:
        doc = docx.Document(file_path)
    except Exception as e:
        raise ValueError(
            f"Could not open Word document '{filename}': {str(e)}. "
            f"Please make sure it is a valid .docx file (or export from Google Docs/Word as .docx or .pdf)."
        )

    sections_data = []
    current_section = []
    word_count = 0
    section_num = 1

    # Extract paragraphs and table cells
    all_elements = []
    for p in doc.paragraphs:
        txt = p.text.strip()
        if txt:
            all_elements.append(txt)

    for table in doc.tables:
        for row in table.rows:
            row_txt = " | ".join([cell.text.strip() for cell in row.cells if cell.text.strip()])
            if row_txt:
                all_elements.append(row_txt)

    if not all_elements:
        raise ValueError(f"The Word document '{filename}' has no text content.")

    for text_block in all_elements:
        current_section.append(text_block)
        words = len(text_block.split())
        word_count += words

        # Split into pseudo-pages / sections of roughly 350-450 words
        if word_count >= 350:
            combined = "\n\n".join(current_section).strip()
            if combined:
                sections_data.append({
                    "text": combined,
                    "page": section_num,
                    "total_pages": None,
                    "source": filename,
                    "doc_type": "docx",
                    "file_path": file_path
                })
                section_num += 1
            current_section = []
            word_count = 0

    if current_section:
        combined = "\n\n".join(current_section).strip()
        if combined:
            sections_data.append({
                "text": combined,
                "page": section_num,
                "total_pages": section_num,
                "source": filename,
                "doc_type": "docx",
                "file_path": file_path
            })

    return sections_data


def extract_document(file_path: str) -> List[Dict[str, Any]]:
    """
    Auto-detects document format (PDF or Word) and extracts text segments.
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return extract_text_from_pdf(file_path)
    elif ext in [".docx", ".doc"]:
        return extract_text_from_docx(file_path)
    else:
        raise ValueError(f"Unsupported format: {ext}. Only PDF (.pdf) and Word (.docx, .doc) files are allowed.")


def chunk_text(
    pages_data: List[Dict[str, Any]],
    chunk_size: int = 700,
    chunk_overlap: int = 120
) -> List[Dict[str, Any]]:
    """
    Splits document pages/sections into overlapping semantic chunks.
    Ensures 100% unique IDs with MD5 hash to prevent any ChromaDB collision.
    """
    chunks = []

    for item in pages_data:
        text = item["text"]
        source = item["source"]
        page = item.get("page", 1)
        doc_type = item.get("doc_type", "pdf")
        clean_source = re.sub(r"[^a-zA-Z0-9_\-\.]", "_", source)

        if len(text) <= chunk_size:
            chunk_hash = hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()[:6]
            chunks.append({
                "id": f"{clean_source}_p{page}_c0_{chunk_hash}",
                "text": text,
                "metadata": {
                    "source": source,
                    "page": page,
                    "doc_type": doc_type,
                    "chunk_idx": 0,
                    "length": len(text)
                }
            })
            continue

        # Split by paragraphs or sentence boundaries
        start = 0
        local_c_idx = 0
        while start < len(text):
            end = start + chunk_size
            if end >= len(text):
                chunk_slice = text[start:].strip()
                if chunk_slice:
                    chunk_hash = hashlib.md5(chunk_slice.encode("utf-8", errors="ignore")).hexdigest()[:6]
                    chunks.append({
                        "id": f"{clean_source}_p{page}_c{local_c_idx}_{chunk_hash}",
                        "text": chunk_slice,
                        "metadata": {
                            "source": source,
                            "page": page,
                            "doc_type": doc_type,
                            "chunk_idx": local_c_idx,
                            "length": len(chunk_slice)
                        }
                    })
                break

            # Find natural break point near 'end'
            cut = text.rfind("\n\n", start, end)
            if cut == -1 or cut <= start:
                cut = text.rfind("\n", start, end)
            if cut == -1 or cut <= start:
                cut = text.rfind(". ", start, end)
                if cut != -1:
                    cut += 1
            if cut == -1 or cut <= start:
                cut = text.rfind(" ", start, end)
            if cut == -1 or cut <= start:
                cut = end

            chunk_slice = text[start:cut].strip()
            if chunk_slice:
                chunk_hash = hashlib.md5(chunk_slice.encode("utf-8", errors="ignore")).hexdigest()[:6]
                chunks.append({
                    "id": f"{clean_source}_p{page}_c{local_c_idx}_{chunk_hash}",
                    "text": chunk_slice,
                    "metadata": {
                        "source": source,
                        "page": page,
                        "doc_type": doc_type,
                        "chunk_idx": local_c_idx,
                        "length": len(chunk_slice)
                    }
                })
                local_c_idx += 1

            start = max(start + 1, cut - chunk_overlap)

    return chunks
