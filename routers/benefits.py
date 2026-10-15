from typing import Any, Optional, Literal
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from database import get_document, list_benefits, get_connection

router = APIRouter(prefix="/api/benefits", tags=["Benefits"])


class ManualBenefit(BaseModel):
    benefit_name: str = Field(min_length=1)
    benefit_category: Optional[str] = None
    limits: Optional[str] = None
    percentages: Optional[str] = None
    visits: Optional[str] = None
    deductibles: Optional[str] = None
    copay_ucr: Optional[str] = None
    benefit_treatment: Optional[str] = None
    other_attributes: dict[str, Any] = Field(default_factory=dict)
    added_by: str = "Underwriter"


class ResolveBenefitRequest(BaseModel):
    action: Literal["mark_na", "map_existing", "raise_change_request"]
    mapped_to_benefit: Optional[str] = None
    notes: Optional[str] = None
    resolved_by: str = "Underwriter"


def _not_found():
    raise HTTPException(status_code=404, detail="Document or benefit not found.")


@router.get("/by-document/{document_id}")
def get_benefits_by_document(document_id: int):
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")
    return {"document_id": document_id, "benefits": list_benefits(document_id)}


@router.post("/manual/{document_id}")
def add_manual_benefit(document_id: int, benefit: ManualBenefit):
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")

    conn = get_connection()
    try:
        row = conn.execute(
            """
            INSERT INTO extracted_benefits (
                document_id, benefit_name, benefit_category, limits, percentages,
                visits, deductibles, copay_ucr, benefit_treatment, other_attributes,
                extraction_confidence, validation_status, validation_reason,
                added_by, is_manually_added
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,TRUE)
            RETURNING id
            """,
            (
                document_id,
                benefit.benefit_name.strip(),
                benefit.benefit_category or "N/A",
                benefit.limits or "N/A",
                benefit.percentages or "N/A",
                benefit.visits or "N/A",
                benefit.deductibles or "N/A",
                benefit.copay_ucr or "N/A",
                benefit.benefit_treatment or "N/A",
                json.dumps(benefit.other_attributes, ensure_ascii=False),
                "manual",
                "Needs Review",
                "Manually added by underwriter; pending verification.",
                benefit.added_by,
            ),
        )
        benefit_id = row[0]
        conn.commit()
        return {
            "message": "Benefit added successfully",
            "benefit_id": benefit_id,
            "document_id": document_id,
            "validation_status": "Needs Review",
        }
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save benefit: {str(exc)}",
        ) from exc
    finally:
        conn.close()


@router.post("/resolve/{document_id}/{benefit_id}")
def resolve_benefit(
    document_id: int,
    benefit_id: int,
    request: ResolveBenefitRequest,
):
    """
    Persists the underwriter's decision on a benefit.
    action:
      - mark_na: sets status to N/A
      - map_existing: stores the selected existing benefit and sets Needs Review
      - raise_change_request: records a change request and sets Needs Review
    """
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")

    if request.action == "map_existing" and not (request.mapped_to_benefit or "").strip():
        raise HTTPException(
            status_code=422,
            detail="Select the existing benefit to map to.",
        )

    if request.action == "mark_na":
        status = "N/A"
        reason = request.notes or "Marked as not applicable by the underwriter."
    elif request.action == "map_existing":
        status = "Needs Review"
        reason = request.notes or f"Mapped to existing benefit: {request.mapped_to_benefit}."
    else:
        status = "Needs Review"
        reason = request.notes or "Change request raised by the underwriter."

    conn = get_connection()
    try:
        row = conn.execute(
            """
            UPDATE extracted_benefits
            SET validation_status = %s,
                validation_reason = %s,
                resolution_action = %s,
                resolution_notes = %s,
                resolved_by = %s,
                resolved_at = NOW(),
                mapped_to_benefit = %s
            WHERE id = %s AND document_id = %s
            RETURNING id, benefit_name, validation_status, validation_reason,
                      resolution_action, resolution_notes, resolved_by,
                      resolved_at, mapped_to_benefit
            """,
            (
                status,
                reason,
                request.action,
                request.notes,
                request.resolved_by,
                request.mapped_to_benefit if request.action == "map_existing" else None,
                benefit_id,
                document_id,
            ),
        ).fetchone()

        if not row:
            conn.rollback()
            _not_found()

        conn.commit()
        return {
            "message": "Benefit resolution saved.",
            "document_id": document_id,
            "benefit": {
                "id": row[0],
                "benefit_name": row[1],
                "validation_status": row[2],
                "validation_reason": row[3],
                "resolution_action": row[4],
                "resolution_notes": row[5],
                "resolved_by": row[6],
                "resolved_at": row[7].isoformat() if row[7] else None,
                "mapped_to_benefit": row[8],
            },
        }
    except HTTPException:
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save benefit resolution: {str(exc)}",
        ) from exc
    finally:
        conn.close()


@router.post("/validate/{document_id}")
def validate_document_benefits(document_id: int):
    """
    Basic source-text presence check only; this is not an authoritative policy comparison.
    Use a reference schedule for true validation.
    """
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    source_text = document.get("extracted_text") or ""
    if not source_text.strip():
        raise HTTPException(
            status_code=422,
            detail="No extracted source text is available for validation.",
        )

    benefits = list_benefits(document_id)
    normalized_source = " ".join(source_text.lower().split())
    results = []

    for benefit in benefits:
        name = (benefit.get("benefit_name") or "").strip()
        excerpt = (benefit.get("source_excerpt") or "").strip()
        matched = (
            bool(name and name.lower() in normalized_source)
            or bool(excerpt and excerpt.lower() in normalized_source)
        )
        if benefit.get("validation_status") == "N/A":
            status = "N/A"
            reason = benefit.get("validation_reason") or "Marked not applicable by underwriter."
        elif matched:
            status = "Needs Review"
            reason = "Text appears in the source document; reference schedule comparison is still required."
        else:
            status = "Needs Review"
            reason = "Could not confirm the benefit directly from the extracted source text."

        results.append({
            **benefit,
            "status": status,
            "validation_status": benefit.get("validation_status") or status,
            "validation_reason": benefit.get("validation_reason") or reason,
        })

    return {
        "document_id": document_id,
        "total": len(results),
        "valid": sum(item["status"] == "Valid" for item in results),
        "needs_review": sum(item["status"] == "Needs Review" for item in results),
        "results": results,
    }
