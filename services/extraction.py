
import json
import requests

from config import (
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_EMBED_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    MAX_TEXT_CHARS,
    CHUNK_SIZE,
    CHUNK_OVERLAP,
)

FIELDS = [
    "benefit_name",
    "benefit_category",
    "limits",
    "percentages",
    "visits",
    "deductibles",
    "copay_ucr",
    "benefit_treatment",
    "other_attributes",
    "source_excerpt",
    "extraction_confidence",
]

EXTRACTION_INSTRUCTIONS = """
You extract structured insurance benefit schedule data.
Use only evidence present in the supplied source text.

Return one JSON object with exactly this top-level shape:
{
  "benefits": [
    {
      "benefit_name": "N/A",
      "benefit_category": "N/A",
      "limits": "N/A",
      "percentages": "N/A",
      "visits": "N/A",
      "deductibles": "N/A",
      "copay_ucr": "N/A",
      "benefit_treatment": "N/A",
      "other_attributes": {},
      "source_excerpt": "N/A",
      "extraction_confidence": "low"
    }
  ]
}

Rules:
- Extract every distinct benefit described in the supplied text.
- Do not merge unrelated benefits.
- Use the exact string "N/A" for missing or unsupported scalar values.
- Do not invent coverage, amounts, units, or rules.
- benefit_treatment must be "Base Benefit", "Major Medical",
  both if explicitly applicable, or "N/A".
- Capture limits, percentages, visits, frequency, deductibles,
  copayments, and UCR details when present.
- Store other supported details in other_attributes as a JSON object.
- source_excerpt must be a short exact excerpt from the supplied text.
- extraction_confidence must be "high", "medium", or "low".
- Return valid JSON only, without Markdown or explanations.
"""


