-- scheduler.ddl — 定时任务 / 日终批处理执行语义扩展（ADR-0021）
-- 归属：extensions/scheduler（跨域运行时扩展，非核心六类契约）
-- 目标：PostgreSQL 16；本文件是可执行契约工件，CI DDL 任务执行并冒烟。
-- 语义：rules/scheduling.rules.yaml（SCH-001..012）。

-- ---------------------------------------------------------------------------
-- 作业定义：job_id 命名空间 + 计划表达式 + 定义版本
-- ---------------------------------------------------------------------------
CREATE TABLE scheduled_job (
    job_id          text        PRIMARY KEY,
    schedule        text        NOT NULL,
    schedule_format text        NOT NULL
                                CHECK (schedule_format IN ('cron', 'calendar')),
    version         bigint      NOT NULL DEFAULT 1 CHECK (version >= 1),
    max_attempts    integer     NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    enabled         boolean     NOT NULL DEFAULT true,
    description     text,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_scheduled_job_id CHECK (job_id ~ '^[a-z][a-z0-9_.-]*$')
);

-- ---------------------------------------------------------------------------
-- 运行记录：同一 (job_id, scheduled_for) 至多一个 run；run_key 即外部幂等键
-- ---------------------------------------------------------------------------
CREATE TABLE job_run (
    run_id           uuid        PRIMARY KEY,
    job_id           text        NOT NULL REFERENCES scheduled_job (job_id),
    run_key          text        NOT NULL,
    scheduled_for    timestamptz NOT NULL,
    scope            text        NOT NULL,
    status           text        NOT NULL DEFAULT 'running'
                                 CHECK (status IN ('running', 'succeeded', 'failed', 'skipped')),
    attempt          integer     NOT NULL DEFAULT 1 CHECK (attempt >= 1),
    max_attempts     integer     NOT NULL DEFAULT 3 CHECK (max_attempts >= 1),
    lease_id         uuid,
    lease_owner      text,
    lease_expires_at timestamptz,
    started_at       timestamptz NOT NULL DEFAULT now(),
    finished_at      timestamptz,
    last_error       text,
    created_at       timestamptz NOT NULL DEFAULT now(),
    -- 计划时点幂等（SCH-001）：同一作业同一计划时点至多一个 run
    CONSTRAINT uq_job_run_scheduled UNIQUE (job_id, scheduled_for),
    -- 外部幂等键（SCH-001）：run_key = job_id + scheduled_for
    CONSTRAINT uq_job_run_run_key UNIQUE (run_key),
    -- 租约三元组必须同时存在或同时为空（SCH-004）
    CONSTRAINT ck_job_run_lease_pair CHECK (
        (lease_id IS NULL) = (lease_owner IS NULL)
        AND (lease_owner IS NULL) = (lease_expires_at IS NULL)),
    -- running 必须持有租约（SCH-004）
    CONSTRAINT ck_job_run_running_lease CHECK (
        status <> 'running' OR (lease_id IS NOT NULL AND lease_expires_at IS NOT NULL)),
    -- 终态必须有完成时间（SCH-006）
    CONSTRAINT ck_job_run_finished_at CHECK (
        status NOT IN ('succeeded', 'skipped') OR finished_at IS NOT NULL),
    -- 终态不得残留租约（SCH-006）
    CONSTRAINT ck_job_run_terminal_lease CHECK (
        status = 'running' OR lease_id IS NULL),
    CONSTRAINT ck_job_run_attempt_bound CHECK (
        max_attempts >= 1 AND attempt <= max_attempts)
);

-- 同一互斥域同一时刻至多一个 running（SCH-003）。
-- 过期租约的陈旧 running 行必须先回收为 failed（lease_expired），再允许新 run 认领。
CREATE UNIQUE INDEX uq_job_run_scope_running ON job_run (scope)
    WHERE status = 'running';

-- 到期认领 / 租约回收扫描
CREATE INDEX idx_job_run_running_lease ON job_run (lease_expires_at)
    WHERE status = 'running';

-- 运维查询：按作业与计划时点倒序
CREATE INDEX idx_job_run_job_scheduled ON job_run (job_id, scheduled_for DESC);
