
from typing import Any, Literal, Optional
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from services.validation import validate_benefit
from database import (
    get_document,
    list_benefits,
    get_connection,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/benefits",
    tags=["Benefits"]
)


# ============================================
# PYDANTIC SCHEMAS
# ============================================

class ManualBenefit(BaseModel):
    benefit_name: str = Field(min_length=1)
    benefit_category: Optional[str] = None
    limits: Optional[str] = None
    percentages: Optional[str] = None
    visits: Optional[str] = None
    deductibles: Optional[str] = None
    copay_ucr: Optional[str] = None
    benefit_treatment: Optional[str] = None
    other_attributes: dict[str, Any] = Field(
        default_factory=dict
    )
    added_by: str = "Underwriter"


class ResolveBenefitRequest(BaseModel):
    document_id: int

    action: Literal[
        "map_existing",
        "mark_na",
        "raise_change_request"
    ]

    notes: Optional[str] = None
    existing_benefit_id: Optional[int] = None
    existing_field: Optional[str] = None
    new_field_name: Optional[str] = None


# ============================================
# GET BENEFITS BY DOCUMENT
# ============================================

@router.get("/by-document/{document_id}")
def get_benefits_by_document(document_id: int):

    if not get_document(document_id):
        raise HTTPException(
            status_code=404,
            detail="Document not found."
        )

    return {
        "document_id": document_id,
        "benefits": list_benefits(document_id)
    }


# ============================================
# ADD MANUAL BENEFIT
# ============================================

@router.post("/manual/{document_id}")
def add_manual_benefit(
    document_id: int,
    benefit: ManualBenefit
):

    if not get_document(document_id):
        raise HTTPException(
            status_code=404,
            detail="Document not found."
        )

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
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s,
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
                    json.dumps(
                        benefit.other_attributes
                    ),
                    "manual",
                    "Needs Review",
                    benefit.added_by,
                    True,
                    "Manually added; pending verification"
                )
            )

            benefit_id = cur.fetchone()[0]

        conn.commit()

        return {
            "message": "Benefit added successfully",
            "benefit_id": benefit_id,
            "document_id": document_id,
            "validation_status": "Needs Review"
        }

    except Exception as exc:
        conn.rollback()

        logger.exception(
            "Failed to add manual benefit"
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to save benefit."
        ) from exc

    finally:
        conn.close()


# ============================================
# RESOLVE BENEFIT EXCEPTION
# THREE ACTIONS ONLY
# ============================================

