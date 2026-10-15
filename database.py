
import json

import psycopg
from psycopg.rows import dict_row
from pgvector.psycopg import register_vector

from config import DATABASE_URL


# =====================================================
# 1. DATABASE SCHEMA
# =====================================================

SCHEMA_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS source_documents (
    id BIGSERIAL PRIMARY KEY,
    client_name TEXT NOT NULL,
    source_insurer TEXT NOT NULL,
    assigned_underwriter TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    content_type TEXT,
    file_extension TEXT NOT NULL,
    original_file BYTEA NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    extracted_text TEXT,
    processing_status TEXT NOT NULL DEFAULT 'uploaded',
    processing_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS extracted_benefits (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL
        REFERENCES source_documents(id)
        ON DELETE CASCADE,
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
    validation_status TEXT NOT NULL DEFAULT 'Unverified',
    validation_reason TEXT NOT NULL DEFAULT '',
    resolution_action TEXT,
    resolution_notes TEXT,
    resolved_by TEXT,
    resolved_at TIMESTAMPTZ,
    mapped_to_benefit TEXT,
    added_by TEXT,
    is_manually_added BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Add columns to existing installations without deleting existing data.
ALTER TABLE extracted_benefits ADD COLUMN IF NOT EXISTS validation_status TEXT NOT NULL DEFAULT 'Unverified';
ALTER TABLE extracted_benefits ADD COLUMN IF NOT EXISTS validation_reason TEXT NOT NULL DEFAULT '';
ALTER TABLE extracted_benefits ADD COLUMN IF NOT EXISTS resolution_action TEXT;
ALTER TABLE extracted_benefits ADD COLUMN IF NOT EXISTS resolution_notes TEXT;
ALTER TABLE extracted_benefits ADD COLUMN IF NOT EXISTS resolved_by TEXT;
ALTER TABLE extracted_benefits ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ;
ALTER TABLE extracted_benefits ADD COLUMN IF NOT EXISTS mapped_to_benefit TEXT;
ALTER TABLE extracted_benefits ADD COLUMN IF NOT EXISTS added_by TEXT;
ALTER TABLE extracted_benefits ADD COLUMN IF NOT EXISTS is_manually_added BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS document_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL
        REFERENCES source_documents(id)
        ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(768) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS projects (
    id BIGSERIAL PRIMARY KEY,
    client_name TEXT NOT NULL,
    source_insurer TEXT NOT NULL,
    assigned_underwriter TEXT NOT NULL,
    active_document_id BIGINT
        REFERENCES source_documents(id)
        ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE source_documents
ADD COLUMN IF NOT EXISTS project_id BIGINT
REFERENCES projects(id);

ALTER TABLE source_documents
ADD COLUMN IF NOT EXISTS version_number INTEGER;

CREATE UNIQUE INDEX IF NOT EXISTS
uq_projects_client_insurer
ON projects (
    LOWER(BTRIM(client_name)),
    LOWER(BTRIM(source_insurer))
);

CREATE UNIQUE INDEX IF NOT EXISTS
uq_document_project_version
ON source_documents (
    project_id,
    version_number
);

CREATE INDEX IF NOT EXISTS
idx_documents_project_id
ON source_documents(project_id);

CREATE INDEX IF NOT EXISTS
idx_benefits_document_id
ON extracted_benefits(document_id);

CREATE INDEX IF NOT EXISTS
idx_chunks_document_id
ON document_chunks(document_id);

CREATE INDEX IF NOT EXISTS
idx_documents_status
ON source_documents(processing_status);
"""


# =====================================================
# 2. CUSTOM EXCEPTIONS
# =====================================================

class DuplicateProjectError(ValueError):

    def __init__(self, project_id):
        self.project_id = project_id

        super().__init__(
            f"Project BEN-{project_id} already exists "
            "for this client and insurer. "
            "Reopen it to upload a new version."
        )


# =====================================================
# 3. DATABASE CONNECTION
# =====================================================

def get_connection():
    conn = psycopg.connect(DATABASE_URL)
    register_vector(conn)
    return conn


# =====================================================
# 4. HELPERS
# =====================================================

def serialize_dates(item):
    for key in (
        "created_at",
        "updated_at",
        "processed_at",
    ):
        if key in item and item[key] is not None:
            item[key] = item[key].isoformat()

    return item


def normalize_name(value):
    return " ".join(str(value or "").split())


def find_project(conn, client_name, source_insurer):
    return conn.execute(
        """
        SELECT id
        FROM projects
        WHERE LOWER(BTRIM(client_name)) =
              LOWER(BTRIM(%s))
          AND LOWER(BTRIM(source_insurer)) =
              LOWER(BTRIM(%s))
        LIMIT 1
        """,
        (client_name, source_insurer),
    ).fetchone()


# =====================================================
# 5. INITIALIZE DATABASE AND MIGRATE OLD DOCUMENTS
# =====================================================

def init_db():

    with psycopg.connect(DATABASE_URL) as conn:

        # Prevent concurrent initialization from
        # assigning conflicting version numbers.
        conn.execute(
            "SELECT pg_advisory_xact_lock(912345678)"
        )

        conn.execute(SCHEMA_SQL)

        # Find existing documents without a project.
        old_documents = conn.execute(
            """
            SELECT
                id,
                client_name,
                source_insurer,
                assigned_underwriter,
                processing_status,
                created_at
            FROM source_documents
            WHERE project_id IS NULL
            ORDER BY created_at ASC, id ASC
            """
        ).fetchall()

        for row in old_documents:

            (
                document_id,
                client_name,
                source_insurer,
                assigned_underwriter,
                processing_status,
                created_at,
            ) = row

            client_name = normalize_name(client_name)
            source_insurer = normalize_name(source_insurer)

            project_row = find_project(
                conn,
                client_name,
                source_insurer,
            )

            if project_row:
                project_id = project_row[0]

            else:
                project_id = conn.execute(
                    """
<<<<<<< HEAD
                    INSERT INTO extracted_benefits
                    (document_id, benefit_name, benefit_category, limits, percentages,
                     visits, deductibles, copay_ucr, benefit_treatment, other_attributes,
                     source_excerpt, extraction_confidence, validation_status,
                     validation_reason, added_by, is_manually_added)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,'Unverified','',NULL,FALSE)
                    """,
                    (
                        document_id, item.get("benefit_name", "N/A"), item.get("benefit_category", "N/A"),
                        item.get("limits", "N/A"), item.get("percentages", "N/A"),
                        item.get("visits", "N/A"), item.get("deductibles", "N/A"),
                        item.get("copay_ucr", "N/A"), item.get("benefit_treatment", "N/A"),
                        json.dumps(item.get("other_attributes") or {}, ensure_ascii=False),
                        item.get("source_excerpt", "N/A"), item.get("extraction_confidence", "N/A"),
=======
                    INSERT INTO projects (
                        client_name,
                        source_insurer,
                        assigned_underwriter,
                        created_at,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        client_name,
                        source_insurer,
                        assigned_underwriter,
                        created_at,
                        created_at,
>>>>>>> origin/dev
                    ),
                ).fetchone()[0]

            next_version = conn.execute(
                """
                SELECT COALESCE(
                    MAX(version_number), 0
                ) + 1
                FROM source_documents
                WHERE project_id = %s
                """,
                (project_id,),
            ).fetchone()[0]

            conn.execute(
                """
                UPDATE source_documents
                SET
                    project_id = %s,
                    version_number = %s
                WHERE id = %s
                """,
                (
                    project_id,
                    next_version,
                    document_id,
                ),
            )

        # Repair version numbers if an earlier
        # migration left any of them unassigned.
        missing_versions = conn.execute(
            """
            SELECT id, project_id
            FROM source_documents
            WHERE project_id IS NOT NULL
              AND version_number IS NULL
            ORDER BY project_id, created_at, id
            """
        ).fetchall()

        for document_id, project_id in missing_versions:

            next_version = conn.execute(
                """
                SELECT COALESCE(
                    MAX(version_number), 0
                ) + 1
                FROM source_documents
                WHERE project_id = %s
                """,
                (project_id,),
            ).fetchone()[0]

            conn.execute(
                """
                UPDATE source_documents
                SET version_number = %s
                WHERE id = %s
                """,
                (
                    next_version,
                    document_id,
                ),
            )

        # Set the active document to the latest
        # successfully completed version.
        #
        # Existing active versions are preserved
        # if they are still valid.
        conn.execute(
            """
            UPDATE projects p
            SET active_document_id = (
                SELECT sd.id
                FROM source_documents sd
                WHERE sd.project_id = p.id
                  AND sd.processing_status = 'completed'
                ORDER BY
                    sd.version_number DESC,
                    sd.id DESC
                LIMIT 1
            )
            WHERE p.active_document_id IS NULL
            """
        )

        conn.commit()

    print(
        "CANOPY database tables and "
        "project versioning are ready."
    )


# =====================================================
# 6. CREATE PROJECT
# =====================================================

def create_project(
    client_name,
    source_insurer,
    assigned_underwriter,
):

    client_name = normalize_name(client_name)
    source_insurer = normalize_name(source_insurer)
    assigned_underwriter = normalize_name(
        assigned_underwriter
    )

    if not all((
        client_name,
        source_insurer,
        assigned_underwriter,
    )):
        raise ValueError(
            "All project details are required."
        )

    with get_connection() as conn:

        # Serialize project creation so concurrent
        # requests cannot create duplicate projects.
        conn.execute(
            "SELECT pg_advisory_xact_lock(912345679)"
        )

        existing = find_project(
            conn,
            client_name,
            source_insurer,
        )

        if existing:
            raise DuplicateProjectError(existing[0])

        project_id = conn.execute(
            """
            INSERT INTO projects (
                client_name,
                source_insurer,
                assigned_underwriter
            )
            VALUES (%s, %s, %s)
            RETURNING id
            """,
            (
                client_name,
                source_insurer,
                assigned_underwriter,
            ),
        ).fetchone()[0]

        conn.commit()

        return project_id


# =====================================================
# 7. CREATE DOCUMENT / CREATE NEW VERSION
# =====================================================

def create_document(
    client_name,
    source_insurer,
    assigned_underwriter,
    filename,
    content_type,
    extension,
    original_file,
    project_id=None,
):

    client_name = normalize_name(client_name)
    source_insurer = normalize_name(source_insurer)
    assigned_underwriter = normalize_name(
        assigned_underwriter
    )

    with get_connection() as conn:

        conn.execute(
            "SELECT pg_advisory_xact_lock(912345679)"
        )

        if project_id is None:

            # New project + Version 1.
            # Duplicate projects are not allowed.
            existing = find_project(
                conn,
                client_name,
                source_insurer,
            )

            if existing:
                raise DuplicateProjectError(
                    existing[0]
                )

            project_id = conn.execute(
                """
                INSERT INTO projects (
                    client_name,
                    source_insurer,
                    assigned_underwriter
                )
                VALUES (%s, %s, %s)
                RETURNING id
                """,
                (
                    client_name,
                    source_insurer,
                    assigned_underwriter,
                ),
            ).fetchone()[0]

            version_number = 1

        else:

            # Existing project + next version.
            project = conn.execute(
                """
                SELECT
                    id,
                    client_name,
                    source_insurer
                FROM projects
                WHERE id = %s
                FOR UPDATE
                """,
                (project_id,),
            ).fetchone()

            if not project:
                raise ValueError(
                    "Project not found."
                )

            # Use the project's canonical names.
            client_name = project[1]
            source_insurer = project[2]

            version_number = conn.execute(
                """
                SELECT COALESCE(
                    MAX(version_number), 0
                ) + 1
                FROM source_documents
                WHERE project_id = %s
                """,
                (project_id,),
            ).fetchone()[0]

        document_id = conn.execute(
            """
            INSERT INTO source_documents (
                project_id,
                version_number,
                client_name,
                source_insurer,
                assigned_underwriter,
                original_filename,
                content_type,
                file_extension,
                original_file,
                file_size_bytes,
                processing_status
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                'uploaded'
            )
            RETURNING id
            """,
            (
                project_id,
                version_number,
                client_name,
                source_insurer,
                assigned_underwriter,
                filename,
                content_type,
                extension,
                original_file,
                len(original_file),
            ),
        ).fetchone()[0]

        conn.execute(
            """
            UPDATE projects
            SET
                assigned_underwriter = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                assigned_underwriter,
                project_id,
            ),
        )

        conn.commit()

        return document_id


