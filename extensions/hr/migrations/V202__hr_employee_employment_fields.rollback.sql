-- ============================================================================
-- V202__hr_employee_employment_fields.rollback.sql — 人力资源域（hr v1.1.0）
-- 顺序与 V202__hr_employee_employment_fields.sql 相反；仅新增列与约束，回滚即剔除（无数据迁移）
-- ============================================================================

ALTER TABLE hr_employee DROP CONSTRAINT IF EXISTS ck_hr_employee_employment_type;
ALTER TABLE hr_employee DROP COLUMN IF EXISTS employment_type;
ALTER TABLE hr_employee DROP COLUMN IF EXISTS work_location;
