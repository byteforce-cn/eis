-- ============================================================================
-- EIS core.ddl — 核心数据契约 DDL
-- Spec v1.0.0（2026-10-08 冻结）· 目标数据库：PostgreSQL 16+
-- 生成物：01-data-contract/*.schema.json → tools/schema-compiler
-- 禁止手工修改；变更必须走 ADR（00-freeze/adr/README.md）并附带迁移/回滚脚本
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;   -- 双时间轴排他约束（防区间重叠）所需

-- ----------------------------------------------------------------------------
-- 1. 核心域（冻结）
-- ----------------------------------------------------------------------------
CREATE DOMAIN eis_id        AS UUID;
CREATE DOMAIN eis_version   AS BIGINT CHECK (VALUE >= 1);
CREATE DOMAIN eis_timestamp AS TIMESTAMPTZ(6);

COMMENT ON DOMAIN eis_id        IS 'UUIDv7：全局唯一、时间有序';
COMMENT ON DOMAIN eis_version   IS '乐观锁版本号：每次更新 +1';
COMMENT ON DOMAIN eis_timestamp IS 'UTC 微秒时间戳（TIMESTAMPTZ(6)）';

-- ----------------------------------------------------------------------------
-- 2. 业务对象表模板
--    每个业务对象表 = 本模板元字段 + 领域字段（由扩展定义）
--    schema-compiler 按对象展开生成具体建表语句；本模板不直接部署
-- ----------------------------------------------------------------------------
CREATE TABLE business_object (
    -- 身份与并发
    id              eis_id        NOT NULL,
    version         eis_version   NOT NULL DEFAULT 1,

    -- 业务时间（Valid Time，半开区间 [valid_from, valid_to)）
    valid_from      eis_timestamp NOT NULL,
    valid_to        eis_timestamp,

    -- 系统时间（Transaction Time，半开区间 [recorded_at, superseded_at)；append-only）
    recorded_at     eis_timestamp NOT NULL,
    superseded_at   eis_timestamp,

    -- 审计字段
    created_by      eis_id        NOT NULL,
    created_at      eis_timestamp NOT NULL,
    updated_by      eis_id,
    updated_at      eis_timestamp,

    -- 领域字段（由扩展追加）...

    CONSTRAINT pk_business_object      PRIMARY KEY (id, recorded_at),
    CONSTRAINT valid_range             CHECK (valid_to IS NULL OR valid_to > valid_from),
    CONSTRAINT recorded_range          CHECK (superseded_at IS NULL OR superseded_at > recorded_at)
);

-- 同一业务对象至多一条“当前记录”（系统时间轴开区间）
CREATE UNIQUE INDEX uq_business_object_current
    ON business_object (id) WHERE superseded_at IS NULL;

-- 时点查询索引（见 03-time-contract/temporal.ddl 说明）
CREATE INDEX idx_business_object_valid_time    ON business_object (valid_from, valid_to);
CREATE INDEX idx_business_object_recorded_time ON business_object (recorded_at, superseded_at);
CREATE INDEX idx_business_object_bitemporal    ON business_object (valid_from, valid_to, recorded_at, superseded_at);

-- ----------------------------------------------------------------------------
-- 3. 事件表（append-only：事件是不可变更的事实）
-- ----------------------------------------------------------------------------
CREATE TABLE event (
    id               eis_id        NOT NULL,
    type             TEXT          NOT NULL,
    occurred_at      eis_timestamp NOT NULL,
    recorded_at      eis_timestamp NOT NULL,
    actor            eis_id        NOT NULL,
    subjects         UUID[]        NOT NULL DEFAULT '{}',
    payload          JSONB         NOT NULL,
    idempotency_key  TEXT          NOT NULL,
    version          INTEGER       NOT NULL DEFAULT 1,

    CONSTRAINT pk_event                PRIMARY KEY (id),
    CONSTRAINT event_type_format       CHECK (type ~ '^[a-z][a-z0-9_.]*$'),
    CONSTRAINT event_idempotency_key_uq UNIQUE (idempotency_key),
    CONSTRAINT event_recorded_after_occurred CHECK (recorded_at >= occurred_at)
);

CREATE INDEX idx_event_type_occurred ON event (type, occurred_at);
CREATE INDEX idx_event_actor         ON event (actor);
CREATE INDEX idx_event_subjects      ON event USING GIN (subjects);

-- append-only 保护
CREATE RULE event_no_update AS ON UPDATE TO event DO INSTEAD NOTHING;
CREATE RULE event_no_delete AS ON DELETE TO event DO INSTEAD NOTHING;

-- ----------------------------------------------------------------------------
-- 4. 命令表（写操作意图；幂等键全局唯一）
-- ----------------------------------------------------------------------------
CREATE TABLE command (
    id               eis_id        NOT NULL,
    type             TEXT          NOT NULL,
    issued_at        eis_timestamp NOT NULL,
    issuer           eis_id        NOT NULL,
    targets          UUID[]        NOT NULL DEFAULT '{}',
    payload          JSONB         NOT NULL,
    idempotency_key  TEXT          NOT NULL,
    status           TEXT          NOT NULL DEFAULT 'pending',
    rejection_reason TEXT,

    CONSTRAINT pk_command                 PRIMARY KEY (id),
    CONSTRAINT command_type_format        CHECK (type ~ '^[a-z][a-z0-9_.]*$'),
    CONSTRAINT command_status_check       CHECK (status IN ('pending', 'accepted', 'rejected')),
    CONSTRAINT command_idempotency_key_uq UNIQUE (idempotency_key)
);

CREATE INDEX idx_command_status ON command (status);

-- ----------------------------------------------------------------------------
-- 5. 视图表（读模型；可重复构建，携带双时点）
-- ----------------------------------------------------------------------------
CREATE TABLE view (
    id              eis_id        NOT NULL,
    view_type       TEXT          NOT NULL,
    subject         eis_id,
    data            JSONB         NOT NULL,
    as_of           eis_timestamp NOT NULL,
    recorded_as_of  eis_timestamp NOT NULL,
    computed_at     eis_timestamp NOT NULL,
    source_events   UUID[]        NOT NULL DEFAULT '{}',
    version         eis_version   NOT NULL DEFAULT 1,

    CONSTRAINT pk_view PRIMARY KEY (id, as_of, recorded_as_of)
);

CREATE INDEX idx_view_type_subject ON view (view_type, subject);
CREATE INDEX idx_view_bitemporal   ON view (view_type, as_of, recorded_as_of);
