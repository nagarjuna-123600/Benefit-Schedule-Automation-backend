# Benefit Schedule Automation — FastAPI + PostgreSQL + Ollama

## Features
- Upload PDF, Excel (`.xlsx`, `.xlsm`, `.xls`), Word (`.docx`), email (`.eml`, `.msg`), TXT and CSV.
- Retain the exact original uploaded bytes in PostgreSQL (`source_documents.original_file`).
- Extract benefit fields with local Ollama `llama3.2:latest`.
- Missing or unsupported field values are normalized to the string `N/A`.
- Generate embeddings using `nomic-embed-text:latest` and store vectors in PostgreSQL with pgvector.
- Link each benefit and text chunk to the source document with `document_id`.
- Expose endpoints through FastAPI Swagger UI.

## Important limitations
- Scanned/image-only PDFs need OCR; this implementation reports that no selectable text was found instead of inventing data.
- Email message files are retained in original form. The email body is parsed, but attachments embedded in an email are not separately extracted by this version.
- Legacy `.doc` Word files are not supported; use `.docx`.
- Ollama output is AI-generated and should be reviewed by an underwriter before being treated as authoritative.
- The code sends up to `MAX_TEXT_CHARS` characters to the extraction model. For very large schedules, implement multi-part extraction and merge results before production.
- PostgreSQL server must have pgvector installed. The Python `pgvector` package alone does not install the PostgreSQL server extension.

## 1. Create a PostgreSQL database
Create a database named `benefit_automation`, for example in pgAdmin or psql.
Then ensure the pgvector server extension is installed for your PostgreSQL version and run:
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```
If that command fails with `extension "vector" is not available`, install the pgvector server extension that matches your PostgreSQL installation, or use a PostgreSQL distribution/container that includes pgvector. A normal SQL query cannot install a missing server extension.

## 2. Prepare Ollama
Ensure Ollama is running, then:
```powershell
ollama pull llama3.2:latest
ollama pull nomic-embed-text:latest
ollama list
```
The embedding model is expected to return 768-dimensional vectors.

## 3. Set up Python (Windows PowerShell)
Open PowerShell in this project folder:
```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```
Edit `.env` and replace `YOUR_PASSWORD` with your PostgreSQL password. If the password contains URL-special characters, URL-encode them.

## 4. Start the backend
```powershell
python -m uvicorn main:app --reload
```
Open:
- Swagger: http://localhost:8000/docs
- Health check: http://localhost:8000/health

The first startup creates the tables. The PostgreSQL user must be allowed to create the extension (or the extension must be created by a database administrator beforehand).

## 5. Test upload in Swagger
Use `POST /api/documents/upload-and-extract` and fill:
- `client_name`
- `source_insurer`
- `assigned_underwriter`
- `file`

The endpoint uses `multipart/form-data`.

## API endpoints
- `GET /health`
- `POST /api/documents/upload-and-extract`
- `GET /api/documents/{document_id}` — metadata and extracted benefits
- `GET /api/documents/{document_id}/download-original` — download the original bytes
- `GET /api/benefits/by-document/{document_id}`
- `GET /api/search?q=annual%20dental%20maximum&limit=5`

## Tables
- `source_documents`: metadata, processing status, extracted text, and original binary file.
- `extracted_benefits`: one row per extracted benefit, linked with `document_id`.
- `document_chunks`: text chunks and vector embeddings, linked with `document_id`.

## React integration
Send `multipart/form-data` to `http://localhost:8000/api/documents/upload-and-extract`. Field names must exactly match the backend:
`client_name`, `source_insurer`, `assigned_underwriter`, and `file`.
Do not set the multipart `Content-Type` header manually in browser `fetch`; let the browser create the boundary.
