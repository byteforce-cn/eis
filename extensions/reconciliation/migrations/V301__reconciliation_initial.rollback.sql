-- ============================================================================
-- V301__reconciliation_initial.rollback.sql — 回滚 V301
-- 不删表（表由 build/ddl/reconciliation.ddl 生成）；仅移除本迁移新增的索引。
-- ============================================================================

DROP INDEX IF EXISTS idx_reconciliation_difference_run_category;
DROP INDEX IF EXISTS uq_reconciliation_run_run_key_current;
