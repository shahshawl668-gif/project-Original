-- Payroll Validation SaaS — PostgreSQL schema
-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- Users (one user = one company tenant)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    company_name VARCHAR(255),
    -- PT / LWF state(s) live in statutory_settings (multi-state per tenant);
    -- per-employee state is read from the salary register row.
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users (email);

-- Refresh tokens (JWT refresh)
CREATE TABLE refresh_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_refresh_tokens_user_id ON refresh_tokens (user_id);

-- Salary component configuration per tenant
CREATE TABLE components_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    component_name VARCHAR(100) NOT NULL,
    pf_applicable BOOLEAN NOT NULL DEFAULT FALSE,
    esic_applicable BOOLEAN NOT NULL DEFAULT FALSE,
    pt_applicable BOOLEAN NOT NULL DEFAULT FALSE,
    lwf_applicable BOOLEAN NOT NULL DEFAULT FALSE,
    bonus_applicable BOOLEAN NOT NULL DEFAULT FALSE,
    included_in_wages BOOLEAN NOT NULL DEFAULT FALSE,
    taxable BOOLEAN NOT NULL DEFAULT FALSE,
    tax_exemption_type VARCHAR(20) NOT NULL DEFAULT 'none',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, component_name)
);

CREATE INDEX idx_components_config_user_id ON components_config (user_id);

-- Professional Tax slabs (reference data; can be seeded per state)
CREATE TABLE pt_slabs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state VARCHAR(100) NOT NULL,
    slab_min NUMERIC(14, 2) NOT NULL,
    slab_max NUMERIC(14, 2) NOT NULL,
    amount NUMERIC(14, 2) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pt_slabs_state_dates ON pt_slabs (state, effective_from, effective_to);

-- Labour Welfare Fund rates by state and wage band
CREATE TABLE lwf_rates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    state VARCHAR(100) NOT NULL,
    wage_band_min NUMERIC(14, 2) NOT NULL,
    wage_band_max NUMERIC(14, 2) NOT NULL,
    employee_rate NUMERIC(14, 2) NOT NULL,
    employer_rate NUMERIC(14, 2) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_lwf_rates_state_dates ON lwf_rates (state, effective_from, effective_to);

-- Optional: store payroll upload runs for history
CREATE TABLE payroll_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    run_type VARCHAR(32) NOT NULL,
    effective_month_from DATE,
    effective_month_to DATE,
    filename VARCHAR(512),
    employee_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_payroll_runs_user_id ON payroll_runs (user_id);

-- Password reset tokens (optional flow)
CREATE TABLE password_reset_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    token_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_password_reset_user_id ON password_reset_tokens (user_id);

-- One-time per-tenant statutory configuration (PF, ESIC)
CREATE TABLE statutory_settings (
    user_id UUID PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    -- PF
    pf_wage_ceiling          NUMERIC(14, 2) NOT NULL DEFAULT 15000,
    pf_employee_rate         NUMERIC(6, 4)  NOT NULL DEFAULT 0.12,
    pf_employer_rate         NUMERIC(6, 4)  NOT NULL DEFAULT 0.12,
    pf_eps_rate              NUMERIC(6, 4)  NOT NULL DEFAULT 0.0833,
    pf_edli_rate             NUMERIC(6, 4)  NOT NULL DEFAULT 0.0050,
    pf_admin_rate            NUMERIC(6, 4)  NOT NULL DEFAULT 0.0050,
    pf_restrict_to_ceiling   BOOLEAN        NOT NULL DEFAULT TRUE,
    -- ESIC
    esic_wage_ceiling        NUMERIC(14, 2) NOT NULL DEFAULT 21000,
    esic_employee_rate       NUMERIC(6, 4)  NOT NULL DEFAULT 0.0075,
    esic_employer_rate       NUMERIC(6, 4)  NOT NULL DEFAULT 0.0325,
    esic_round_mode          VARCHAR(8)     NOT NULL DEFAULT 'up',
    -- Multi-state PT / LWF lists for the tenant. Per-employee state is taken
    -- from the salary register row; first item here is the fallback default.
    pt_states                JSONB          NOT NULL DEFAULT '[]'::jsonb,
    lwf_states               JSONB          NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- CTC report uploads (one row per file)
CREATE TABLE ctc_uploads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    effective_from DATE NOT NULL,
    filename VARCHAR(512),
    employee_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_ctc_uploads_user ON ctc_uploads (user_id, effective_from DESC);

-- CTC records (per-employee annual breakdown by component)
CREATE TABLE ctc_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    upload_id UUID NOT NULL REFERENCES ctc_uploads (id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    employee_id VARCHAR(64) NOT NULL,
    employee_name VARCHAR(255),
    effective_from DATE NOT NULL,
    annual_components JSONB NOT NULL,
    annual_ctc NUMERIC(14, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, employee_id, effective_from)
);

CREATE INDEX idx_ctc_records_user_emp ON ctc_records (user_id, employee_id, effective_from DESC);

-- Salary register (one row per period_month per tenant)
CREATE TABLE salary_registers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    period_month DATE NOT NULL,
    filename VARCHAR(512),
    employee_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, period_month)
);

CREATE INDEX idx_salary_registers_user ON salary_registers (user_id, period_month DESC);

-- Salary register rows (per-employee per period)
CREATE TABLE salary_register_rows (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    register_id UUID NOT NULL REFERENCES salary_registers (id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    period_month DATE NOT NULL,
    employee_id VARCHAR(64) NOT NULL,
    employee_name VARCHAR(255),
    paid_days NUMERIC(6, 2),
    lop_days NUMERIC(6, 2),
    components JSONB NOT NULL,
    arrears JSONB NOT NULL DEFAULT '{}',
    increment_arrear_total NUMERIC(14, 2) DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sr_rows_user_emp_period ON salary_register_rows (user_id, employee_id, period_month);
CREATE INDEX idx_sr_rows_register ON salary_register_rows (register_id);
