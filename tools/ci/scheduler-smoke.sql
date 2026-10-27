-- tools/ci/scheduler-smoke.sql — Scheduler DDL 冒烟（PostgreSQL 16，CI 使用）
-- 覆盖：run_key 幂等、计划时点唯一、scope 互斥、状态机、租约约束、陈旧租约回收。
\set ON_ERROR_STOP on
BEGIN;

INSERT INTO scheduled_job (job_id, schedule, schedule_format, max_attempts)
VALUES ('finance.daily-close', '0 1 * * *', 'cron', 3);

-- 1. 正常认领：running + 租约三元组
INSERT INTO job_run
       (run_id, job_id, run_key, scheduled_for, scope, status, attempt, max_attempts,
        lease_id, lease_owner, lease_expires_at)
VALUES ('01900000-0000-7000-8000-0000000e0001', 'finance.daily-close',
        'finance.daily-close@2026-10-27T01:00:00Z', '2026-10-27T01:00:00Z',
        'job:finance.daily-close', 'running', 1, 3,
        '01900000-0000-7000-8000-0000000e1001', 'worker-a',
        '2026-10-27T01:00:30Z');

-- 2. run_key 唯一：同一 run_key 不得插入第二份
DO $$
BEGIN
  BEGIN
    INSERT INTO job_run
           (run_id, job_id, run_key, scheduled_for, scope, status, attempt, max_attempts,
            lease_id, lease_owner, lease_expires_at)
    VALUES ('01900000-0000-7000-8000-0000000e0002', 'finance.daily-close',
            'finance.daily-close@2026-10-27T01:00:00Z', '2026-10-27T02:00:00Z',
            'job:finance.daily-close', 'running', 1, 3,
            '01900000-0000-7000-8000-0000000e1002', 'worker-b',
            '2026-10-27T01:00:30Z');
    RAISE EXCEPTION 'expected unique_violation on run_key';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 3. (job_id, scheduled_for) 唯一：换 run_key 也不能重复计划时点
DO $$
BEGIN
  BEGIN
    INSERT INTO job_run
           (run_id, job_id, run_key, scheduled_for, scope, status, attempt, max_attempts,
            lease_id, lease_owner, lease_expires_at)
    VALUES ('01900000-0000-7000-8000-0000000e0003', 'finance.daily-close',
            'finance.daily-close@2026-10-27T01:00:00Z#dup', '2026-10-27T01:00:00Z',
            'job:finance.daily-close', 'running', 1, 3,
            '01900000-0000-7000-8000-0000000e1003', 'worker-c',
            '2026-10-27T01:00:30Z');
    RAISE EXCEPTION 'expected unique_violation on (job_id, scheduled_for)';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 4. scope 互斥：同 scope 第二个 running 必须被部分唯一索引拒绝
DO $$
BEGIN
  BEGIN
    INSERT INTO job_run
           (run_id, job_id, run_key, scheduled_for, scope, status, attempt, max_attempts,
            lease_id, lease_owner, lease_expires_at)
    VALUES ('01900000-0000-7000-8000-0000000e0004', 'finance.daily-close',
            'finance.daily-close@2026-10-27T02:00:00Z', '2026-10-27T02:00:00Z',
            'job:finance.daily-close', 'running', 1, 3,
            '01900000-0000-7000-8000-0000000e1004', 'worker-d',
            '2026-10-27T02:00:30Z');
    RAISE EXCEPTION 'expected unique_violation on scope running';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 5. 状态机 CHECK：未知状态必须被拒
DO $$
BEGIN
  BEGIN
    INSERT INTO job_run (run_id, job_id, run_key, scheduled_for, scope, status)
    VALUES ('01900000-0000-7000-8000-0000000e0005', 'finance.daily-close',
            'finance.daily-close@2026-10-27T03:00:00Z', '2026-10-27T03:00:00Z',
            'job:finance.daily-close', 'bogus');
    RAISE EXCEPTION 'expected check_violation on status';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- 6. running 必须持有租约三元组
DO $$
BEGIN
  BEGIN
    INSERT INTO job_run (run_id, job_id, run_key, scheduled_for, scope, status)
    VALUES ('01900000-0000-7000-8000-0000000e0006', 'finance.daily-close',
            'finance.daily-close@2026-10-27T04:00:00Z', '2026-10-27T04:00:00Z',
            'job:finance.daily-close', 'running');
    RAISE EXCEPTION 'expected check_violation on running lease';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- 7. skipped 必须有 finished_at
DO $$
BEGIN
  BEGIN
    INSERT INTO job_run (run_id, job_id, run_key, scheduled_for, scope, status)
    VALUES ('01900000-0000-7000-8000-0000000e0007', 'finance.daily-close',
            'finance.daily-close@2026-10-27T05:00:00Z', '2026-10-27T05:00:00Z',
            'job:finance.daily-close', 'skipped');
    RAISE EXCEPTION 'expected check_violation on skipped finished_at';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- 8. 终态不得残留租约
DO $$
BEGIN
  BEGIN
    INSERT INTO job_run
           (run_id, job_id, run_key, scheduled_for, scope, status, attempt, max_attempts,
            lease_id, lease_owner, lease_expires_at, finished_at)
    VALUES ('01900000-0000-7000-8000-0000000e0008', 'finance.daily-close',
            'finance.daily-close@2026-10-27T06:00:00Z', '2026-10-27T06:00:00Z',
            'job:finance.daily-close', 'succeeded', 1, 3,
            '01900000-0000-7000-8000-0000000e1008', 'worker-a',
            '2026-10-27T06:00:30Z', '2026-10-27T06:00:10Z');
    RAISE EXCEPTION 'expected check_violation on terminal lease';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- 9. attempt 不得超过 max_attempts
DO $$
BEGIN
  BEGIN
    INSERT INTO job_run
           (run_id, job_id, run_key, scheduled_for, scope, status, attempt, max_attempts,
            lease_id, lease_owner, lease_expires_at)
    VALUES ('01900000-0000-7000-8000-0000000e0009', 'finance.daily-close',
            'finance.daily-close@2026-10-27T07:00:00Z', '2026-10-27T07:00:00Z',
            'job:finance.daily-close', 'running', 4, 3,
            '01900000-0000-7000-8000-0000000e1009', 'worker-a',
            '2026-10-27T07:00:30Z');
    RAISE EXCEPTION 'expected check_violation on attempt bound';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- 10. 陈旧租约回收：先置 failed，再允许新 run 认领同 scope
UPDATE job_run
   SET status = 'failed', finished_at = now(), last_error = 'lease_expired',
       lease_id = NULL, lease_owner = NULL, lease_expires_at = NULL
 WHERE run_key = 'finance.daily-close@2026-10-27T01:00:00Z';

INSERT INTO job_run
       (run_id, job_id, run_key, scheduled_for, scope, status, attempt, max_attempts,
        lease_id, lease_owner, lease_expires_at)
VALUES ('01900000-0000-7000-8000-0000000e0010', 'finance.daily-close',
        'finance.daily-close@2026-10-27T08:00:00Z', '2026-10-27T08:00:00Z',
        'job:finance.daily-close', 'running', 1, 3,
        '01900000-0000-7000-8000-0000000e1010', 'worker-e',
        '2026-10-27T08:00:30Z');

ROLLBACK;  -- 冒烟数据全部回滚

SELECT 'scheduler-smoke: all assertions passed' AS result;
