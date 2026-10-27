-- tools/ci/im-smoke.sql — IM 协作触达层 DDL 冒烟（PostgreSQL 16，CI 使用）
-- 前置：01-data-contract/core.ddl + build/ddl/im.ddl + extensions/im/migrations/V401__im_initial.sql
-- 覆盖：发送幂等、server_seq 唯一、群成员唯一、好友对双向唯一、黑名单唯一、已读位点唯一。
\set ON_ERROR_STOP on
BEGIN;

-- 1. 群 + 群主成员
INSERT INTO im_group (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
                      name, owner_user_id, status)
VALUES ('01900000-0000-7000-8000-0000000fb001', 1,
        '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
        '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
        '冒烟群', '01900000-0000-7000-8000-0000000fb0ff', 'active');

INSERT INTO im_group_member (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
                             group_id, user_id, role, mute_until, joined_at, left_at)
VALUES ('01900000-0000-7000-8000-0000000fb101', 1,
        '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
        '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
        '01900000-0000-7000-8000-0000000fb001', '01900000-0000-7000-8000-0000000fb0ff',
        'owner', NULL, '2026-10-27T00:00:00Z', NULL);

-- 2. 同一群同一用户只允许一个当前成员关系
DO $$
BEGIN
  BEGIN
    INSERT INTO im_group_member (id, version, valid_from, valid_to, recorded_at, superseded_at,
                                 created_by, created_at, group_id, user_id, role, joined_at)
    VALUES ('01900000-0000-7000-8000-0000000fb102', 1,
            '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
            '01900000-0000-7000-8000-0000000fb001', '01900000-0000-7000-8000-0000000fb0ff',
            'member', '2026-10-27T00:00:00Z');
    RAISE EXCEPTION 'expected unique_violation on group member';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 3. 消息：客户端幂等键唯一
INSERT INTO im_message (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
                        chat_id, sender_user_id, client_msg_id, server_seq, status, payload_type, content)
VALUES ('01900000-0000-7000-8000-0000000fb201', 1,
        '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
        '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
        '01900000-0000-7000-8000-0000000fb001', '01900000-0000-7000-8000-0000000fb0ff',
        'c-1', 1, 'normal', 0, '{"text":"hello"}'::jsonb);

DO $$
BEGIN
  BEGIN
    INSERT INTO im_message (id, version, valid_from, valid_to, recorded_at, superseded_at,
                            created_by, created_at, chat_id, sender_user_id, client_msg_id,
                            server_seq, status, payload_type, content)
    VALUES ('01900000-0000-7000-8000-0000000fb202', 1,
            '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
            '01900000-0000-7000-8000-0000000fb001', '01900000-0000-7000-8000-0000000fb0ff',
            'c-1', 2, 'normal', 0, '{}'::jsonb);
    RAISE EXCEPTION 'expected unique_violation on (chat_id, client_msg_id)';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 4. 消息：会话内 server_seq 唯一
DO $$
BEGIN
  BEGIN
    INSERT INTO im_message (id, version, valid_from, valid_to, recorded_at, superseded_at,
                            created_by, created_at, chat_id, sender_user_id, client_msg_id,
                            server_seq, status, payload_type, content)
    VALUES ('01900000-0000-7000-8000-0000000fb203', 1,
            '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
            '01900000-0000-7000-8000-0000000fb001', '01900000-0000-7000-8000-0000000fb0ff',
            'c-2', 1, 'normal', 0, '{}'::jsonb);
    RAISE EXCEPTION 'expected unique_violation on (chat_id, server_seq)';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 5. 好友：与方向无关的唯一对
INSERT INTO im_friendship (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
                           from_user_id, to_user_id, status, requested_at)
VALUES ('01900000-0000-7000-8000-0000000fb301', 1,
        '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
        '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
        '01900000-0000-7000-8000-0000000fb0ff', '01900000-0000-7000-8000-0000000fb0fe',
        'pending', '2026-10-27T00:00:00Z');

DO $$
BEGIN
  BEGIN
    INSERT INTO im_friendship (id, version, valid_from, valid_to, recorded_at, superseded_at,
                               created_by, created_at, from_user_id, to_user_id, status, requested_at)
    VALUES ('01900000-0000-7000-8000-0000000fb302', 1,
            '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
            '01900000-0000-7000-8000-0000000fb0fe', '01900000-0000-7000-8000-0000000fb0ff',
            'pending', '2026-10-27T00:00:00Z');
    RAISE EXCEPTION 'expected unique_violation on friendship pair (either direction)';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 6. 黑名单：同一对当前唯一
INSERT INTO im_block (id, version, valid_from, valid_to, recorded_at, superseded_at, created_by, created_at,
                      user_id, blocked_user_id, blocked_at)
VALUES ('01900000-0000-7000-8000-0000000fb401', 1,
        '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
        '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
        '01900000-0000-7000-8000-0000000fb0ff', '01900000-0000-7000-8000-0000000fb0fe',
        '2026-10-27T00:00:00Z');

DO $$
BEGIN
  BEGIN
    INSERT INTO im_block (id, version, valid_from, valid_to, recorded_at, superseded_at,
                          created_by, created_at, user_id, blocked_user_id, blocked_at)
    VALUES ('01900000-0000-7000-8000-0000000fb402', 1,
            '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
            '01900000-0000-7000-8000-0000000fb0ff', '01900000-0000-7000-8000-0000000fb0fe',
            '2026-10-27T00:00:00Z');
    RAISE EXCEPTION 'expected unique_violation on block pair';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

-- 7. 已读位点：端维度唯一
INSERT INTO im_read_position (id, version, valid_from, valid_to, recorded_at, superseded_at,
                              created_by, created_at, chat_id, user_id, endpoint_id, last_seq, reported_at)
VALUES ('01900000-0000-7000-8000-0000000fb501', 1,
        '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
        '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
        'dm-1', '01900000-0000-7000-8000-0000000fb0ff', 'dev-1', 5, '2026-10-27T00:00:00Z');

DO $$
BEGIN
  BEGIN
    INSERT INTO im_read_position (id, version, valid_from, valid_to, recorded_at, superseded_at,
                                  created_by, created_at, chat_id, user_id, endpoint_id, last_seq, reported_at)
    VALUES ('01900000-0000-7000-8000-0000000fb502', 1,
            '2026-10-27T00:00:00Z', NULL, '2026-10-27T00:00:00Z', NULL,
            '01900000-0000-7000-8000-0000000fb0ff', '2026-10-27T00:00:00Z',
            'dm-1', '01900000-0000-7000-8000-0000000fb0ff', 'dev-1', 3, '2026-10-27T00:00:00Z');
    RAISE EXCEPTION 'expected unique_violation on read position endpoint';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
END $$;

ROLLBACK;  -- 冒烟数据全部回滚

SELECT 'im-smoke: all assertions passed' AS result;
