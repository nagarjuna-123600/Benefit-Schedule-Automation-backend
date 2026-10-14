from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import Response
from config import MAX_UPLOAD_MB, MAX_TEXT_CHARS
from database import (
    create_document, update_document_text, save_extraction,
    mark_document_failed, get_document, list_benefits,
)
from parsers import extract_text, SUPPORTED_EXTENSIONS
from services.extraction import extract_benefits, chunk_text, create_embeddings

router = APIRouter(prefix="/api/documents", tags=["Documents"])

@router.post("/upload-and-extract")
def upload_and_extract(
    client_name: str = Form(...),
    source_insurer: str = Form(...),
    assigned_underwriter: str = Form(...),
    file: UploadFile = File(...),
):
    filename = Path(file.filename or "uploaded_document").name
    extension = Path(filename).suffix.lower()
    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type '{extension}'. Supported: PDF, XLSX, XLSM, XLS, DOCX, EML,TXT,",
        )

    original_bytes = file.file.read()
    if not original_bytes:
        raise HTTPException(status_code=400, detail="The uploaded file is empty.")
    if len(original_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_UPLOAD_MB} MB upload limit.")

    # Save original bytes first so the source document is retained even if parsing/AI extraction fails.
    document_id = create_document(
        client_name.strip(), source_insurer.strip(), assigned_underwriter.strip(),
        filename, file.content_type, extension, original_bytes,
    )
    try:
        text = extract_text(filename, original_bytes)
        if not text.strip():
            raise ValueError("The parser did not find readable text in this document.")
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]
        update_document_text(document_id, text)

        benefits = extract_benefits(text)
        chunks = chunk_text(text)
        vectors = create_embeddings(chunks)
        save_extraction(document_id, benefits, chunks, vectors)

        return {
            "message": "Document uploaded and processed successfully",
            "document_id": document_id,
            "original_filename": filename,
            "processing_status": "completed",
            "benefit_count": len(benefits),
            "benefits": benefits,
        }
    except Exception as exc:
        mark_document_failed(document_id, str(exc))
        raise HTTPException(
            status_code=500,
            detail={
                "message": "The original document was saved, but processing failed.",
                "document_id": document_id,
                "processing_status": "failed",
                "error": str(exc),
            },
        ) from exc

@router.get("/{document_id}")
def get_document_details(document_id: int):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")
    document.pop("extracted_text", None)
    document["benefits"] = list_benefits(document_id)
    return document

@router.get("/{document_id}/download-original")
def download_original(
    document_id: int,
    inline: bool
):
    document = get_document(document_id, include_original=True)

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    original = document.pop("original_file")

    disposition = "inline" if inline else "attachment"

    return Response(
        content=bytes(original),
        media_type=(
            document.get("content_type")
            or "application/octet-stream"
        ),
        headers={
            "Content-Disposition": (
                f'{disposition}; '
                f'filename="{document["original_filename"]}"'
            )
        },
    )