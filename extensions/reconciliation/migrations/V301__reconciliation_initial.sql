-- ============================================================================
-- V301__reconciliation_initial.sql — 业务对账扩展（reconciliation 1.0.0）增量迁移
-- 前置：已执行 01-data-contract/core.ddl 与 build/ddl/reconciliation.ddl
--       （schema-compiler 生成 reconciliation_run / reconciliation_difference）
-- 内容：run_key 当前行唯一索引（REC-001 的 DB 兜底）+ 差异按运行/分类查询索引
-- 回滚：V301__reconciliation_initial.rollback.sql
-- ============================================================================

-- 同一 run_key 只允许一个当前运行对象（历史版本以 superseded_at 保留，可复用同一 run_key）
CREATE UNIQUE INDEX uq_reconciliation_run_run_key_current
    ON reconciliation_run (run_key)
    WHERE superseded_at IS NULL;

-- 报告投影：按运行读取差异、按分类计数
CREATE INDEX idx_reconciliation_difference_run_category
    ON reconciliation_difference (run_id, category);
