-- ============================================================================
-- ddl-smoke.sql — EIS DDL 冒烟测试（PostgreSQL 16）
-- 前置：已执行 core.ddl / temporal.ddl / query-templates.sql / audit.ddl
--       与 build/ddl/*.ddl（schema-compiler 生成物）
-- 用法：psql -v ON_ERROR_STOP=1 -f tools/ci/ddl-smoke.sql
-- 断言失败即 RAISE EXCEPTION（CI 退出非零）；成功后全部回滚，不留数据。
-- ============================================================================

BEGIN;

-- 1. 双时间轴：同一对象两个版本（v1 已于 10-05 被系统替代）
INSERT INTO business_object (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at)
VALUES ('01900000-0000-7000-8000-0000000c0001', 1,
        '2026-10-01T00:00:00Z', '2026-10-05T00:00:00Z',
        '2026-10-01T00:00:00Z', '2026-10-05T00:00:00Z',
        '01900000-0000-7000-8000-0000000c00ff', '2026-10-01T00:00:00Z');

INSERT INTO business_object (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at)
VALUES ('01900000-0000-7000-8000-0000000c0001', 2,
        '2026-10-05T00:00:00Z', NULL,
        '2026-10-05T00:00:00Z', NULL,
        '01900000-0000-7000-8000-0000000c00ff', '2026-10-01T00:00:00Z');

-- 2. 时点查询：单一版本 + 半开区间边界 + 系统时间轴
DO $$
DECLARE n int;
BEGIN
  -- 业务时点 10-03 → 仅 v1
  SELECT count(*) INTO n FROM business_object
   WHERE id = '01900000-0000-7000-8000-0000000c0001'
     AND valid_from <= '2026-10-03T00:00:00Z'
     AND (valid_to IS NULL OR valid_to > '2026-10-03T00:00:00Z');
  IF n <> 1 THEN RAISE EXCEPTION '时点查询应为单一版本，实际 %', n; END IF;

  -- 边界：10-05 00:00（半开区间）→ 仅 v2
  SELECT version INTO n FROM business_object
   WHERE id = '01900000-0000-7000-8000-0000000c0001'
     AND valid_from <= '2026-10-05T00:00:00Z'
     AND (valid_to IS NULL OR valid_to > '2026-10-05T00:00:00Z');
  IF n <> 2 THEN RAISE EXCEPTION '半开区间边界应命中 v2，实际 v%', n; END IF;

  -- 系统时间轴：recorded_as_of = 10-02 → v1
  SELECT version INTO n FROM business_object
   WHERE id = '01900000-0000-7000-8000-0000000c0001'
     AND recorded_at <= '2026-10-02T00:00:00Z'
     AND (superseded_at IS NULL OR superseded_at > '2026-10-02T00:00:00Z');
  IF n <> 1 THEN RAISE EXCEPTION '系统时间轴时点查询应命中 v1，实际 v%', n; END IF;
END $$;

-- 3. 动态时点函数（as_of_valid）可直接执行
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM as_of_valid('business_object', '2026-10-03T00:00:00Z')
    AS r(id eis_id, version eis_version, valid_from eis_timestamp, valid_to eis_timestamp,
         recorded_at eis_timestamp, superseded_at eis_timestamp, created_by eis_id,
         created_at eis_timestamp, updated_by eis_id, updated_at eis_timestamp);
  IF n <> 1 THEN RAISE EXCEPTION 'as_of_valid 应返回 1 行，实际 %', n; END IF;
END $$;

-- 4. 约束：业务区间非法必须报错（T-R003）
DO $$
BEGIN
  BEGIN
    INSERT INTO business_object (id, version, valid_from, valid_to, recorded_at, created_by, created_at)
    VALUES ('01900000-0000-7000-8000-0000000c0002', 1,
            '2026-10-05T00:00:00Z', '2026-10-01T00:00:00Z',
            '2026-10-01T00:00:00Z',
            '01900000-0000-7000-8000-0000000c00ff', '2026-10-01T00:00:00Z');
    RAISE EXCEPTION '违规区间未被约束拦截';
  EXCEPTION WHEN check_violation THEN
    NULL;  -- 预期
  END;
END $$;

-- 5. 事件表 append-only（UPDATE / DELETE 必须无效）
INSERT INTO event (id, type, occurred_at, recorded_at, actor, subjects, payload, idempotency_key)
VALUES ('01900000-0000-7000-8000-0000000c0003', 'test.event.created',
        '2026-10-08T09:00:00Z', '2026-10-08T09:00:00Z',
        '01900000-0000-7000-8000-0000000c00ff', '{}', '{"k":1}', 'smoke-key-1');
UPDATE event SET payload = '{"k":2}' WHERE id = '01900000-0000-7000-8000-0000000c0003';
DELETE FROM event WHERE id = '01900000-0000-7000-8000-0000000c0003';
DO $$
BEGIN
  IF (SELECT payload->>'k' FROM event WHERE id = '01900000-0000-7000-8000-0000000c0003') <> '1' THEN
    RAISE EXCEPTION '事件被修改（append-only 失效）';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM event WHERE id = '01900000-0000-7000-8000-0000000c0003') THEN
    RAISE EXCEPTION '事件被删除（append-only 失效）';
  END IF;
END $$;

-- 6. 审计表 append-only
INSERT INTO audit_entry (id, sequence, timestamp, actor, action, resource_type, resource_id, payload, hash, prev_hash)
VALUES ('01900000-0000-7000-8000-0000000c0004', 1, '2026-10-08T09:00:00Z',
        '01900000-0000-7000-8000-0000000c00ff', 'smoke.action', 'test',
        '01900000-0000-7000-8000-0000000c0005', '{}',
        repeat('a', 64), repeat('0', 64));
UPDATE audit_entry SET action = 'tampered' WHERE id = '01900000-0000-7000-8000-0000000c0004';
DELETE FROM audit_entry WHERE id = '01900000-0000-7000-8000-0000000c0004';
DO $$
BEGIN
  IF (SELECT action FROM audit_entry WHERE id = '01900000-0000-7000-8000-0000000c0004') <> 'smoke.action' THEN
    RAISE EXCEPTION '审计条目被修改（append-only 失效）';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM audit_entry WHERE id = '01900000-0000-7000-8000-0000000c0004') THEN
    RAISE EXCEPTION '审计条目被删除（append-only 失效）';
  END IF;
END $$;

-- 7. 扩展表（schema-compiler 生成物）与展开时点函数
INSERT INTO accounting_balance (id, version, valid_from, recorded_at, created_by, created_at,
                                account_code, period, opening_balance, debit_total, credit_total, balance, currency)
VALUES ('01900000-0000-7000-8000-0000000c0006', 1,
        '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z',
        '01900000-0000-7000-8000-0000000c00ff', '2026-10-01T00:00:00Z',
        '1405', '2026-10', 0, 100.00, 0.00, 100.00, 'CNY');
DO $$
DECLARE n int;
BEGIN
  SELECT count(*) INTO n FROM accounting_balance_as_of_valid(
     '1405', '2026-10', '2026-10-15T00:00:00Z');
  IF n <> 1 THEN RAISE EXCEPTION '扩展时点函数应返回 1 行，实际 %', n; END IF;
END $$;

-- 8. 视图表可写（读模型）
INSERT INTO view (id, view_type, data, as_of, recorded_as_of, computed_at)
VALUES ('01900000-0000-7000-8000-0000000c0008', 'smoke.view', '{}',
        '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z');

-- 9. 有效区间不重叠（T-R009 / ADR-0011）：四维排他约束（id + 系统区间 + 业务区间）
-- 9.1 同一系统时间视图内业务区间相交 → 必须被排他约束拒绝（23P01，而非唯一索引 23505）
DO $$
BEGIN
  INSERT INTO business_object (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at)
  VALUES ('01900000-0000-7000-8000-0000000d0001', 1,
          '2026-10-01T00:00:00Z', '2026-10-20T00:00:00Z',
          '2026-10-01T00:00:00Z', '2026-10-20T00:00:00Z',
          '01900000-0000-7000-8000-0000000c00ff', '2026-10-01T00:00:00Z');
  BEGIN
    INSERT INTO business_object (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at)
    VALUES ('01900000-0000-7000-8000-0000000d0001', 2,
            '2026-10-05T00:00:00Z', NULL,
            '2026-10-05T00:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000c00ff', '2026-10-05T00:00:00Z');
    RAISE EXCEPTION '重叠有效区间未被排他约束拦截';
  EXCEPTION
    WHEN exclusion_violation THEN NULL;  -- 预期：T-R009 生效
    WHEN unique_violation THEN
      RAISE EXCEPTION '被唯一索引拦截而非排他约束（T-R009 约束未生效）';
  END;
END $$;

-- 9.2 正常封口链（superseded_at == 新记录 recorded_at）允许业务区间重叠（T-R011 修正形态）
DO $$
BEGIN
  INSERT INTO business_object (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at)
  VALUES ('01900000-0000-7000-8000-0000000d0002', 1,
          '2026-10-01T00:00:00Z', '2026-10-20T00:00:00Z',
          '2026-10-01T00:00:00Z', '2026-10-05T00:00:00Z',
          '01900000-0000-7000-8000-0000000c00ff', '2026-10-01T00:00:00Z');
  INSERT INTO business_object (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at)
  VALUES ('01900000-0000-7000-8000-0000000d0002', 2,
          '2026-10-01T00:00:00Z', '2026-10-20T00:00:00Z',
          '2026-10-05T00:00:00Z', NULL,
          '01900000-0000-7000-8000-0000000c00ff', '2026-10-05T00:00:00Z');
END $$;

-- 9.3 相邻业务区间（prev.valid_to == next.valid_from）即使系统区间相交也必须允许（半开区间）
DO $$
BEGIN
  INSERT INTO business_object (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at)
  VALUES ('01900000-0000-7000-8000-0000000d0003', 1,
          '2026-10-01T00:00:00Z', '2026-10-05T00:00:00Z',
          '2026-10-01T00:00:00Z', '2026-10-20T00:00:00Z',
          '01900000-0000-7000-8000-0000000c00ff', '2026-10-01T00:00:00Z');
  INSERT INTO business_object (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at)
  VALUES ('01900000-0000-7000-8000-0000000d0003', 2,
          '2026-10-05T00:00:00Z', NULL,
          '2026-10-05T00:00:00Z', NULL,
          '01900000-0000-7000-8000-0000000c00ff', '2026-10-05T00:00:00Z');
END $$;

-- 9.4 扩展表（schema-compiler 生成物）同样声明排他约束
DO $$
BEGIN
  INSERT INTO accounting_balance (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
                                  account_code, period, opening_balance, debit_total, credit_total, balance, currency)
  VALUES ('01900000-0000-7000-8000-0000000d0004', 1,
          '2026-10-01T00:00:00Z', '2026-10-20T00:00:00Z',
          '2026-10-01T00:00:00Z', '2026-10-20T00:00:00Z',
          '01900000-0000-7000-8000-0000000c00ff', '2026-10-01T00:00:00Z',
          '1405', '2026-10', 0, 100.00, 0.00, 100.00, 'CNY');
  BEGIN
    INSERT INTO accounting_balance (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
                                    account_code, period, opening_balance, debit_total, credit_total, balance, currency)
    VALUES ('01900000-0000-7000-8000-0000000d0004', 2,
            '2026-10-05T00:00:00Z', NULL,
            '2026-10-05T00:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000c00ff', '2026-10-05T00:00:00Z',
            '1405', '2026-10', 0, 100.00, 0.00, 100.00, 'CNY');
    RAISE EXCEPTION '扩展表重叠有效区间未被排他约束拦截';
  EXCEPTION
    WHEN exclusion_violation THEN NULL;  -- 预期
    WHEN unique_violation THEN
      RAISE EXCEPTION '扩展表被唯一索引拦截而非排他约束（生成物缺 T-R009 约束）';
  END;
END $$;

ROLLBACK;  -- 冒烟数据全部回滚

SELECT 'ddl-smoke: all assertions passed' AS result;
