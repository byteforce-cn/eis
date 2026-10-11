-- ============================================================================
-- temporal.ddl — 双时间轴字段 DDL 片段（Spec v1.0.0，冻结）
-- 用途：schema-compiler 将本片段并入每个业务对象表的生成结果
-- 语义权威：temporal.rules.yaml（T-R001..T-R011）
-- ============================================================================

CREATE EXTENSION IF NOT EXISTS btree_gist;   -- 排他约束（防有效区间重叠）所需

-- ----------------------------------------------------------------------------
-- A. 列定义（每个业务对象表必备；与 01-data-contract/core.ddl 模板一致）
-- ----------------------------------------------------------------------------
--     valid_from      eis_timestamp NOT NULL,   -- 业务生效时间（左闭）
--     valid_to        eis_timestamp,            -- 业务失效时间（右开）；NULL = 当前有效
--     recorded_at     eis_timestamp NOT NULL,   -- 系统记录时间（左闭）
--     superseded_at   eis_timestamp,            -- 系统替代时间（右开）；NULL = 当前记录

-- ----------------------------------------------------------------------------
-- B. 表级约束（并入 CREATE TABLE；对应 T-R003 / T-R004）
-- ----------------------------------------------------------------------------
--     CONSTRAINT valid_range    CHECK (valid_to IS NULL OR valid_to > valid_from),
--     CONSTRAINT recorded_range CHECK (superseded_at IS NULL OR superseded_at > recorded_at),

-- ----------------------------------------------------------------------------
-- C. 索引（<table> 由生成器替换；对应时点查询模式）
-- ----------------------------------------------------------------------------
--     CREATE INDEX idx_<table>_valid_time    ON <table> (valid_from, valid_to);
--     CREATE INDEX idx_<table>_recorded_time ON <table> (recorded_at, superseded_at);
--     CREATE INDEX idx_<table>_bitemporal    ON <table> (valid_from, valid_to, recorded_at, superseded_at);

-- ----------------------------------------------------------------------------
-- D. 可选（推荐）：单当前记录 + 有效区间不重叠（对应 T-R005 / T-R009）
-- ----------------------------------------------------------------------------
--     CREATE UNIQUE INDEX uq_<table>_current ON <table> (id) WHERE superseded_at IS NULL;
--     ALTER TABLE <table> ADD CONSTRAINT ex_<table>_valid_overlap
--         EXCLUDE USING gist (
--             entity_id WITH =,
--             tstzrange(valid_from, valid_to, '[)') WITH &&
--         ) WHERE (superseded_at IS NULL);

-- ----------------------------------------------------------------------------
-- E. 生成示例
--    可执行示例已由 tools/schema-compiler 生成（schema-compiler compile --all），
--    产物见 build/ddl/*.ddl。为避免与生成物重名冲突，本文件不再内嵌具体建表
--    语句；以下为对照示意（列模板）：
-- ----------------------------------------------------------------------------
-- CREATE TABLE {ext}_{object} (
--     id .. version .. valid_from .. valid_to .. recorded_at .. superseded_at ..
--     created_by .. created_at .. updated_by .. updated_at ..
--     -- 领域字段（由对象 Schema 展开）
--     CONSTRAINT pk_{table} PRIMARY KEY (id, recorded_at),
--     CONSTRAINT valid_range    CHECK (valid_to IS NULL OR valid_to > valid_from),
--     CONSTRAINT recorded_range CHECK (superseded_at IS NULL OR superseded_at > recorded_at)
-- );
-- CREATE UNIQUE INDEX uq_{table}_current ON {table} (id) WHERE superseded_at IS NULL;
-- CREATE INDEX idx_{table}_valid_time    ON {table} (valid_from, valid_to);
-- CREATE INDEX idx_{table}_recorded_time ON {table} (recorded_at, superseded_at);
-- CREATE INDEX idx_{table}_bitemporal    ON {table} (valid_from, valid_to, recorded_at, superseded_at);
