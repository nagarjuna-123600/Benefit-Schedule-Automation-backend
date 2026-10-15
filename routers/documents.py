
from pathlib import Path
from urllib.parse import quote

from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Form,
    HTTPException,
)
from fastapi.responses import Response

from config import MAX_UPLOAD_MB, MAX_TEXT_CHARS

from database import (
    DuplicateProjectError,
    create_document,
    update_document_text,
    save_extraction,
    mark_document_failed,
    get_document,
    list_benefits,
    get_connection,
    list_projects,
    get_project,
)

from parsers import extract_text, SUPPORTED_EXTENSIONS

from services.extraction import (
    extract_benefits,
    chunk_text,
    create_embeddings,
)


router = APIRouter(
    prefix="/api/documents",
    tags=["Documents"],
)

projects_router = APIRouter(
    prefix="/api/projects",
    tags=["Projects"],
)


# =====================================================
# SHARED VALIDATION
# =====================================================

def validate_project_details(
    client_name,
    source_insurer,
    assigned_underwriter,
):
    values = (
        client_name.strip(),
        source_insurer.strip(),
        assigned_underwriter.strip(),
    )

    if not all(values):
        raise HTTPException(
            status_code=422,
            detail="All project details are required.",
        )

    return values


def read_uploaded_file(file):
    filename = Path(
        file.filename or "uploaded_document"
    ).name

    extension = Path(filename).suffix.lower()

    if extension not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=415,
            detail=(
                f"Unsupported file type '{extension}'. "
                f"Supported formats: "
                f"{', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            ),
        )

    original_bytes = file.file.read()

    if not original_bytes:
        raise HTTPException(
            status_code=400,
            detail="The uploaded file is empty.",
        )

    if len(original_bytes) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File exceeds the "
                f"{MAX_UPLOAD_MB} MB upload limit."
            ),
        )

    return filename, extension, original_bytes


# =====================================================
# SHARED DOCUMENT EXTRACTION
# =====================================================

def process_document(document_id, filename, original_bytes):
    try:
        text = extract_text(
            filename,
            original_bytes,
        )

        if not text.strip():
            raise ValueError(
                "The parser did not find readable text."
            )

        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS]

        update_document_text(
            document_id,
            text,
        )

        benefits = extract_benefits(text)

        chunks = chunk_text(text)

        vectors = create_embeddings(chunks)

        save_extraction(
            document_id,
            benefits,
            chunks,
            vectors,
        )

        document = get_document(document_id)

        return {
            "message": "Document processed successfully.",
            "document_id": document_id,
            "project_id": document["project_id"],
            "version_number": document["version_number"],
            "original_filename": filename,
            "processing_status": "completed",
            "benefit_count": len(benefits),
            "benefits": benefits,
        }

    except Exception as exc:
        mark_document_failed(
            document_id,
            str(exc),
        )

        raise HTTPException(
            status_code=500,
            detail={
                "message": (
                    "Original document was saved, "
                    "but processing failed. "
                    "The previous active version is unchanged."
                ),
                "document_id": document_id,
                "processing_status": "failed",
                "error": str(exc),
            },
        ) from exc


# =====================================================
# 1. CREATE NEW PROJECT WITH VERSION 1
# =====================================================

@router.post("/upload-and-extract")
def upload_and_extract(
    client_name: str = Form(...),
    source_insurer: str = Form(...),
    assigned_underwriter: str = Form(...),
    file: UploadFile = File(...),
):
    (
        client_name,
        source_insurer,
        assigned_underwriter,
    ) = validate_project_details(
        client_name,
        source_insurer,
        assigned_underwriter,
    )

    filename, extension, original_bytes = (
        read_uploaded_file(file)
    )

    try:
        document_id = create_document(
            client_name,
            source_insurer,
            assigned_underwriter,
            filename,
            file.content_type,
            extension,
            original_bytes,
        )

    except DuplicateProjectError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "message": (
                    "A project already exists for "
                    "this client and source insurer. "
                    "Reopen the existing project to "
                    "upload a new version."
                ),
                "project_id": exc.project_id,
            },
        ) from exc

    return process_document(
        document_id,
        filename,
        original_bytes,
    )


