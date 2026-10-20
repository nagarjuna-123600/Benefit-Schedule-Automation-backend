from fastapi import APIRouter, HTTPException

from database import (
    get_document,
    list_benefits,
    get_connection,
)

from psycopg.rows import dict_row
from typing import List
from pydantic import BaseModel, Field

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
class OptionValueInput(BaseModel):
    benefit_id: int
    proposed_value: str = ""


class CoverageOptionInput(BaseModel):
    option_number: int = Field(ge=1, le=3)
    name: str = Field(min_length=1, max_length=150)
    values: List[OptionValueInput] = []


class SaveCoverageOptionsRequest(BaseModel):
    selected_option: int = Field(ge=1, le=3)
    options: List[CoverageOptionInput] = Field(min_length=1, max_length=3)


@router.get("/{document_id}/options")
def load_coverage_options(document_id: int):
    document = get_document(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    with get_connection() as conn:
        conn.row_factory = dict_row

        options = conn.execute(
            """
            SELECT id, option_number, option_name, is_selected
            FROM coverage_options
            WHERE document_id = %s
            ORDER BY option_number
            """,
            (document_id,),
        ).fetchall()

        result = []

        for option in options:
            values = conn.execute(
                """
                SELECT benefit_id, proposed_value
                FROM coverage_option_values
                WHERE option_id = %s
                """,
                (option["id"],),
            ).fetchall()

            result.append({
                "id": option["option_number"],
                "name": option["option_name"],
                "values": {
                    str(row["benefit_id"]): row["proposed_value"]
                    for row in values
                },
                "is_selected": option["is_selected"],
            })

    return {
        "document_id": document_id,
        "options": result,
        "selected_option": next(
            (
                option["option_number"]
                for option in options
                if option["is_selected"]
            ),
            result[0]["id"] if result else 1,
        ),
    }


@router.put("/{document_id}/options")
def save_coverage_options(
    document_id: int,
    payload: SaveCoverageOptionsRequest,
):
    document = get_document(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    numbers = [option.option_number for option in payload.options]

    if len(numbers) != len(set(numbers)):
        raise HTTPException(
            status_code=422,
            detail="Option numbers must be unique.",
        )

    if payload.selected_option not in numbers:
        raise HTTPException(
            status_code=422,
            detail="The selected option must exist in the options list.",
        )

    with get_connection() as conn:
        conn.row_factory = dict_row
        with conn.transaction():
            benefit_ids = {
                row["id"]
                for row in conn.execute(
                    """
                    SELECT id
                    FROM extracted_benefits
                    WHERE document_id = %s
                    """,
                    (document_id,),
                ).fetchall()
            }

            for option in payload.options:
                for value in option.values:
                    if value.benefit_id not in benefit_ids:
                        raise HTTPException(
                            status_code=422,
                            detail=(
                                f"Benefit {value.benefit_id} does not "
                                "belong to this document."
                            ),
                        )

            # Replace the saved configuration for this document.
            # The transaction ensures a failed save rolls back.
            conn.execute(
                "DELETE FROM coverage_options WHERE document_id = %s",
                (document_id,),
            )

            for option in payload.options:
                option_id = conn.execute(
                    """
                    INSERT INTO coverage_options (
                        document_id,
                        option_number,
                        option_name,
                        is_selected,
                        updated_at
                    )
                    VALUES (%s, %s, %s, %s, NOW())
                    RETURNING id
                    """,
                    (
                        document_id,
                        option.option_number,
                        option.name.strip(),
                        option.option_number == payload.selected_option,
                    ),
                ).fetchone()["id"]

                for value in option.values:
                    conn.execute(
                        """
                        INSERT INTO coverage_option_values (
                            option_id,
                            benefit_id,
                            proposed_value
                        )
                        VALUES (%s, %s, %s)
                        """,
                        (
                            option_id,
                            value.benefit_id,
                            value.proposed_value,
                        ),
                    )

    return {
        "message": "Coverage options saved successfully.",
        "document_id": document_id,
        "selected_option": payload.selected_option,
        "options_saved": len(payload.options),
    }
class OptionBenefitInput(BaseModel):
    mapping_id: int
    proposed_value: str = ""
    notes: str = ""


class OptionInput(BaseModel):
    option_number: int = Field(ge=1, le=3)
    option_name: str = Field(min_length=1, max_length=150)
    benefits: List[OptionBenefitInput] = []


class OptionsSaveRequest(BaseModel):
    selected_option: int = Field(ge=1, le=3)
    options: List[OptionInput] = Field(min_length=1, max_length=3)


@router.get("/{document_id}/options")
def get_coverage_options(document_id: int):
    document = get_document(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    with get_connection() as conn:
        conn.row_factory = dict_row

        draft = conn.execute(
            """
            SELECT id
            FROM underwriting_drafts
            WHERE document_id = %s
              AND version_label = 'v0.2'
            ORDER BY id DESC
            LIMIT 1
            """,
            (document_id,),
        ).fetchone()

        if not draft:
            return {
                "document_id": document_id,
                "draft_id": None,
                "options": [],
                "selected_option": 1,
            }

        options = conn.execute(
            """
            SELECT id, option_number, option_name
            FROM underwriting_options
            WHERE draft_id = %s
            ORDER BY option_number
            """,
            (draft["id"],),
        ).fetchall()

        result = []

        for option in options:
            rows = conn.execute(
                """
                SELECT mapping_id, proposed_value, notes
                FROM underwriting_option_benefits
                WHERE option_id = %s
                ORDER BY id
                """,
                (option["id"],),
            ).fetchall()

            result.append({
                "id": option["option_number"],
                "option_name": option["option_name"],
                "benefits": [dict(row) for row in rows],
            })

    return {
        "document_id": document_id,
        "draft_id": draft["id"],
        "options": result,
        "selected_option": 1,
    }


@router.put("/{document_id}/options")
def save_coverage_options(
    document_id: int,
    payload: OptionsSaveRequest,
):
    document = get_document(document_id)

    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    option_numbers = [item.option_number for item in payload.options]

    if len(option_numbers) != len(set(option_numbers)):
        raise HTTPException(
            status_code=422,
            detail="Option numbers must be unique.",
        )

    if payload.selected_option not in option_numbers:
        raise HTTPException(
            status_code=422,
            detail="Selected option must be included in the request.",
        )

    with get_connection() as conn:
        conn.row_factory = dict_row

        draft = conn.execute(
            """
            SELECT id
            FROM underwriting_drafts
            WHERE document_id = %s
              AND version_label = 'v0.2'
            ORDER BY id DESC
            LIMIT 1
            """,
            (document_id,),
        ).fetchone()

        if not draft:
            raise HTTPException(
                status_code=409,
                detail="No v0.2 underwriting draft exists for this document.",
            )

        with conn.transaction():
            existing = conn.execute(
                """
                SELECT id
                FROM underwriting_options
                WHERE draft_id = %s
                """,
                (draft["id"],),
            ).fetchall()

            # Remove child values before replacing the option configuration.
            for row in existing:
                conn.execute(
                    """
                    DELETE FROM underwriting_option_benefits
                    WHERE option_id = %s
                    """,
                    (row["id"],),
                )

            conn.execute(
                "DELETE FROM underwriting_options WHERE draft_id = %s",
                (draft["id"],),
            )

            for option in payload.options:
                created = conn.execute(
                    """
                    INSERT INTO underwriting_options
                        (draft_id, option_number, option_name)
                    VALUES (%s, %s, %s)
                    RETURNING id
                    """,
                    (
                        draft["id"],
                        option.option_number,
                        option.option_name.strip(),
                    ),
                ).fetchone()

                option_id = created["id"]

                for benefit in option.benefits:
                    conn.execute(
                        """
                        INSERT INTO underwriting_option_benefits
                            (option_id, mapping_id, proposed_value, notes, updated_at)
                        VALUES (%s, %s, %s, %s, NOW())
                        """,
                        (
                            option_id,
                            benefit.mapping_id,
                            benefit.proposed_value,
                            benefit.notes,
                        ),
                    )

    return {
        "message": "Options saved successfully.",
        "document_id": document_id,
        "draft_id": draft["id"],
        "options_saved": len(payload.options),
        "selected_option": payload.selected_option,
    }
# Add below your existing routes in routers/underwriting.py

class PricingOptionInput(BaseModel):
    option_id: int
    base_premium: float = Field(ge=0)
    is_selected: bool = False


class PricingSaveRequest(BaseModel):
    commission_percentage: float = Field(ge=0, le=10)
    currency_code: str = Field(default="INR", min_length=3, max_length=3)
    options: list[PricingOptionInput] = Field(min_length=1, max_length=3)


def _load_pricing_data(conn, document_id: int):
    conn.row_factory = dict_row

    options = conn.execute(
        """
        SELECT id, document_id, option_number, option_name, is_selected
        FROM coverage_options
        WHERE document_id = %s
        ORDER BY option_number
        """,
        (document_id,),
    ).fetchall()

    premiums = conn.execute(
        """
        SELECT pc.id, pc.option_id, pc.base_premium,
               pc.commission_percentage, pc.commission_amount,
               pc.total_premium, pc.currency_code,
               pc.calculation_status, pc.calculated_at
        FROM premium_calculations pc
        JOIN coverage_options co ON co.id = pc.option_id
        WHERE co.document_id = %s
        ORDER BY co.option_number, pc.id DESC
        """,
        (document_id,),
    ).fetchall()

    # Return the latest pricing record per option.
    latest_premiums = {}
    for premium in premiums:
        latest_premiums.setdefault(premium["option_id"], dict(premium))

    return {
        "document_id": document_id,
        "options": [dict(option) for option in options],
        "premiums": list(latest_premiums.values()),
    }


@router.get("/{document_id}/pricing")
def get_pricing(document_id: int):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    with get_connection() as conn:
        data = _load_pricing_data(conn, document_id)

    try:
        benefits = list_benefits(document_id)
    except Exception:
        benefits = []

    data["current_benefits"] = benefits
    return data


@router.post("/{document_id}/pricing/calculate")
def calculate_pricing(document_id: int, payload: PricingSaveRequest):
    return _save_pricing(document_id, payload)


@router.put("/{document_id}/pricing")
def save_pricing(document_id: int, payload: PricingSaveRequest):
    return _save_pricing(document_id, payload)


def _save_pricing(document_id: int, payload: PricingSaveRequest):
    document = get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail="Document not found.")

    if sum(1 for option in payload.options if option.is_selected) != 1:
        raise HTTPException(
            status_code=422,
            detail="Select exactly one coverage option.",
        )

    saved = []

    with get_connection() as conn:
        conn.row_factory = dict_row

        existing_options = conn.execute(
            """
            SELECT id, option_number
            FROM coverage_options
            WHERE document_id = %s
            ORDER BY option_number
            """,
            (document_id,),
        ).fetchall()

        valid_ids = {row["id"] for row in existing_options}
        submitted_ids = [option.option_id for option in payload.options]

        if len(set(submitted_ids)) != len(submitted_ids):
            raise HTTPException(
                status_code=422,
                detail="Duplicate coverage option IDs were submitted.",
            )

        if any(option_id not in valid_ids for option_id in submitted_ids):
            raise HTTPException(
                status_code=400,
                detail="An option does not belong to this document.",
            )

        # Update the selected option.
        selected_option_id = next(
            option.option_id
            for option in payload.options
            if option.is_selected
        )

        conn.execute(
            """
            UPDATE coverage_options
            SET is_selected = (id = %s),
                updated_at = CURRENT_TIMESTAMP
            WHERE document_id = %s
            """,
            (selected_option_id, document_id),
        )

        for option in payload.options:
            base = round(option.base_premium, 2)
            commission = round(
                base * payload.commission_percentage / 100, 2
            )
            total = round(base + commission, 2)

            existing = conn.execute(
                """
                SELECT id
                FROM premium_calculations
                WHERE option_id = %s
                ORDER BY id DESC
                LIMIT 1
                """,
                (option.option_id,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE premium_calculations
                    SET base_premium = %s,
                        commission_percentage = %s,
                        commission_amount = %s,
                        total_premium = %s,
                        currency_code = %s,
                        calculation_status = 'calculated',
                        calculated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    (
                        base,
                        payload.commission_percentage,
                        commission,
                        total,
                        payload.currency_code.upper(),
                        existing["id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO premium_calculations (
                        option_id,
                        base_premium,
                        commission_percentage,
                        commission_amount,
                        total_premium,
                        currency_code,
                        calculation_status,
                        calculated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'calculated',
                            CURRENT_TIMESTAMP)
                    """,
                    (
                        option.option_id,
                        base,
                        payload.commission_percentage,
                        commission,
                        total,
                        payload.currency_code.upper(),
                    ),
                )

            saved.append({
                "option_id": option.option_id,
                "base_premium": base,
                "commission_percentage": payload.commission_percentage,
                "commission_amount": commission,
                "total_premium": total,
                "currency_code": payload.currency_code.upper(),
                "is_selected": option.is_selected,
            })

        conn.commit()

    return {
        "message": "Pricing saved successfully.",
        "document_id": document_id,
        "selected_option_id": selected_option_id,
        "options": saved,
    }