-- =====================================================
-- UPDATE EXISTING EXTRACTED BENEFITS TABLE
-- =====================================================

ALTER TABLE extracted_benefits
ADD COLUMN IF NOT EXISTS validation_status TEXT
DEFAULT 'Needs Review';

ALTER TABLE extracted_benefits
ADD COLUMN IF NOT EXISTS validation_reason TEXT;

ALTER TABLE extracted_benefits
ADD COLUMN IF NOT EXISTS added_by TEXT
DEFAULT 'System';

ALTER TABLE extracted_benefits
ADD COLUMN IF NOT EXISTS is_manually_added BOOLEAN
DEFAULT FALSE;

-- =====================================================
-- 1. BENEFIT MAPPING - v0.1
-- =====================================================

CREATE TABLE IF NOT EXISTS benefit_mappings (
    id BIGSERIAL PRIMARY KEY,

    document_id BIGINT NOT NULL
        REFERENCES source_documents(id)
        ON DELETE CASCADE,

    source_benefit_id BIGINT
        REFERENCES extracted_benefits(id)
        ON DELETE SET NULL,

    benefit_name TEXT NOT NULL,
    benefit_category TEXT,

    current_value TEXT,
    coverage_field TEXT,

    mapping_status TEXT NOT NULL DEFAULT 'Needs Review',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =====================================================
-- 2. UNDERWRITING DRAFT - v0.2
-- =====================================================

CREATE TABLE IF NOT EXISTS underwriting_drafts (
    id BIGSERIAL PRIMARY KEY,

    project_id BIGINT NOT NULL
        REFERENCES projects(id),

    document_id BIGINT NOT NULL
        REFERENCES source_documents(id),

    version_label TEXT NOT NULL DEFAULT 'v0.2',

    status TEXT NOT NULL DEFAULT 'Underwriting In Progress',

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(document_id, version_label)
);


-- =====================================================
-- 3. COVERAGE OPTIONS
-- =====================================================

CREATE TABLE IF NOT EXISTS underwriting_options (
    id BIGSERIAL PRIMARY KEY,

    draft_id BIGINT NOT NULL
        REFERENCES underwriting_drafts(id)
        ON DELETE CASCADE,

    option_number INTEGER NOT NULL
        CHECK (option_number BETWEEN 1 AND 3),

    option_name TEXT NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(draft_id, option_number)
);


-- =====================================================
-- 4. PROPOSED BENEFIT VALUES
-- =====================================================

CREATE TABLE IF NOT EXISTS underwriting_option_benefits (
    id BIGSERIAL PRIMARY KEY,

    option_id BIGINT NOT NULL
        REFERENCES underwriting_options(id)
        ON DELETE CASCADE,

    mapping_id BIGINT NOT NULL
        REFERENCES benefit_mappings(id),

    proposed_value TEXT,

    notes TEXT,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    UNIQUE(option_id, mapping_id)
);


-- =====================================================
-- 5. CHANGE REQUESTS / EXCEPTIONS
-- =====================================================

CREATE TABLE IF NOT EXISTS change_requests (
    id BIGSERIAL PRIMARY KEY,

    draft_id BIGINT NOT NULL
        REFERENCES underwriting_drafts(id)
        ON DELETE CASCADE,

    mapping_id BIGINT
        REFERENCES benefit_mappings(id),

    description TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'Pending'
        CHECK (
            status IN (
                'Pending',
                'Approved',
                'Rejected',
                'Resolved'
            )
        ),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- =====================================================
-- 6. PREMIUM CALCULATIONS
-- =====================================================

CREATE TABLE IF NOT EXISTS premium_calculations (
    id BIGSERIAL PRIMARY KEY,

    option_id BIGINT NOT NULL
        REFERENCES underwriting_options(id)
        ON DELETE CASCADE,

    base_premium NUMERIC(18,2),

    commission_percentage NUMERIC(5,2)
        CHECK (
            commission_percentage BETWEEN 0 AND 10
        ),

    commission_amount NUMERIC(18,2),

    total_premium NUMERIC(18,2),

    currency_code VARCHAR(3) NOT NULL DEFAULT 'JMD',

    calculation_status TEXT NOT NULL DEFAULT 'Pending',

    calculated_at TIMESTAMPTZ,

    UNIQUE(option_id)
);

CREATE INDEX IF NOT EXISTS idx_benefit_mappings_document
ON benefit_mappings(document_id);

CREATE INDEX IF NOT EXISTS idx_underwriting_drafts_project
ON underwriting_drafts(project_id);

CREATE INDEX IF NOT EXISTS idx_underwriting_options_draft
ON underwriting_options(draft_id);