@router.post("/{benefit_id}/resolve")
def resolve_benefit(
    benefit_id: int,
    decision: ResolveBenefitRequest
):
    """
    Save an underwriter review decision.

    Actions:
    1. map_existing
    2. mark_na
    3. raise_change_request

    A successfully saved review is marked
    as Validated.

    Change request approval remains separate
    from review completion.
    """

    if not get_document(decision.document_id):
        raise HTTPException(
            status_code=404,
            detail="Document not found."
        )

    existing_field = (
        decision.existing_field or ""
    ).strip()

    new_field_name = (
        decision.new_field_name or ""
    ).strip()

    resolution_notes = (
        decision.notes or ""
    ).strip()

    # ----------------------------------------
    # VALIDATE MAPPING INPUT
    # ----------------------------------------

    if decision.action == "map_existing":

        if (
            decision.existing_benefit_id is None
            and not existing_field
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Select an existing benefit "
                    "or field."
                )
            )

    # ----------------------------------------
    # VALIDATE CHANGE REQUEST INPUT
    # ----------------------------------------

    if decision.action == "raise_change_request":

        if not new_field_name:
            raise HTTPException(
                status_code=422,
                detail="New field name is required."
            )

    conn = get_connection()

    try:
        with conn.cursor() as cur:

            # --------------------------------
            # FETCH BENEFIT
            # --------------------------------

            cur.execute(
                """
                SELECT id, other_attributes
                FROM extracted_benefits
                WHERE id = %s
                  AND document_id = %s
                FOR UPDATE
                """,
                (
                    benefit_id,
                    decision.document_id
                )
            )

            row = cur.fetchone()

            if row is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Benefit not found "
                        "in this document."
                    )
                )

            attributes = row[1] or {}

            if isinstance(attributes, str):
                attributes = json.loads(attributes)

            if not isinstance(attributes, dict):
                attributes = {}

            # =================================
            # ACTION 1: MAP TO EXISTING
            # =================================

            if decision.action == "map_existing":

                target_benefit_name = None

                if decision.existing_benefit_id is not None:

                    if (
                        decision.existing_benefit_id
                        == benefit_id
                    ):
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                "Cannot map benefit "
                                "to itself."
                            )
                        )

                    # Verify target belongs
                    # to the same document

                    cur.execute(
                        """
                        SELECT id, benefit_name
                        FROM extracted_benefits
                        WHERE id = %s
                          AND document_id = %s
                        """,
                        (
                            decision.existing_benefit_id,
                            decision.document_id
                        )
                    )

                    target_row = cur.fetchone()

                    if target_row is None:
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                "Existing target "
                                "benefit not found."
                            )
                        )

                    target_benefit_name = target_row[1]

                reason = (
                    "Underwriter review completed: "
                    "mapped to an existing benefit."
                )

                resolution = {
                    "action": "map_existing",
                    "existing_benefit_id":
                        decision.existing_benefit_id,
                    "existing_benefit_name":
                        target_benefit_name,
                    "existing_field":
                        existing_field or None,
                    "notes": resolution_notes,
                    "review_status": "Completed"
                }

            # =================================
            # ACTION 2: MARK AS N/A
            # =================================

            elif decision.action == "mark_na":

                reason = (
                    "Underwriter review completed: "
                    "benefit marked as not applicable."
                )

                resolution = {
                    "action": "mark_na",
                    "notes": resolution_notes,
                    "review_status": "Completed",
                    "applicability": "N/A"
                }

            # =================================
            # ACTION 3: RAISE CHANGE REQUEST
            # =================================

            elif decision.action == "raise_change_request":

                reason = (
                    "Underwriter review completed: "
                    "change request submitted "
                    "for approval."
                )

                resolution = {
                    "action": "raise_change_request",
                    "new_field_name": new_field_name,
                    "notes": resolution_notes,
                    "review_status": "Completed",
                    "approval_status": "Pending"
                }

            # =================================
            # MARK REVIEW AS VALIDATED
            # =================================

            status = "Validated"

            # Preserve existing JSONB attributes
            # and save the review decision.

            attributes[
                "underwriter_resolution"
            ] = resolution

            # =================================
            # UPDATE POSTGRESQL
            # =================================

            cur.execute(
                """
                UPDATE extracted_benefits
                SET
                    validation_status = %s,
                    validation_reason = %s,
                    other_attributes = %s::jsonb
                WHERE id = %s
                  AND document_id = %s
                RETURNING id
                """,
                (
                    status,
                    reason,
                    json.dumps(attributes),
                    benefit_id,
                    decision.document_id
                )
            )

            if cur.fetchone() is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "Benefit could not "
                        "be updated."
                    )
                )

        conn.commit()

        return {
            "message": (
                "Review decision saved successfully."
            ),
            "document_id": decision.document_id,
            "benefit_id": benefit_id,
            "action": decision.action,
            "validation_status": status,
            "validation_reason": reason,
            "resolution": resolution
        }

    except HTTPException:
        conn.rollback()
        raise

    except Exception as exc:
        conn.rollback()

        logger.exception(
            "Failed to resolve benefit"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to save review decision."
            )
        ) from exc

    finally:
        conn.close()


# ============================================
# VALIDATE DOCUMENT BENEFITS
# ============================================

