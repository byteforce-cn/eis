-- ============================================================================
-- V201__hr_initial.sql — 人力资源域（hr v1.0.0）初始迁移
-- 版本：V201；扩展：hr 1.0.0（依赖 core_version 1.0.0）
-- 生成物对齐：tools/schema-compiler compile hr（build/ddl/hr.ddl）
-- 前置：已执行 01-data-contract/core.ddl；本迁移幂等性由部署方按版本表保证
-- 回滚：V201__hr_initial.rollback.sql
-- ============================================================================

-- ============================================================================
-- hr.ddl — 人力资源域扩展 1.0.0 生成物
-- 源：extensions/hr/objects/*.schema.json + 01-data-contract/object.schema.json
-- 生成器：tools/schema-compiler（参考实现）；禁止手工修改
-- 前置：已执行 01-data-contract/core.ddl（eis_id / eis_version / eis_timestamp 域）
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;

-- ----------------------------------------------------------------------------
-- OrganizationUnit（extensions/hr/objects/organization-unit.schema.json）
-- ----------------------------------------------------------------------------
CREATE TABLE hr_organization_unit (
    id              eis_id NOT NULL,
    version         eis_version NOT NULL DEFAULT 1,
    valid_from      eis_timestamp NOT NULL,
    valid_to        eis_timestamp,
    recorded_at     eis_timestamp NOT NULL,
    superseded_at   eis_timestamp,
    created_by      eis_id NOT NULL,
    created_at      eis_timestamp NOT NULL,
    updated_by      eis_id,
    updated_at      eis_timestamp,
    -- 领域字段
    code            TEXT NOT NULL,   -- pattern ^[A-Z0-9][A-Z0-9_-]{1,31}$
    name            TEXT NOT NULL,
    unit_type       TEXT NOT NULL,
    parent_id       UUID,
    status          TEXT NOT NULL,
    description     TEXT,
    CONSTRAINT pk_hr_organization_unit            PRIMARY KEY (id, recorded_at),
    CONSTRAINT valid_range    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT recorded_range CHECK (superseded_at IS NULL OR superseded_at > recorded_at),
    CONSTRAINT ck_hr_organization_unit_unit_type CHECK (unit_type IN ('company', 'department', 'team')),
    CONSTRAINT ck_hr_organization_unit_status CHECK (status IN ('active', 'inactive'))
);

CREATE UNIQUE INDEX uq_hr_organization_unit_current ON hr_organization_unit (id) WHERE superseded_at IS NULL;
CREATE INDEX idx_hr_organization_unit_valid_time    ON hr_organization_unit (valid_from, valid_to);
CREATE INDEX idx_hr_organization_unit_recorded_time ON hr_organization_unit (recorded_at, superseded_at);
CREATE INDEX idx_hr_organization_unit_bitemporal    ON hr_organization_unit (valid_from, valid_to, recorded_at, superseded_at);

-- ----------------------------------------------------------------------------
-- Position（extensions/hr/objects/position.schema.json）
-- ----------------------------------------------------------------------------
CREATE TABLE hr_position (
    id              eis_id NOT NULL,
    version         eis_version NOT NULL DEFAULT 1,
    valid_from      eis_timestamp NOT NULL,
    valid_to        eis_timestamp,
    recorded_at     eis_timestamp NOT NULL,
    superseded_at   eis_timestamp,
    created_by      eis_id NOT NULL,
    created_at      eis_timestamp NOT NULL,
    updated_by      eis_id,
    updated_at      eis_timestamp,
    -- 领域字段
    code            TEXT NOT NULL,   -- pattern ^[A-Z0-9][A-Z0-9_-]{1,31}$
    title           TEXT NOT NULL,
    org_unit_id     UUID NOT NULL,
    reports_to_position_id UUID,
    grade           TEXT,
    headcount       NUMERIC(20,4),
    status          TEXT NOT NULL,
    CONSTRAINT pk_hr_position            PRIMARY KEY (id, recorded_at),
    CONSTRAINT valid_range    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT recorded_range CHECK (superseded_at IS NULL OR superseded_at > recorded_at),
    CONSTRAINT ck_hr_position_status CHECK (status IN ('active', 'frozen', 'closed'))
);

CREATE UNIQUE INDEX uq_hr_position_current ON hr_position (id) WHERE superseded_at IS NULL;
CREATE INDEX idx_hr_position_valid_time    ON hr_position (valid_from, valid_to);
CREATE INDEX idx_hr_position_recorded_time ON hr_position (recorded_at, superseded_at);
CREATE INDEX idx_hr_position_bitemporal    ON hr_position (valid_from, valid_to, recorded_at, superseded_at);

-- ----------------------------------------------------------------------------
-- Employee（extensions/hr/objects/employee.schema.json）
-- ----------------------------------------------------------------------------
CREATE TABLE hr_employee (
    id              eis_id NOT NULL,
    version         eis_version NOT NULL DEFAULT 1,
    valid_from      eis_timestamp NOT NULL,
    valid_to        eis_timestamp,
    recorded_at     eis_timestamp NOT NULL,
    superseded_at   eis_timestamp,
    created_by      eis_id NOT NULL,
    created_at      eis_timestamp NOT NULL,
    updated_by      eis_id,
    updated_at      eis_timestamp,
    -- 领域字段
    employee_no     TEXT NOT NULL,   -- pattern ^EMP-[0-9]{6,}$
    name            TEXT NOT NULL,
    status          TEXT NOT NULL,
    hire_date       DATE NOT NULL,
    org_unit_id     UUID,
    contact         TEXT,
    id_type         TEXT,
    id_number_hash  TEXT,
    terminated_at   eis_timestamp,
    terminated_reason TEXT,
    CONSTRAINT pk_hr_employee            PRIMARY KEY (id, recorded_at),
    CONSTRAINT valid_range    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT recorded_range CHECK (superseded_at IS NULL OR superseded_at > recorded_at),
    CONSTRAINT ck_hr_employee_status CHECK (status IN ('pending_onboarding', 'active', 'terminated', 'cancelled')),
    CONSTRAINT ck_hr_employee_id_type CHECK (id_type IN ('national_id', 'passport'))
);

CREATE UNIQUE INDEX uq_hr_employee_current ON hr_employee (id) WHERE superseded_at IS NULL;
CREATE INDEX idx_hr_employee_valid_time    ON hr_employee (valid_from, valid_to);
CREATE INDEX idx_hr_employee_recorded_time ON hr_employee (recorded_at, superseded_at);
CREATE INDEX idx_hr_employee_bitemporal    ON hr_employee (valid_from, valid_to, recorded_at, superseded_at);

-- ----------------------------------------------------------------------------
-- Assignment（extensions/hr/objects/assignment.schema.json）
-- ----------------------------------------------------------------------------
CREATE TABLE hr_assignment (
    id              eis_id NOT NULL,
    version         eis_version NOT NULL DEFAULT 1,
    valid_from      eis_timestamp NOT NULL,
    valid_to        eis_timestamp,
    recorded_at     eis_timestamp NOT NULL,
    superseded_at   eis_timestamp,
    created_by      eis_id NOT NULL,
    created_at      eis_timestamp NOT NULL,
    updated_by      eis_id,
    updated_at      eis_timestamp,
    -- 领域字段
    employee_id     UUID NOT NULL,
    position_id     UUID NOT NULL,
    org_unit_id     UUID NOT NULL,
    is_primary      BOOLEAN NOT NULL,
    status          TEXT NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE,
    CONSTRAINT pk_hr_assignment            PRIMARY KEY (id, recorded_at),
    CONSTRAINT valid_range    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT recorded_range CHECK (superseded_at IS NULL OR superseded_at > recorded_at),
    CONSTRAINT ck_hr_assignment_status CHECK (status IN ('active', 'ended'))
);

CREATE UNIQUE INDEX uq_hr_assignment_current ON hr_assignment (id) WHERE superseded_at IS NULL;
CREATE INDEX idx_hr_assignment_valid_time    ON hr_assignment (valid_from, valid_to);
CREATE INDEX idx_hr_assignment_recorded_time ON hr_assignment (recorded_at, superseded_at);
CREATE INDEX idx_hr_assignment_bitemporal    ON hr_assignment (valid_from, valid_to, recorded_at, superseded_at);

-- ----------------------------------------------------------------------------
-- ProvisioningTask（extensions/hr/objects/provisioning-task.schema.json）
-- ----------------------------------------------------------------------------
CREATE TABLE hr_provisioning_task (
    id              eis_id NOT NULL,
    version         eis_version NOT NULL DEFAULT 1,
    valid_from      eis_timestamp NOT NULL,
    valid_to        eis_timestamp,
    recorded_at     eis_timestamp NOT NULL,
    superseded_at   eis_timestamp,
    created_by      eis_id NOT NULL,
    created_at      eis_timestamp NOT NULL,
    updated_by      eis_id,
    updated_at      eis_timestamp,
    -- 领域字段
    employee_id     UUID NOT NULL,
    action          TEXT NOT NULL,
    status          TEXT NOT NULL,
    attempts        NUMERIC(20,4) NOT NULL,
    last_error      TEXT,
    completed_at    eis_timestamp,
    CONSTRAINT pk_hr_provisioning_task            PRIMARY KEY (id, recorded_at),
    CONSTRAINT valid_range    CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT recorded_range CHECK (superseded_at IS NULL OR superseded_at > recorded_at),
    CONSTRAINT ck_hr_provisioning_task_action CHECK (action IN ('create_account', 'enable_account', 'disable_account')),
    CONSTRAINT ck_hr_provisioning_task_status CHECK (status IN ('pending', 'succeeded', 'failed'))
);

CREATE UNIQUE INDEX uq_hr_provisioning_task_current ON hr_provisioning_task (id) WHERE superseded_at IS NULL;
CREATE INDEX idx_hr_provisioning_task_valid_time    ON hr_provisioning_task (valid_from, valid_to);
CREATE INDEX idx_hr_provisioning_task_recorded_time ON hr_provisioning_task (recorded_at, superseded_at);
CREATE INDEX idx_hr_provisioning_task_bitemporal    ON hr_provisioning_task (valid_from, valid_to, recorded_at, superseded_at);

