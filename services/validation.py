
def normalize_text(value):
    if value is None:
        return ""
    return " ".join(str(value).lower().replace(",", "").split())


def validate_benefit(benefit, source_text):
    fields = [
        "limits",
        "percentages",
        "visits",
        "deductibles",
        "copay_ucr",
        "benefit_treatment",
    ]

    checked_fields = []
    unmatched_fields = []

    source = normalize_text(source_text)

    for field in fields:
        value = benefit.get(field)

        if value is None or str(value).strip() in ("", "N/A"):
            continue

        normalized_value = normalize_text(value)

        if normalized_value in source:
            checked_fields.append(field)
        else:
            unmatched_fields.append(field)

    if unmatched_fields:
        status = "Needs Review"
        reason = "Some extracted values could not be matched to source text."
    elif checked_fields:
        status = "Valid"
        reason = "All checked values were found in the source text."
    else:
        status = "Needs Review"
        reason = "No usable values were available for verification."

    return {
        **benefit,
        "status": status,
        "validation_reason": reason,
        "checked_fields": checked_fields,
        "unmatched_fields": unmatched_fields,
    }
