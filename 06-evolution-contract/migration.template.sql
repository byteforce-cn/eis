-- ============================================================================
-- migration.template.sql — 迁移脚本模板（Spec v1.0.0，冻结）
-- 命名：migration/V{version}__{description}.sql
-- 流程：准备 → 双写 → 切换 → 清理（见 06 演进契约）
-- 每个迁移必须有对应回滚：rollback.template.sql
-- ============================================================================

-- 1. 创建新表
CREATE TABLE object_v2 (
    -- 新结构
    id          eis_id        NOT NULL,
    version     eis_version   NOT NULL DEFAULT 1,
    valid_from  eis_timestamp NOT NULL,
    -- ...
    CONSTRAINT pk_object_v2 PRIMARY KEY (id)
);

-- 2. 迁移数据
INSERT INTO object_v2
SELECT
    id,
    version,
    valid_from
    -- 字段映射（逐字段显式列出，禁止 SELECT *）
FROM object_v1;

-- 3. 创建索引
CREATE INDEX idx_object_v2_valid_time ON object_v2 (valid_from);

-- 4. 验证
DO $$
BEGIN
    IF (SELECT COUNT(*) FROM object_v1) != (SELECT COUNT(*) FROM object_v2) THEN
        RAISE EXCEPTION 'Migration count mismatch';
    END IF;
END $$;

-- 5. 双写对账（双写期由应用执行；准入条件：差异率 < 0.001%）
-- DO $$
-- BEGIN
--     IF (SELECT COUNT(*) FROM object_v1 a FULL JOIN object_v2 b USING (id)
--         WHERE a.id IS NULL OR b.id IS NULL OR a.version != b.version) > 0 THEN
--         RAISE EXCEPTION 'Dual-write divergence detected';
--     END IF;
-- END $$;
