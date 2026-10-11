-- ============================================================================
-- V201__hr_initial.rollback.sql — 人力资源域初始迁移回滚
-- 顺序与 V201__hr_initial.sql 相反；仅回滚空域（有数据时请先导出）
-- ============================================================================

DROP TABLE IF EXISTS hr_provisioning_task;
DROP TABLE IF EXISTS hr_assignment;
DROP TABLE IF EXISTS hr_employee;
DROP TABLE IF EXISTS hr_position;
DROP TABLE IF EXISTS hr_organization_unit;
