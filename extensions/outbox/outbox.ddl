-- outbox.ddl — 可靠投递扩展（Outbox/Inbox）表结构（ADR-0018）
-- 归属：extensions/outbox（跨域运行时扩展，非核心六类契约）
-- 目标：PostgreSQL 16；本文件是可执行契约工件，CI DDL 任务执行并冒烟。
-- 语义：rules/delivery.rules.yaml（OBX-001..012）。

-- ---------------------------------------------------------------------------
-- 生产段：Outbox
-- ---------------------------------------------------------------------------
CREATE TABLE outbox_message (
    id                uuid        PRIMARY KEY,
    aggregate_type    text        NOT NULL,
    aggregate_id      text        NOT NULL,
    seq               bigint      NOT NULL CHECK (seq >= 1),
    event_id          uuid        NOT NULL,
    event_type        text        NOT NULL,
    payload           jsonb       NOT NULL,
    status            text        NOT NULL DEFAULT 'pending'
                                  CHECK (status IN ('pending', 'processing', 'sent', 'dead')),
    attempts          integer     NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at   timestamptz NOT NULL DEFAULT now(),
    lease_owner       text,
    lease_expires_at  timestamptz,
    last_error        text,
    created_at        timestamptz NOT NULL DEFAULT now(),
    sent_at           timestamptz,
    dead_at           timestamptz,
    -- 聚合内顺序身份：同一聚合的 seq 单调递增且唯一（OBX-003/004）
    CONSTRAINT uq_outbox_aggregate_seq UNIQUE (aggregate_id, seq),
    -- 事件只入 Outbox 一次（原子捕获 + 幂等）
    CONSTRAINT uq_outbox_event UNIQUE (event_id),
    CONSTRAINT ck_outbox_processing_lease CHECK (
        status <> 'processing' OR (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)),
    CONSTRAINT ck_outbox_sent_at CHECK (status <> 'sent' OR sent_at IS NOT NULL),
    CONSTRAINT ck_outbox_dead_at CHECK (status <> 'dead' OR dead_at IS NOT NULL),
    CONSTRAINT ck_outbox_lease_pair CHECK (
        (lease_owner IS NULL) = (lease_expires_at IS NULL))
);

-- 到期认领（relay claim）：pending 与可回收 processing
CREATE INDEX idx_outbox_due ON outbox_message (next_attempt_at, created_at)
    WHERE status IN ('pending', 'processing');

-- 分片键 = aggregate_id；聚合内按 seq 排序（OBX-003/004）
CREATE INDEX idx_outbox_aggregate_order ON outbox_message (aggregate_id, seq)
    WHERE status <> 'sent';

-- ---------------------------------------------------------------------------
-- 消费段：Inbox（最小语义，#34 已并入 #31）
-- ---------------------------------------------------------------------------
CREATE TABLE inbox_message (
    consumer_group    text        NOT NULL,
    event_id          uuid        NOT NULL,
    status            text        NOT NULL DEFAULT 'processing'
                                  CHECK (status IN ('processing', 'done', 'dead')),
    attempts          integer     NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    next_attempt_at   timestamptz NOT NULL DEFAULT now(),
    lease_owner       text,
    lease_expires_at  timestamptz,
    last_error        text,
    received_at       timestamptz NOT NULL DEFAULT now(),
    done_at           timestamptz,
    dead_at           timestamptz,
    -- 消费幂等：同一消费者组对同一事件只处理一次（OBX-012）
    PRIMARY KEY (consumer_group, event_id),
    CONSTRAINT ck_inbox_lease_pair CHECK (
        (lease_owner IS NULL) = (lease_expires_at IS NULL)),
    CONSTRAINT ck_inbox_done_at CHECK (status <> 'done' OR done_at IS NOT NULL),
    CONSTRAINT ck_inbox_dead_at CHECK (status <> 'dead' OR dead_at IS NOT NULL)
);

CREATE INDEX idx_inbox_due ON inbox_message (next_attempt_at)
    WHERE status = 'processing';
