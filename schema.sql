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
    document_id BIGINT NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
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
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding VECTOR(768) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(document_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_benefits_document_id ON extracted_benefits(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_document_id ON document_chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_documents_status ON source_documents(processing_status);
