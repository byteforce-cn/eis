-- tools/ci/reconciliation-smoke.sql — 对账扩展 DDL 冒烟（PostgreSQL 16，CI 使用）
-- 前置：01-data-contract/core.ddl + build/ddl/reconciliation.ddl +
--       extensions/reconciliation/migrations/V301__reconciliation_initial.sql
-- 覆盖：run_key 当前行唯一（REC-001）、历史版本可复用 run_key、分类受控（REC-003）。
\set ON_ERROR_STOP on
BEGIN;

-- 1. 正常运行 + 差异
INSERT INTO reconciliation_run
       (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
        domain, period, sequence, run_key, status,
        tolerance_amount, tolerance_quantity,
        source_count, target_count, difference_count, started_at)
VALUES ('01900000-0000-7000-8000-0000000fa001', 1,
        '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
        '01900000-0000-7000-8000-0000000fa0ff', '2026-10-27T00:00:00Z',
        'order', '2026-10', 1, 'order:2026-10:1', 'running',
        0.01, 0.0001, 3, 2, 1, '2026-10-27T00:00:00Z');

INSERT INTO reconciliation_difference
       (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
        run_id, category, source_ref, target_ref, amount_delta, quantity_delta,
        resolution_code, resolved_by, resolved_at, note)
VALUES ('01900000-0000-7000-8000-0000000fa101', 1,
        '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
        '01900000-0000-7000-8000-0000000fa0ff', '2026-10-27T00:00:00Z',
        '01900000-0000-7000-8000-0000000fa001', 'amount_mismatch', 'ORD-1', 'PAY-1',
        1.00, NULL, NULL, NULL, NULL, NULL);

-- 2. run_key 当前行唯一：同一 run_key 第二个当前对象必须被拒
DO $$
BEGIN
  BEGIN
    INSERT INTO reconciliation_run
           (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
            domain, period, sequence, run_key, status,
            tolerance_amount, tolerance_quantity,
            source_count, target_count, difference_count, started_at)
    VALUES ('01900000-0000-7000-8000-0000000fa002', 1,
            '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000fa0ff', '2026-10-27T00:00:00Z',
            'order', '2026-10', 1, 'order:2026-10:1', 'running',
            0, 0, 1, 1, 0, '2026-10-27T00:00:00Z');
    RAISE EXCEPTION 'expected unique_violation on current run_key';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 3. 历史版本允许复用同一 run_key（当前行唯一，不是全表唯一）
UPDATE reconciliation_run
   SET superseded_at = '2026-10-27T01:00:00Z', valid_to = '2026-10-27T01:00:00Z'
 WHERE id = '01900000-0000-7000-8000-0000000fa001';

INSERT INTO reconciliation_run
       (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
        domain, period, sequence, run_key, status,
        tolerance_amount, tolerance_quantity,
        source_count, target_count, difference_count, started_at)
VALUES ('01900000-0000-7000-8000-0000000fa003', 1,
        '2026-10-27T01:00:00Z', NULL, '2026-10-27T01:00:00Z', NULL,
        '01900000-0000-7000-8000-0000000fa0ff', '2026-10-27T01:00:00Z',
        'order', '2026-10', 1, 'order:2026-10:1', 'running',
        0, 0, 1, 1, 0, '2026-10-27T01:00:00Z');

-- 4. 分类受控：未知分类必须被拒
DO $$
BEGIN
  BEGIN
    INSERT INTO reconciliation_difference
           (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
            run_id, category, source_ref)
    VALUES ('01900000-0000-7000-8000-0000000fa102', 1,
            '2026-10-27T01:00:00Z', NULL, '2026-10-27T01:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000fa0ff', '2026-10-27T01:00:00Z',
            '01900000-0000-7000-8000-0000000fa003', 'free_text_guess', 'ORD-2');
    RAISE EXCEPTION 'expected check_violation on category';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- 5. 处理方式受控：未知 resolution_code 必须被拒
DO $$
BEGIN
  BEGIN
    INSERT INTO reconciliation_difference
           (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
            run_id, category, source_ref, resolution_code)
    VALUES ('01900000-0000-7000-8000-0000000fa103', 1,
            '2026-10-27T01:00:00Z', NULL, '2026-10-27T01:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000fa0ff', '2026-10-27T01:00:00Z',
            '01900000-0000-7000-8000-0000000fa003', 'resolved', 'ORD-3', 'guess');
    RAISE EXCEPTION 'expected check_violation on resolution_code';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

ROLLBACK;  -- 冒烟数据全部回滚

SELECT 'reconciliation-smoke: all assertions passed' AS result;
