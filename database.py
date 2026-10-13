import json
import psycopg
from pgvector.psycopg import register_vector
from config import DATABASE_URL

SCHEMA_SQL = """
             CREATE \
             EXTENSION IF NOT EXISTS vector;

             CREATE TABLE IF NOT EXISTS source_documents \
             ( \
                 id \
                 BIGSERIAL \
                 PRIMARY \
                 KEY, \
                 client_name \
                 TEXT \
                 NOT \
                 NULL, \
                 source_insurer \
                 TEXT \
                 NOT \
                 NULL, \
                 assigned_underwriter \
                 TEXT \
                 NOT \
                 NULL, \
                 original_filename \
                 TEXT \
                 NOT \
                 NULL, \
                 content_type \
                 TEXT, \
                 file_extension \
                 TEXT \
                 NOT \
                 NULL, \
                 original_file \
                 BYTEA \
                 NOT \
                 NULL, \
                 file_size_bytes \
                 BIGINT \
                 NOT \
                 NULL, \
                 extracted_text \
                 TEXT, \
                 processing_status \
                 TEXT \
                 NOT \
                 NULL \
                 DEFAULT \
                 'uploaded', \
                 processing_error \
                 TEXT, \
                 created_at \
                 TIMESTAMPTZ \
                 NOT \
                 NULL \
                 DEFAULT \
                 NOW \
             ( \
             ),
                 processed_at TIMESTAMPTZ
                 );

             CREATE TABLE IF NOT EXISTS extracted_benefits \
             ( \
                 id \
                 BIGSERIAL \
                 PRIMARY \
                 KEY, \
                 document_id \
                 BIGINT \
                 NOT \
                 NULL \
                 REFERENCES \
                 source_documents \
             ( \
                 id \
             ) ON DELETE CASCADE,
                 benefit_name TEXT NOT NULL DEFAULT 'N/A',
                 benefit_category TEXT NOT NULL DEFAULT 'N/A',
                 limits TEXT NOT NULL DEFAULT 'N/A',
                 percentages TEXT NOT NULL DEFAULT 'N/A',
                 visits TEXT NOT NULL DEFAULT 'N/A',
                 deductibles TEXT NOT NULL DEFAULT 'N/A',
                 copay_ucr TEXT NOT NULL DEFAULT 'N/A',
                 benefit_treatment TEXT NOT NULL DEFAULT 'N/A',
                 other_attributes JSONB NOT NULL DEFAULT '{}'::jsonb,
                 source_excerpt TEXT NOT NULL DEFAULT 'N/A',
                 extraction_confidence TEXT NOT NULL DEFAULT 'N/A',
                 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW \
             ( \
             )
                 );

             CREATE TABLE IF NOT EXISTS document_chunks \
             ( \
                 id \
                 BIGSERIAL \
                 PRIMARY \
                 KEY, \
                 document_id \
                 BIGINT \
                 NOT \
                 NULL \
                 REFERENCES \
                 source_documents \
             ( \
                 id \
             ) ON DELETE CASCADE,
                 chunk_index INTEGER NOT NULL,
                 chunk_text TEXT NOT NULL,
                 embedding VECTOR \
             ( \
                 768 \
             ) NOT NULL,
                 created_at TIMESTAMPTZ NOT NULL DEFAULT NOW \
             ( \
             ),
                 UNIQUE \
             ( \
                 document_id, \
                 chunk_index \
             )
                 );

             CREATE INDEX IF NOT EXISTS idx_benefits_document_id ON extracted_benefits(document_id);
             CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks(document_id);
             CREATE INDEX IF NOT EXISTS idx_documents_status ON source_documents(processing_status); \
             """


def get_connection():
    conn = psycopg.connect(DATABASE_URL)
    register_vector(conn)
    return conn


def init_db():
    # The PostgreSQL server must have pgvector installed. CREATE EXTENSION requires permission.
    with psycopg.connect(DATABASE_URL) as conn:
        conn.execute(SCHEMA_SQL)
        conn.commit()
    print("Database tables are ready.")


def create_document(client_name, source_insurer, assigned_underwriter,
                    filename, content_type, extension, original_file):
    with get_connection() as conn:
        row = conn.execute(
            """
            INSERT INTO source_documents
            (client_name, source_insurer, assigned_underwriter, original_filename,
             content_type, file_extension, original_file, file_size_bytes, processing_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'uploaded') RETURNING id
            """,
            (client_name, source_insurer, assigned_underwriter, filename,
             content_type, extension, original_file, len(original_file)),
        ).fetchone()
        conn.commit()
        return row[0]


