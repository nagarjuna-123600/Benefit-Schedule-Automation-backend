from pathlib import Path
from io import BytesIO
from email import policy
from email.parser import BytesParser
import csv
import io

SUPPORTED_EXTENSIONS = {
    ".pdf", ".xlsx", ".xlsm", ".xls", ".docx", ".eml", ".msg", ".txt", ".csv"
}

def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")

def extract_text(filename: str, file_bytes: bytes) -> str:
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext}'. Supported types: PDF, Excel, DOCX, EML, MSG, TXT, CSV.")

    if ext == ".pdf":
        import fitz
        parts = []
        with fitz.open(stream=file_bytes, filetype="pdf") as pdf:
            for page_number, page in enumerate(pdf, start=1):
                text = page.get_text("text").strip()
                if text:
                    parts.append(f"[Page {page_number}]\n{text}")
        text = "\n\n".join(parts)
        if not text.strip():
            raise ValueError("No selectable text found in PDF. This may be a scanned PDF; OCR must be added for scanned documents.")
        return text

    if ext in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        workbook = load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
        parts = []
        for sheet in workbook.worksheets:
            parts.append(f"[Sheet: {sheet.title}]")
            for row in sheet.iter_rows(values_only=True):
                cells = [str(value).strip() if value is not None else "" for value in row]
                if any(cells):
                    parts.append(" | ".join(cells))
        workbook.close()
        return "\n".join(parts)

    if ext == ".xls":
        import xlrd
        workbook = xlrd.open_workbook(file_contents=file_bytes)
        parts = []
        for sheet in workbook.sheets():
            parts.append(f"[Sheet: {sheet.name}]")
            for row_idx in range(sheet.nrows):
                vals = [str(v).strip() if v is not None else "" for v in sheet.row_values(row_idx)]
                if any(vals):
                    parts.append(" | ".join(vals))
        return "\n".join(parts)

    if ext == ".docx":
        from docx import Document
        doc = Document(BytesIO(file_bytes))
        parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        for table_index, table in enumerate(doc.tables, start=1):
            parts.append(f"[Table {table_index}]")
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip().replace("\n", " ") for cell in row.cells))
        return "\n".join(parts)

    if ext == ".eml":
        msg = BytesParser(policy=policy.default).parsebytes(file_bytes)
        parts = [f"Subject: {msg.get('subject', '')}", f"From: {msg.get('from', '')}",
                 f"To: {msg.get('to', '')}", f"Date: {msg.get('date', '')}"]
        body = []
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_disposition() == "attachment":
                    # Original email (including attachments) is retained; attachment text parsing is separate.
                    continue
                if part.get_content_type() == "text/plain":
                    try:
                        body.append(part.get_content())
                    except Exception:
                        payload = part.get_payload(decode=True) or b""
                        body.append(_decode_bytes(payload))
            if not body:
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        from html import unescape
                        import re
                        html = part.get_content()
                        body.append(unescape(re.sub(r"<[^>]+>", " ", html)))
                        break
        else:
            try:
                body.append(msg.get_content())
            except Exception:
                body.append(_decode_bytes(msg.get_payload(decode=True) or b""))
        parts.extend(body)
        return "\n".join(p for p in parts if p)

    if ext == ".msg":
        try:
            import extract_msg
        except ImportError as exc:
            raise ValueError("For Outlook .msg files, install extract-msg (pip install extract-msg).") from exc
        with open_msg_bytes(file_bytes) as msg:
            return "\n".join([
                f"Subject: {msg.subject or ''}",
                f"From: {msg.sender or ''}",
                f"To: {msg.to or ''}",
                str(msg.body or ""),
            ])

    if ext == ".txt":
        return _decode_bytes(file_bytes)

    if ext == ".csv":
        text = _decode_bytes(file_bytes)
        reader = csv.reader(io.StringIO(text))
        return "\n".join(" | ".join(row) for row in reader)

    raise ValueError("Unsupported file type.")

# extract-msg works with paths; use a temporary file for in-memory uploads.
from contextlib import contextmanager
@contextmanager
def open_msg_bytes(data):
    import tempfile, os, extract_msg
    fd, path = tempfile.mkstemp(suffix=".msg")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        msg = extract_msg.Message(path)
        try:
            yield msg
        finally:
            msg.close()
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
