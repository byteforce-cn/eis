-- tools/ci/outbox-smoke.sql — Outbox/Inbox DDL 冒烟（PostgreSQL 16，CI 使用）
-- 覆盖：原子捕获唯一约束、状态机 CHECK、租约约束、SKIP LOCKED 认领、Inbox 幂等。
\set ON_ERROR_STOP on
BEGIN;

-- 1. 原子捕获：正常入队
INSERT INTO outbox_message
       (id, aggregate_type, aggregate_id, seq, event_id, event_type, payload)
VALUES ('01900000-0000-7000-8000-00000000a001', 'demo', 'agg-1', 1,
        '01900000-0000-7000-8000-00000000b001', 'demo.created', '{}'::jsonb);

-- 2. (aggregate_id, seq) 唯一：重复 seq 必须被拒
DO $$
BEGIN
  BEGIN
    INSERT INTO outbox_message
           (id, aggregate_type, aggregate_id, seq, event_id, event_type, payload)
    VALUES ('01900000-0000-7000-8000-00000000a002', 'demo', 'agg-1', 1,
            '01900000-0000-7000-8000-00000000b002', 'demo.updated', '{}'::jsonb);
    RAISE EXCEPTION 'expected unique_violation on (aggregate_id, seq)';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 3. event_id 唯一：同一事件只能入 Outbox 一次
DO $$
BEGIN
  BEGIN
    INSERT INTO outbox_message
           (id, aggregate_type, aggregate_id, seq, event_id, event_type, payload)
    VALUES ('01900000-0000-7000-8000-00000000a003', 'demo', 'agg-1', 2,
            '01900000-0000-7000-8000-00000000b001', 'demo.updated', '{}'::jsonb);
    RAISE EXCEPTION 'expected unique_violation on event_id';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 4. 状态机 CHECK：未知状态必须被拒
DO $$
BEGIN
  BEGIN
    INSERT INTO outbox_message
           (id, aggregate_type, aggregate_id, seq, event_id, event_type, payload, status)
    VALUES ('01900000-0000-7000-8000-00000000a004', 'demo', 'agg-2', 1,
            '01900000-0000-7000-8000-00000000b003', 'demo.created', '{}'::jsonb, 'bogus');
    RAISE EXCEPTION 'expected check_violation on status';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- 5. 租约约束：processing 必须同时有 lease_owner 与 lease_expires_at
DO $$
BEGIN
  BEGIN
    UPDATE outbox_message SET status = 'processing'
     WHERE id = '01900000-0000-7000-8000-00000000a001';
    RAISE EXCEPTION 'expected check_violation on processing lease';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- 6. 认领语句：FOR UPDATE SKIP LOCKED
UPDATE outbox_message
   SET status = 'processing', lease_owner = 'relay-a',
       lease_expires_at = now() + interval '30 seconds'
 WHERE id = (SELECT id FROM outbox_message
              WHERE status = 'pending' AND next_attempt_at <= now()
              ORDER BY next_attempt_at, created_at
              FOR UPDATE SKIP LOCKED
              LIMIT 1);
SELECT status, lease_owner FROM outbox_message WHERE aggregate_id = 'agg-1';

-- 7. 确认后置：sent 必须带 sent_at
UPDATE outbox_message
   SET status = 'sent', sent_at = now(), lease_owner = NULL, lease_expires_at = NULL
 WHERE aggregate_id = 'agg-1' AND seq = 1;
DO $$
BEGIN
  BEGIN
    UPDATE outbox_message SET status = 'sent', sent_at = NULL
     WHERE aggregate_id = 'agg-1' AND seq = 1;
    RAISE EXCEPTION 'expected check_violation on sent_at';
  EXCEPTION WHEN check_violation THEN NULL;
  END;
END $$;

-- 8. 失败/死信：dead 必须带 dead_at
UPDATE outbox_message
   SET status = 'dead', dead_at = now(), attempts = attempts + 1,
       lease_owner = NULL, lease_expires_at = NULL
 WHERE aggregate_id = 'agg-1' AND seq = 1;
SELECT status, attempts, dead_at IS NOT NULL AS has_dead_at
  FROM outbox_message WHERE aggregate_id = 'agg-1' AND seq = 1;

-- 9. Inbox 幂等：同 (consumer_group, event_id) 只能有一行
INSERT INTO inbox_message
       (consumer_group, event_id, status, lease_owner, lease_expires_at)
VALUES ('group-a', '01900000-0000-7000-8000-00000000b001', 'processing', 'consumer-1',
        now() + interval '30 seconds');
DO $$
BEGIN
  BEGIN
    INSERT INTO inbox_message
           (consumer_group, event_id, status, lease_owner, lease_expires_at)
    VALUES ('group-a', '01900000-0000-7000-8000-00000000b001', 'processing', 'consumer-2',
            now() + interval '30 seconds');
    RAISE EXCEPTION 'expected unique_violation on inbox (consumer_group, event_id)';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 10. Inbox 退避：processing 无租约（退避等待）合法，但 lease_owner/lease_expires_at 必须成对
UPDATE inbox_message
   SET lease_owner = NULL, lease_expires_at = NULL,
       next_attempt_at = now() + interval '2 seconds'
 WHERE consumer_group = 'group-a' AND event_id = '01900000-0000-7000-8000-00000000b001';

-- 11. Inbox done/dead 时间戳约束
UPDATE inbox_message
   SET status = 'done', done_at = now()
 WHERE consumer_group = 'group-a' AND event_id = '01900000-0000-7000-8000-00000000b001';
SELECT status, done_at IS NOT NULL AS has_done_at FROM inbox_message;

UPDATE inbox_message
   SET status = 'dead', dead_at = now()
 WHERE consumer_group = 'group-a' AND event_id = '01900000-0000-7000-8000-00000000b001';
SELECT status, dead_at IS NOT NULL AS has_dead_at FROM inbox_message;

COMMIT;
