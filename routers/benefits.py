
from typing import Any, Optional
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from services.validation import validate_benefit
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


@router.get("/by-document/{document_id}")
def get_benefits_by_document(document_id: int):
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")

    return {
        "document_id": document_id,
        "benefits": list_benefits(document_id),
    }


@router.post("/manual/{document_id}")
def add_manual_benefit(document_id: int, benefit: ManualBenefit):
    if not get_document(document_id):
        raise HTTPException(status_code=404, detail="Document not found.")

    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
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
                    extraction_confidence,
                    validation_status,
                    added_by,
                    is_manually_added,
                    validation_reason
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s::jsonb, %s, %s, %s, %s, %s
                )
                RETURNING id
                """,
                (
                    document_id,
                    benefit.benefit_name.strip(),
                    benefit.benefit_category,
                    benefit.limits,
                    benefit.percentages,
                    benefit.visits,
                    benefit.deductibles,
                    benefit.copay_ucr,
                    benefit.benefit_treatment,
                    json.dumps(benefit.other_attributes),
                    "manual",
                    "Needs Review",
                    benefit.added_by,
                    True,
                    "Manually added; pending verification",
                ),
            )

            benefit_id = cur.fetchone()[0]

        conn.commit()

        return {
            "message": "Benefit added successfully",
            "benefit_id": benefit_id,
            "document_id": document_id,
            "validation_status": "Needs Review",
        }

    except Exception as exc:
        conn.rollback()
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(
            status_code=500,
            detail="Failed to save benefit. Check the backend logs.",
        ) from exc
    finally:
        conn.close()


@router.post("/validate/{document_id}")
def validate_document_benefits(document_id: int):
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
    results = [
        validate_benefit(benefit, source_text)
        for benefit in benefits
    ]

    return {
        "document_id": document_id,
        "total": len(results),
        "valid": sum(item["status"] == "Valid" for item in results),
        "needs_review": sum(
            item["status"] == "Needs Review" for item in results
        ),
        "results": results,
    }
