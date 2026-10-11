-- ============================================================================
-- audit.ddl — 审计表 DDL（Spec v1.0.0，冻结）
-- append-only：禁止 UPDATE / DELETE；哈希链规范化与验证见 hash-chain.spec.md
-- 生成物：audit.schema.json → schema-compiler
-- ============================================================================

CREATE TABLE audit_entry (
    id              UUID          NOT NULL,
    sequence        BIGSERIAL     NOT NULL,      -- 从 1 开始，单调递增（创世 = 1）
    timestamp       TIMESTAMPTZ(6) NOT NULL,     -- UTC 微秒
    actor           UUID          NOT NULL,
    action          TEXT          NOT NULL,
    resource_type   TEXT          NOT NULL,
    resource_id     UUID,
    payload         JSONB         NOT NULL,
    hash            TEXT          NOT NULL,
    prev_hash       TEXT          NOT NULL,
    signature       TEXT,                        -- 可选 CA 签名

    CONSTRAINT pk_audit_entry      PRIMARY KEY (id),
    CONSTRAINT audit_sequence_uq   UNIQUE (sequence),
    CONSTRAINT audit_hash_len      CHECK (hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT audit_prev_hash_len CHECK (prev_hash ~ '^[0-9a-f]{64}$')
);

-- 禁止 UPDATE 和 DELETE（append-only）
CREATE RULE audit_no_update AS ON UPDATE TO audit_entry DO INSTEAD NOTHING;
CREATE RULE audit_no_delete AS ON DELETE TO audit_entry DO INSTEAD NOTHING;

-- 索引
CREATE INDEX idx_audit_sequence ON audit_entry (sequence);
CREATE INDEX idx_audit_timestamp ON audit_entry (timestamp);
CREATE INDEX idx_audit_actor ON audit_entry (actor);
CREATE INDEX idx_audit_resource ON audit_entry (resource_type, resource_id);

-- 生产建议：以数据库权限进一步加固（审计写入角色仅保留 INSERT）
-- REVOKE UPDATE, DELETE ON audit_entry FROM <app_role>;