# =====================================================
# 2. GET ALL UNIQUE PROJECTS
# =====================================================

@projects_router.get("")
def get_all_projects():
    projects = list_projects()

    return {
        "total": len(projects),
        "projects": projects,
    }


# =====================================================
# 3. REOPEN EXISTING PROJECT / VERSION HISTORY
# =====================================================

@projects_router.get("/{project_id}")
def get_project_details(project_id: int):
    project = get_project(project_id)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found.",
        )

    return project


# =====================================================
# 4. UPLOAD NEW VERSION TO EXISTING PROJECT
# =====================================================

@projects_router.post("/{project_id}/documents")
def upload_new_version(
    project_id: int,
    file: UploadFile = File(...),
    assigned_underwriter: str | None = Form(None),
):
    project = get_project(project_id)

    if not project:
        raise HTTPException(
            status_code=404,
            detail="Project not found.",
        )

    filename, extension, original_bytes = (
        read_uploaded_file(file)
    )

    underwriter = (
        assigned_underwriter.strip()
        if assigned_underwriter
        else project["assigned_underwriter"]
    )

    try:
        document_id = create_document(
            project["client_name"],
            project["source_insurer"],
            underwriter,
            filename,
            file.content_type,
            extension,
            original_bytes,
            project_id=project_id,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    return process_document(
        document_id,
        filename,
        original_bytes,
    )


# =====================================================
# 5. FETCH ALL DOCUMENT VERSIONS
# =====================================================

@router.get("")
def list_all_documents():
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                project_id,
                version_number,
                client_name,
                source_insurer,
                assigned_underwriter,
                original_filename,
                file_extension,
                file_size_bytes,
                processing_status,
                processing_error,
                created_at,
                processed_at
            FROM source_documents
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()

    columns = [
        "id",
        "project_id",
        "version_number",
        "client_name",
        "source_insurer",
        "assigned_underwriter",
        "original_filename",
        "file_extension",
        "file_size_bytes",
        "processing_status",
        "processing_error",
        "created_at",
        "processed_at",
    ]

    documents = []

    for row in rows:
        document = dict(zip(columns, row))

        for field in ("created_at", "processed_at"):
            if document[field]:
                document[field] = (
                    document[field].isoformat()
                )

        documents.append(document)

    return {
        "total": len(documents),
        "documents": documents,
    }


# =====================================================
# 6. FETCH DOCUMENT DETAILS AND BENEFITS
# =====================================================

@router.get("/{document_id}")
def get_document_details(document_id: int):
    document = get_document(document_id)

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    document.pop("extracted_text", None)

    document["benefits"] = list_benefits(
        document_id
    )

    return document


# =====================================================
# 7. PREVIEW OR DOWNLOAD ORIGINAL DOCUMENT
# =====================================================

@router.get("/{document_id}/download-original")
def download_original(
    document_id: int,
    inline: bool = False,
):
    document = get_document(
        document_id,
        include_original=True,
    )

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    original = document.pop("original_file")

    filename = document["original_filename"]

    extension = document["file_extension"].lower()

    mime_types = {
        ".pdf": "application/pdf",
        ".xlsx": (
            "application/vnd.openxmlformats-"
            "officedocument.spreadsheetml.sheet"
        ),
        ".xls": "application/vnd.ms-excel",
        ".xlsm": (
            "application/vnd.ms-excel."
            "sheet.macroEnabled.12"
        ),
        ".docx": (
            "application/vnd.openxmlformats-"
            "officedocument.wordprocessingml.document"
        ),
        ".txt": "text/plain",
        ".eml": "message/rfc822",
    }

    media_type = mime_types.get(
        extension,
        document.get("content_type")
        or "application/octet-stream",
    )

    disposition = (
        "inline"
        if inline and extension == ".pdf"
        else "attachment"
    )

    encoded_filename = quote(
        filename,
        safe="",
    )

    return Response(
        content=bytes(original),
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f"{disposition}; "
                f"filename*=UTF-8''{encoded_filename}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
