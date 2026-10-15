from fastapi import APIRouter, HTTPException

from database import (
    get_document,
    list_benefits,
    get_connection,
)

from psycopg.rows import dict_row


router = APIRouter(
    prefix="/api/underwriting",
    tags=["Underwriting"],
)


# =====================================================
# 1. LOAD UNDERWRITING WORKSPACE
# =====================================================

@router.get("/{document_id}/workspace")
def get_underwriting_workspace(document_id: int):

    document = get_document(document_id)

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found.",
        )

    benefits = list_benefits(document_id)

    with get_connection() as conn:

        conn.row_factory = dict_row

        mappings = conn.execute(
            """
            SELECT *
            FROM benefit_mappings
            WHERE document_id = %s
            ORDER BY id
            """,
            (document_id,),
        ).fetchall()

        draft = conn.execute(
            """
            SELECT *
            FROM underwriting_drafts
            WHERE document_id = %s
              AND version_label = 'v0.2'
            """,
            (document_id,),
        ).fetchone()

        options = []

        if draft:
            options = conn.execute(
                """
                SELECT
                    o.id,
                    o.option_number,
                    o.option_name
                FROM underwriting_options o
                WHERE o.draft_id = %s
                ORDER BY o.option_number
                """,
                (draft["id"],),
            ).fetchall()

    return {
        "document_id": document_id,
        "project_id": document["project_id"],
        "current_plan": benefits,
        "mapped_benefits": [dict(row) for row in mappings],
        "draft": dict(draft) if draft else None,
        "options": [dict(row) for row in options],
    }