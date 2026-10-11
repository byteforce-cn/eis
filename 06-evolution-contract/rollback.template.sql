-- ============================================================================
-- rollback.template.sql — 回滚脚本模板（Spec v1.0.0，冻结）
-- 命名：rollback/V{version}__{description}.sql
-- 前提：迁移期间旧表保留（不做破坏性变更），随时可回退
-- ============================================================================

-- 1. 删除新表
DROP TABLE IF EXISTS object_v2;

-- 2. 恢复旧表
-- （旧表在迁移期间保留；回滚后写流量切回 object_v1）

-- 3. 验证
DO $$
BEGIN
    IF (SELECT COUNT(*) FROM object_v1) = 0 THEN
        RAISE EXCEPTION 'Rollback failed: old table is empty';
    END IF;
END $$;
