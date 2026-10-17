-- ============================================================================
-- V202__hr_employee_employment_fields.sql — 人力资源域（hr v1.1.0）
-- 版本：V202；扩展：hr 1.1.0（依赖 core_version 1.0.0）
-- 变更：Employee 增加 employment_type / work_location——加法演进（MINOR，issue #13 / ADR-0009）
-- 生成物对齐：tools/migration-generator（草案）+ tools/schema-compiler compile hr（build/ddl/hr.ddl）
-- 前置：已执行 V201__hr_initial.sql
-- 回滚：V202__hr_employee_employment_fields.rollback.sql
-- ============================================================================

-- 可选新增列（历史数据按 NULL 处理；不加 NOT NULL、无需回填）
ALTER TABLE hr_employee ADD COLUMN employment_type TEXT;
ALTER TABLE hr_employee ADD COLUMN work_location TEXT;

-- 受控枚举约束（与 schema-compiler 生成物逐字对齐）
ALTER TABLE hr_employee
    ADD CONSTRAINT ck_hr_employee_employment_type
    CHECK (employment_type IN ('full_time', 'part_time', 'intern', 'contract'));