def update_document_text(document_id, extracted_text):
    with get_connection() as conn:
        conn.execute(
            "UPDATE source_documents SET extracted_text=%s, processing_status='extracting' WHERE id=%s",
            (extracted_text, document_id),
        )
        conn.commit()


def save_extraction(document_id, benefits, chunks, vectors):
    with get_connection() as conn:
        with conn.transaction():
            conn.execute("DELETE FROM extracted_benefits WHERE document_id=%s", (document_id,))
            conn.execute("DELETE FROM document_chunks WHERE document_id=%s", (document_id,))
            for item in benefits:
                conn.execute(
                    """
                    INSERT INTO extracted_benefits
                    (document_id, benefit_name, benefit_category, limits, percentages,
                     visits, deductibles, copay_ucr, benefit_treatment, other_attributes,
                     source_excerpt, extraction_confidence)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                    """,
                    (
                        document_id, item["benefit_name"], item["benefit_category"],
                        item["limits"], item["percentages"], item["visits"],
                        item["deductibles"], item["copay_ucr"], item["benefit_treatment"],
                        json.dumps(item["other_attributes"], ensure_ascii=False),
                        item["source_excerpt"], item["extraction_confidence"],
                    ),
                )
            for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
                conn.execute(
                    "INSERT INTO document_chunks (document_id, chunk_index, chunk_text, embedding) VALUES (%s,%s,%s,%s)",
                    (document_id, i, chunk, vector),
                )
            conn.execute(
                "UPDATE source_documents SET processing_status='completed', processing_error=NULL, processed_at=NOW() WHERE id=%s",
                (document_id,),
            )


def mark_document_failed(document_id, error):
    with get_connection() as conn:
        conn.execute(
            "UPDATE source_documents SET processing_status='failed', processing_error=%s WHERE id=%s",
            (str(error)[:4000], document_id),
        )
        conn.commit()


def get_document(document_id, include_original=False):
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, client_name, source_insurer, assigned_underwriter,
                   original_filename, content_type, file_extension, file_size_bytes,
                   extracted_text, processing_status, processing_error, created_at, processed_at
                   {original}
            FROM source_documents WHERE id=%s
            """.format(original=", original_file" if include_original else ""),
            (document_id,),
        ).fetchone()
        if not row:
            return None
        keys = ["id", "client_name", "source_insurer", "assigned_underwriter",
                "original_filename", "content_type", "file_extension", "file_size_bytes",
                "extracted_text", "processing_status", "processing_error", "created_at", "processed_at"]
        if include_original:
            keys.append("original_file")
        result = dict(zip(keys, row))
        result["created_at"] = result["created_at"].isoformat() if result["created_at"] else None
        result["processed_at"] = result["processed_at"].isoformat() if result["processed_at"] else None
        return result


def list_benefits(document_id):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id,
                   document_id,
                   benefit_name,
                   benefit_category,
                   limits,
                   percentages,
                   visits,
                   deductibles,
                   copay_ucr,
                   benefit_treatment,
                   other_attributes,
                   source_excerpt,
                   extraction_confidence,
                   created_at
            FROM extracted_benefits
            WHERE document_id = %s
            ORDER BY id
            """,
            (document_id,),
        ).fetchall()
        cols = ["id", "document_id", "benefit_name", "benefit_category", "limits",
                "percentages", "visits", "deductibles", "copay_ucr", "benefit_treatment",
                "other_attributes", "source_excerpt", "extraction_confidence", "created_at"]
        result = []
        for row in rows:
            item = dict(zip(cols, row))
            item["created_at"] = item["created_at"].isoformat() if item["created_at"] else None
            result.append(item)
        return result


def search_chunks(vector, limit=5):
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT dc.document_id,
                   sd.original_filename,
                   dc.chunk_text,
                   (dc.embedding <=> %s) AS distance
            FROM document_chunks dc
                     JOIN source_documents sd ON sd.id = dc.document_id
            ORDER BY dc.embedding <=> %s
                LIMIT %s
            """,
            (vector, vector, limit),
        ).fetchall()
        return [
            {"document_id": r[0], "original_filename": r[1],
             "chunk_text": r[2], "distance": float(r[3])}
            for r in rows
        ]