@router.post("/validate/{document_id}")
def validate_document_benefits(document_id: int):

    document = get_document(document_id)

    if not document:
        raise HTTPException(
            status_code=404,
            detail="Document not found."
        )

    source_text = (
        document.get("extracted_text") or ""
    )

    if not source_text.strip():
        raise HTTPException(
            status_code=422,
            detail=(
                "No extracted source text "
                "is available for validation."
            )
        )

    benefits = list_benefits(document_id)

    results = []

    conn = get_connection()

    try:
        with conn.cursor() as cur:

            for benefit in benefits:

                current_status = str(
                    benefit.get(
                        "validation_status"
                    ) or ""
                ).strip().lower()

                attributes = (
                    benefit.get(
                        "other_attributes"
                    ) or {}
                )

                if isinstance(attributes, str):
                    attributes = json.loads(
                        attributes
                    )

                if not isinstance(attributes, dict):
                    attributes = {}

                resolution = attributes.get(
                    "underwriter_resolution",
                    {}
                )

                if not isinstance(resolution, dict):
                    resolution = {}

                action = resolution.get("action")

                review_status = str(
                    resolution.get(
                        "review_status"
                    ) or ""
                ).strip().lower()

                # =================================
                # PRESERVE COMPLETED REVIEWS
                # =================================

                if (
                    review_status == "completed"
                    and action in (
                        "map_existing",
                        "mark_na",
                        "raise_change_request"
                    )
                ):
                    preserved_status = "Validated"

                    preserved_reason = (
                        benefit.get(
                            "validation_reason"
                        )
                        or "Underwriter review completed."
                    )

                    # Also repair older completed
                    # reviews that were saved with
                    # Needs Review, N/A, or
                    # Change Requested status.

                    if current_status != "validated":

                        cur.execute(
                            """
                            UPDATE extracted_benefits
                            SET
                                validation_status = %s,
                                validation_reason = %s
                            WHERE id = %s
                              AND document_id = %s
                            """,
                            (
                                preserved_status,
                                preserved_reason,
                                benefit["id"],
                                document_id
                            )
                        )

                    results.append({
                        **benefit,
                        "status": preserved_status,
                        "validation_status":
                            preserved_status,
                        "validation_reason":
                            preserved_reason
                    })

                    continue

                # =================================
                # PRESERVE EXISTING VALIDATED STATUS
                # =================================

                if current_status == "validated":

                    results.append({
                        **benefit,
                        "status": "Validated",
                        "validation_status": "Validated"
                    })

                    continue

                # =================================
                # RUN VALIDATION RULES
                # =================================

                result = validate_benefit(
                    benefit,
                    source_text
                )

                status = (
                    result.get("status")
                    or "Needs Review"
                )

                reason = (
                    result.get("validation_reason")
                    or result.get("reason")
                    or ""
                )

                # =================================
                # SAVE VALIDATION RESULT
                # =================================

                cur.execute(
                    """
                    UPDATE extracted_benefits
                    SET
                        validation_status = %s,
                        validation_reason = %s
                    WHERE id = %s
                      AND document_id = %s
                    """,
                    (
                        status,
                        reason,
                        benefit["id"],
                        document_id
                    )
                )

                results.append({
                    **benefit,
                    **result,
                    "id": benefit["id"],
                    "status": status,
                    "validation_status": status,
                    "validation_reason": reason
                })

        conn.commit()

    except Exception as exc:
        conn.rollback()

        logger.exception(
            "Failed to validate document benefits"
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to validate document benefits."
            )
        ) from exc

    finally:
        conn.close()

    # ============================================
    # VALIDATION SUMMARY
    # ============================================

    valid_statuses = {
        "valid",
        "validated",
        "verified",
        "passed",
        "approved"
    }

    excluded_statuses = {
        "n/a",
        "na",
        "not applicable"
    }

    valid_count = sum(
        str(item.get("status") or "")
        .strip()
        .lower() in valid_statuses
        for item in results
    )

    not_applicable_count = sum(
        str(item.get("status") or "")
        .strip()
        .lower() in excluded_statuses
        for item in results
    )

    needs_review_count = sum(
        str(item.get("status") or "")
        .strip()
        .lower() == "needs review"
        for item in results
    )

    change_requested_count = sum(
        str(item.get("status") or "")
        .strip()
        .lower() == "change requested"
        for item in results
    )

    total = len(results)

    completed_count = (
        valid_count + not_applicable_count
    )

    validation_percentage = (
        round(
            completed_count / total * 100
        )
        if total > 0
        else 0
    )

    return {
        "document_id": document_id,
        "total": total,
        "valid": valid_count,
        "validated": valid_count,
        "needs_review": needs_review_count,
        "change_requested": change_requested_count,
        "not_applicable": not_applicable_count,
        "completed": completed_count,
        "validation_percentage":
            validation_percentage,
        "results": results
    }