# =====================================================
# 8. UPDATE EXTRACTED DOCUMENT TEXT
# =====================================================

def update_document_text(
    document_id,
    extracted_text,
):

    with get_connection() as conn:

        conn.execute(
            """
            UPDATE source_documents
            SET
                extracted_text = %s,
                processing_status = 'extracting'
            WHERE id = %s
            """,
            (
                extracted_text,
                document_id,
            ),
        )

        conn.commit()


# =====================================================
# 9. SAVE BENEFITS, CHUNKS AND EMBEDDINGS
# =====================================================

def save_extraction(
    document_id,
    benefits,
    chunks,
    vectors,
):

    if len(chunks) != len(vectors):
        raise ValueError(
            "Chunk and embedding counts do not match."
        )

    with get_connection() as conn:

        with conn.transaction():

            # Lock the document and its project.
            document = conn.execute(
                """
                SELECT project_id, version_number
                FROM source_documents
                WHERE id = %s
                FOR UPDATE
                """,
                (document_id,),
            ).fetchone()

            if not document:
                raise ValueError(
                    "Document not found."
                )

            project_id, version_number = document

            conn.execute(
                """
                DELETE FROM extracted_benefits
                WHERE document_id = %s
                """,
                (document_id,),
            )

            conn.execute(
                """
                DELETE FROM document_chunks
                WHERE document_id = %s
                """,
                (document_id,),
            )

            for item in benefits:

                conn.execute(
                    """
                    INSERT INTO extracted_benefits (
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
                        extraction_confidence
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s::jsonb,
                        %s, %s
                    )
                    """,
                    (
                        document_id,
                        item.get(
                            "benefit_name", "N/A"
                        ),
                        item.get(
                            "benefit_category", "N/A"
                        ),
                        item.get("limits", "N/A"),
                        item.get("percentages", "N/A"),
                        item.get("visits", "N/A"),
                        item.get("deductibles", "N/A"),
                        item.get("copay_ucr", "N/A"),
                        item.get(
                            "benefit_treatment", "N/A"
                        ),
                        json.dumps(
                            item.get(
                                "other_attributes", {}
                            ),
                            ensure_ascii=False,
                        ),
                        item.get(
                            "source_excerpt", "N/A"
                        ),
                        item.get(
                            "extraction_confidence", "N/A"
                        ),
                    ),
                )

            for index, (chunk, vector) in enumerate(
                zip(chunks, vectors)
            ):

                conn.execute(
                    """
                    INSERT INTO document_chunks (
                        document_id,
                        chunk_index,
                        chunk_text,
                        embedding
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        document_id,
                        index,
                        chunk,
                        vector,
                    ),
                )

            conn.execute(
                """
                UPDATE source_documents
                SET
                    processing_status = 'completed',
                    processing_error = NULL,
                    processed_at = NOW()
                WHERE id = %s
                """,
                (document_id,),
            )

            # Activate the newly completed version
            # only if no newer successful version
            # is already active.
            if project_id is not None:

                conn.execute(
                    """
                    UPDATE projects p
                    SET
                        active_document_id = %s,
                        updated_at = NOW()
                    WHERE p.id = %s
                      AND (
                          p.active_document_id IS NULL
                          OR NOT EXISTS (
                              SELECT 1
                              FROM source_documents active
                              WHERE active.id =
                                    p.active_document_id
                                AND active.project_id = p.id
                                AND active.processing_status =
                                    'completed'
                                AND active.version_number > %s
                          )
                      )
                    """,
                    (
                        document_id,
                        project_id,
                        version_number,
                    ),
                )


# =====================================================
# 10. MARK DOCUMENT PROCESSING AS FAILED
# =====================================================

def mark_document_failed(
    document_id,
    error,
):

    with get_connection() as conn:

        conn.execute(
            """
            UPDATE source_documents
            SET
                processing_status = 'failed',
                processing_error = %s
            WHERE id = %s
            """,
            (
                str(error)[:4000],
                document_id,
            ),
        )

        conn.commit()

    # Do not change the active document.
    # The previous successful version remains active.


# =====================================================
# 11. GET DOCUMENT DETAILS
# =====================================================

def get_document(
    document_id,
    include_original=False,
):

    with get_connection() as conn:

        conn.row_factory = dict_row

        columns = """
            id,
            project_id,
            version_number,
            client_name,
            source_insurer,
            assigned_underwriter,
            original_filename,
            content_type,
            file_extension,
            file_size_bytes,
            extracted_text,
            processing_status,
            processing_error,
            created_at,
            processed_at
        """

        if include_original:
            columns += ", original_file"

        # The selected columns are defined internally,
        # not supplied by the user.
        row = conn.execute(
            f"""
            SELECT {columns}
            FROM source_documents
            WHERE id = %s
            """,
            (document_id,),
        ).fetchone()

        if not row:
            return None

        return serialize_dates(dict(row))


# =====================================================
# 12. LIST EXTRACTED BENEFITS
# =====================================================

def list_benefits(document_id):

    with get_connection() as conn:

        conn.row_factory = dict_row

        rows = conn.execute(
            """
<<<<<<< HEAD
            SELECT id, document_id, benefit_name, benefit_category, limits, percentages,
                   visits, deductibles, copay_ucr, benefit_treatment, other_attributes,
                   source_excerpt, extraction_confidence, validation_status,
                   validation_reason, resolution_action, resolution_notes, resolved_by,
                   resolved_at, mapped_to_benefit, added_by, is_manually_added, created_at
            FROM extracted_benefits
            WHERE document_id=%s
=======
            SELECT
                id,
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
>>>>>>> origin/dev
            ORDER BY id
            """,
            (document_id,),
        ).fetchall()
<<<<<<< HEAD
        cols = ["id", "document_id", "benefit_name", "benefit_category", "limits",
                "percentages", "visits", "deductibles", "copay_ucr", "benefit_treatment",
                "other_attributes", "source_excerpt", "extraction_confidence",
                "validation_status", "validation_reason", "resolution_action",
                "resolution_notes", "resolved_by", "resolved_at", "mapped_to_benefit",
                "added_by", "is_manually_added", "created_at"]
        result = []
        for row in rows:
            item = dict(zip(cols, row))
            for date_field in ("created_at", "resolved_at"):
                if item[date_field]:
                    item[date_field] = item[date_field].isoformat()
            result.append(item)
        return result
=======
>>>>>>> origin/dev

        return [
            serialize_dates(dict(row))
            for row in rows
        ]


# =====================================================
# 13. LIST ALL PROJECTS
# =====================================================

def list_projects():

    with get_connection() as conn:

        conn.row_factory = dict_row

        rows = conn.execute(
            """
            SELECT
                p.id,
                p.client_name,
                p.source_insurer,
                p.assigned_underwriter,
                p.active_document_id,
                p.created_at,
                p.updated_at,

                active.version_number
                    AS active_version_number,

                active.original_filename,
                active.file_extension,
                active.file_size_bytes,
                active.processing_status,

                latest.id AS latest_document_id,
                latest.version_number
                    AS latest_version_number,
                latest.processing_status
                    AS latest_processing_status,

                (
                    SELECT COUNT(*)
                    FROM source_documents d
                    WHERE d.project_id = p.id
                ) AS version_count

            FROM projects p

            LEFT JOIN source_documents active
                ON active.id = p.active_document_id

            LEFT JOIN LATERAL (
                SELECT
                    d.id,
                    d.version_number,
                    d.processing_status
                FROM source_documents d
                WHERE d.project_id = p.id
                ORDER BY
                    d.version_number DESC,
                    d.id DESC
                LIMIT 1
            ) latest ON TRUE

            ORDER BY
                p.updated_at DESC,
                p.id DESC
            """
        ).fetchall()

        return [
            serialize_dates(dict(row))
            for row in rows
        ]


# =====================================================
# 14. GET PROJECT AND COMPLETE VERSION HISTORY
# =====================================================

def get_project(project_id):

    with get_connection() as conn:

        conn.row_factory = dict_row

        project = conn.execute(
            """
            SELECT
                id,
                client_name,
                source_insurer,
                assigned_underwriter,
                active_document_id,
                created_at,
                updated_at
            FROM projects
            WHERE id = %s
            """,
            (project_id,),
        ).fetchone()

        if not project:
            return None

        versions = conn.execute(
            """
            SELECT
                id,
                project_id,
                version_number,
                assigned_underwriter,
                original_filename,
                content_type,
                file_extension,
                file_size_bytes,
                processing_status,
                processing_error,
                created_at,
                processed_at
            FROM source_documents
            WHERE project_id = %s
            ORDER BY
                version_number DESC,
                id DESC
            """,
            (project_id,),
        ).fetchall()

        result = serialize_dates(dict(project))

        result["versions"] = [
            serialize_dates(dict(version))
            for version in versions
        ]

        result["version_count"] = len(
            result["versions"]
        )

        result["active_version"] = next(
            (
                version
                for version in result["versions"]
                if version["id"]
                == result["active_document_id"]
            ),
            None,
        )

        result["latest_version"] = (
            result["versions"][0]
            if result["versions"]
            else None
        )

        return result


# =====================================================
# 15. SEARCH DOCUMENT CHUNKS USING PGVECTOR
# =====================================================

def search_chunks(
    vector,
    limit=5,
):

    with get_connection() as conn:

        rows = conn.execute(
            """
            SELECT
                dc.document_id,
                sd.original_filename,
                dc.chunk_text,
                (dc.embedding <=> %s) AS distance
            FROM document_chunks dc

            JOIN source_documents sd
                ON sd.id = dc.document_id

            ORDER BY dc.embedding <=> %s

            LIMIT %s
            """,
            (
                vector,
                vector,
                limit,
            ),
        ).fetchall()

        return [
            {
                "document_id": row[0],
                "original_filename": row[1],
                "chunk_text": row[2],
                "distance": float(row[3]),
            }
            for row in rows
        ]
