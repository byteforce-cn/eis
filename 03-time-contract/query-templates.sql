-- ============================================================================
-- query-templates.sql — 时点查询模板（Spec v1.0.0，冻结）
-- 语义权威：temporal.rules.yaml（半开区间 [from, to)）
-- 说明：p_table 为动态表名（plpgsql 动态 SQL 实现，可直接执行）；返回 SETOF
--       record，调用方需附列定义列表（如 SELECT * FROM as_of_valid('t', now())
--       AS r(id uuid, ...)）。schema-compiler 亦可按具体表展开为强类型函数
--       （展开示例见文末）。
-- ============================================================================

-- 按业务时间查询
CREATE FUNCTION as_of_valid(p_table TEXT, p_time TIMESTAMPTZ)
RETURNS SETOF RECORD AS $$
BEGIN
  RETURN QUERY EXECUTE format(
    'SELECT * FROM %I WHERE valid_from <= $1 AND (valid_to IS NULL OR valid_to > $1)',
    p_table
  ) USING p_time;
END;
$$ LANGUAGE plpgsql STABLE;

-- 按系统时间查询
CREATE FUNCTION as_of_recorded(p_table TEXT, p_time TIMESTAMPTZ)
RETURNS SETOF RECORD AS $$
BEGIN
  RETURN QUERY EXECUTE format(
    'SELECT * FROM %I WHERE recorded_at <= $1 AND (superseded_at IS NULL OR superseded_at > $1)',
    p_table
  ) USING p_time;
END;
$$ LANGUAGE plpgsql STABLE;

-- 按双时间查询
CREATE FUNCTION as_of_bitemporal(
  p_table TEXT,
  p_valid_time TIMESTAMPTZ,
  p_recorded_time TIMESTAMPTZ
)
RETURNS SETOF RECORD AS $$
BEGIN
  RETURN QUERY EXECUTE format(
    'SELECT * FROM %I
      WHERE valid_from <= $1 AND (valid_to IS NULL OR valid_to > $1)
        AND recorded_at <= $2 AND (superseded_at IS NULL OR superseded_at > $2)',
    p_table
  ) USING p_valid_time, p_recorded_time;
END;
$$ LANGUAGE plpgsql STABLE;

-- ============================================================================
-- 展开示例（以 accounting_balance 为例）：可直接执行的具体函数
-- 前置：已执行 build/ddl/accounting.ddl（schema-compiler 生成物，字段以
--       extensions/accounting/objects/balance.schema.json 为准：account_code）
-- ============================================================================

-- 业务时点查询：科目在某期间、某业务时点的余额（单行）
CREATE FUNCTION accounting_balance_as_of_valid(
  p_account_code TEXT,
  p_period       TEXT,
  p_time         TIMESTAMPTZ
) RETURNS SETOF accounting_balance AS $$
  SELECT * FROM accounting_balance
  WHERE account_code = p_account_code
    AND period = p_period
    AND valid_from <= p_time
    AND (valid_to IS NULL OR valid_to > p_time)
    AND superseded_at IS NULL;
$$ LANGUAGE sql STABLE;

-- 双时间轴查询：系统在 p_recorded_time 时点“认为” p_valid_time 时的余额
CREATE FUNCTION accounting_balance_as_of_bitemporal(
  p_account_code  TEXT,
  p_period        TEXT,
  p_valid_time    TIMESTAMPTZ,
  p_recorded_time TIMESTAMPTZ
) RETURNS SETOF accounting_balance AS $$
  SELECT * FROM accounting_balance
  WHERE account_code = p_account_code
    AND period = p_period
    AND valid_from <= p_valid_time
    AND (valid_to IS NULL OR valid_to > p_valid_time)
    AND recorded_at <= p_recorded_time
    AND (superseded_at IS NULL OR superseded_at > p_recorded_time);
$$ LANGUAGE sql STABLE;