def _post_ollama(path, payload):
    try:
        response = requests.post(
            f"{OLLAMA_BASE_URL.rstrip('/')}{path}",
            json=payload,
            timeout=OLLAMA_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.json()

    except requests.Timeout as exc:
        raise RuntimeError(
            f"Ollama timed out after {OLLAMA_TIMEOUT_SECONDS} seconds "
            f"while calling {path}. Check Ollama performance and reduce "
            "the input size if necessary."
        ) from exc

    except requests.RequestException as exc:
        raise RuntimeError(
            f"Could not call Ollama at {OLLAMA_BASE_URL}. "
            f"Check that Ollama is running and the model is installed. "
            f"Details: {exc}"
        ) from exc


def _normalize_value(value):
    if value is None or value == "" or value == []:
        return "N/A"

    if isinstance(value, (dict, list)):
        return value

    return str(value).strip() or "N/A"


def normalize_benefit(item):
    if not isinstance(item, dict):
        item = {}

    normalized = {}

    for key in FIELDS:
        if key == "other_attributes":
            value = item.get(key, {})
            normalized[key] = (
                value
                if isinstance(value, dict)
                else {"value": _normalize_value(value)}
            )

        elif key == "extraction_confidence":
            confidence = str(item.get(key, "low")).lower()
            normalized[key] = (
                confidence
                if confidence in {"high", "medium", "low"}
                else "low"
            )

        else:
            normalized[key] = _normalize_value(item.get(key))

    return normalized


def chunk_text(text):
    if not text:
        return []

    # Use manageable chunks for LLM extraction.
    size = max(200, min(CHUNK_SIZE, 4000))
    overlap = max(0, min(CHUNK_OVERLAP, size // 4))

    chunks = []
    start = 0

    while start < len(text):
        end = min(len(text), start + size)
        chunk = text[start:end].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = end - overlap

    return chunks


def _extract_benefits_from_chunk(chunk, chunk_number, total_chunks):
    result = _post_ollama(
        "/api/chat",
        {
            "model": OLLAMA_MODEL,
            "stream": False,
            "format": "json",
            "keep_alive": "10m",
            "messages": [
                {
                    "role": "system",
                    "content": EXTRACTION_INSTRUCTIONS,
                },
                {
                    "role": "user",
                    "content": (
                        f"Extract benefits from document section "
                        f"{chunk_number} of {total_chunks}.\n\n"
                        "Only use the following source text. "
                        "Extract all benefits supported by this section.\n\n"
                        f"{chunk}"
                    ),
                },
            ],
            "options": {
                "temperature": 0,
                "num_predict": 2048,
            },
        },
    )

    content = result.get("message", {}).get("content", "")

    try:
        parsed = json.loads(content)

    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"Ollama returned invalid JSON for section "
            f"{chunk_number}/{total_chunks}. "
            f"Response preview: {content[:300]}"
        ) from exc

    benefits = parsed.get("benefits", []) if isinstance(parsed, dict) else []

    if not isinstance(benefits, list):
        raise RuntimeError(
            f"Invalid benefits list in section {chunk_number}."
        )

    return [
        normalize_benefit(item)
        for item in benefits
        if isinstance(item, dict)
    ]


def _benefit_key(benefit):
    """
    Identify likely duplicate benefits returned by overlapping chunks.
    Do not merge benefits with different names.
    """
    name = str(benefit.get("benefit_name", "N/A")).strip().casefold()

    if name == "n/a":
        # Preserve unidentified records instead of merging all of them.
        return None

    category = str(
        benefit.get("benefit_category", "N/A")
    ).strip().casefold()

    return name, category


def _merge_duplicate(existing, incoming):
    """
    Fill missing fields from a duplicate record while preserving
    values already extracted.
    """
    merged = dict(existing)

    for field in FIELDS:
        old_value = merged.get(field)
        new_value = incoming.get(field)

        if field == "other_attributes":
            old_dict = old_value if isinstance(old_value, dict) else {}
            new_dict = new_value if isinstance(new_value, dict) else {}

            combined = dict(old_dict)

            for key, value in new_dict.items():
                if key not in combined or combined[key] in (None, "", "N/A"):
                    combined[key] = value

            merged[field] = combined

        elif old_value in (None, "", "N/A") and new_value not in (
            None, "", "N/A"
        ):
            merged[field] = new_value

        elif field == "source_excerpt":
            # Retain a useful supporting excerpt.
            if new_value not in (None, "", "N/A") and len(
                str(new_value)
            ) > len(str(old_value or "")):
                merged[field] = new_value

        elif field == "extraction_confidence":
            # Keep the stronger confidence label.
            rank = {"low": 1, "medium": 2, "high": 3}

            if rank.get(str(new_value), 0) > rank.get(str(old_value), 0):
                merged[field] = new_value

    return merged


def extract_benefits(document_text):
    if not document_text or not document_text.strip():
        raise ValueError("No document text was extracted.")

    # Respect the existing configured maximum.
    bounded_text = document_text[:MAX_TEXT_CHARS]

    chunks = chunk_text(bounded_text)

    if not chunks:
        raise ValueError("No usable text chunks were created.")

    all_benefits = []
    total_chunks = len(chunks)

    for index, chunk in enumerate(chunks, start=1):
        print(
            f"Extracting benefits from section "
            f"{index}/{total_chunks}..."
        )

        benefits = _extract_benefits_from_chunk(
            chunk,
            index,
            total_chunks,
        )

        all_benefits.extend(benefits)

    # Deduplicate results from overlapping chunks.
    merged_benefits = []
    seen = {}

    for benefit in all_benefits:
        key = _benefit_key(benefit)

        if key is None:
            merged_benefits.append(benefit)
            continue

        if key in seen:
            position = seen[key]
            merged_benefits[position] = _merge_duplicate(
                merged_benefits[position],
                benefit,
            )
        else:
            seen[key] = len(merged_benefits)
            merged_benefits.append(benefit)

    if not merged_benefits:
        merged_benefits = [
            normalize_benefit(
                {
                    "benefit_name": "N/A",
                    "source_excerpt": (
                        "No distinct benefit was identified "
                        "by the extraction model."
                    ),
                    "extraction_confidence": "low",
                }
            )
        ]

    print(
        f"Extraction complete: {len(merged_benefits)} "
        f"benefit records from {total_chunks} sections."
    )

    return merged_benefits


def create_embeddings(chunks):
    if not chunks:
        return []

    result = _post_ollama(
        "/api/embed",
        {
            "model": OLLAMA_EMBED_MODEL,
            "input": chunks,
            "keep_alive": "10m",
        },
    )

    vectors = result.get("embeddings")

    if not isinstance(vectors, list) or len(vectors) != len(chunks):
        raise RuntimeError(
            "Ollama embeddings response did not match "
            "the number of chunks."
        )

    for vector in vectors:
        if len(vector) != 768:
            raise RuntimeError(
                f"Expected 768-dimensional embeddings from "
                f"{OLLAMA_EMBED_MODEL}, received {len(vector)}. "
                "Check the model and PostgreSQL vector dimension."
            )

    return vectors


def embed_query(query):
    result = _post_ollama(
        "/api/embed",
        {
            "model": OLLAMA_EMBED_MODEL,
            "input": query,
            "keep_alive": "10m",
        },
    )

    vectors = result.get("embeddings", [])

    if not vectors:
        raise RuntimeError("Ollama did not return a query embedding.")

    vector = vectors[0]

    if len(vector) != 768:
        raise RuntimeError(
            f"Expected 768-dimensional query embedding, "
            f"received {len(vector)}."
        )

    return vector
