-- 0001_init.sql —— 校园智能助手初始结构（13 张表）
-- 约定：utf8mb4 / InnoDB；主键 BIGINT UNSIGNED；时间 DATETIME；
-- 软删除仅用于 conversation / kb_file（deleted_at）；
-- 枚举用 VARCHAR + COMMENT，不用 MySQL ENUM（加值要 DDL）。

SET NAMES utf8mb4;

-- ---------- 迁移版本 ----------
CREATE TABLE IF NOT EXISTS `schema_version` (
  `version`     VARCHAR(32)  NOT NULL COMMENT '迁移文件名前缀，如 0001',
  `applied_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`version`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='迁移版本';

-- ---------- 账号 ----------
CREATE TABLE IF NOT EXISTS `user_account` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `username`      VARCHAR(64)     NOT NULL COMMENT '登录名；学生=学号，管理员=自定义',
  `role`          VARCHAR(16)     NOT NULL COMMENT 'student / admin（访客为匿名，不建账号）',
  `password_hash` VARCHAR(100)    NOT NULL COMMENT 'bcrypt',
  `status`        VARCHAR(16)     NOT NULL DEFAULT 'active' COMMENT 'active / disabled',
  `fail_count`    INT             NOT NULL DEFAULT 0,
  `locked_until`  DATETIME        NULL COMMENT '锁定到期时间',
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_username` (`username`),
  KEY `idx_role` (`role`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='账号';

CREATE TABLE IF NOT EXISTS `student_profile` (
  `id`                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`            BIGINT UNSIGNED NOT NULL,
  `student_no`         VARCHAR(32)     NOT NULL,
  `name`               VARCHAR(64)     NULL,
  `college`            VARCHAR(64)     NULL,
  `major`              VARCHAR(64)     NULL,
  `grade`              VARCHAR(16)     NULL,
  `edu_username`       VARCHAR(64)     NULL COMMENT '教务账号',
  `edu_cred_cipher`    VARBINARY(1024) NULL COMMENT '教务口令密文（AES-GCM：nonce+ct+tag）',
  `edu_bound_at`       DATETIME        NULL,
  `created_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`         DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user` (`user_id`),
  UNIQUE KEY `uk_student_no` (`student_no`),
  CONSTRAINT `fk_profile_user` FOREIGN KEY (`user_id`) REFERENCES `user_account` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生档案与教务绑定';

-- ---------- 会话与消息 ----------
CREATE TABLE IF NOT EXISTS `conversation` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT UNSIGNED NOT NULL,
  `title`      VARCHAR(128)    NOT NULL DEFAULT '新会话',
  `role_mode`  VARCHAR(16)     NOT NULL COMMENT '创建时的角色：student / admin',
  `deleted_at` DATETIME        NULL,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_user_updated` (`user_id`, `updated_at`),
  CONSTRAINT `fk_conv_user` FOREIGN KEY (`user_id`) REFERENCES `user_account` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话';

CREATE TABLE IF NOT EXISTS `message` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `conversation_id` BIGINT UNSIGNED NOT NULL,
  `role`            VARCHAR(16)     NOT NULL COMMENT 'user / assistant / system',
  `content`         MEDIUMTEXT      NOT NULL,
  `tokens`          INT             NULL,
  `latency_ms`      INT             NULL,
  `trace_id`        VARCHAR(32)     NULL,
  `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_conv_id` (`conversation_id`, `id`),
  CONSTRAINT `fk_msg_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversation` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='消息';

CREATE TABLE IF NOT EXISTS `citation` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `message_id` BIGINT UNSIGNED NOT NULL,
  `kb_file_id` BIGINT UNSIGNED NULL,
  `chunk_id`   VARCHAR(64)     NULL COMMENT 'Chroma 侧向量 ID',
  `page_no`    INT             NULL,
  `url`        VARCHAR(512)    NULL,
  `snippet`    VARCHAR(1024)   NOT NULL,
  `score`      DECIMAL(6,4)    NULL,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_msg` (`message_id`),
  CONSTRAINT `fk_cite_msg` FOREIGN KEY (`message_id`) REFERENCES `message` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='回答引用';

-- ---------- 知识库 ----------
CREATE TABLE IF NOT EXISTS `kb_file` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `filename`       VARCHAR(255)    NOT NULL,
  `file_hash`      CHAR(64)        NOT NULL COMMENT 'sha256，用于幂等',
  `file_type`      VARCHAR(16)     NOT NULL COMMENT 'pdf/docx/xlsx/pptx/html/txt',
  `size_bytes`     BIGINT          NOT NULL DEFAULT 0,
  `parse_channel`  VARCHAR(16)     NULL COMMENT 'markitdown / ocr',
  `source_dept`    VARCHAR(64)     NULL,
  `effective_from` DATE            NULL,
  `effective_to`   DATE            NULL,
  `parse_status`   VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT 'pending/parsing/success/failed',
  `chunk_count`    INT             NOT NULL DEFAULT 0,
  `version`        INT             NOT NULL DEFAULT 1,
  `uploaded_by`    BIGINT UNSIGNED NULL,
  `deleted_at`     DATETIME        NULL,
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_hash` (`file_hash`),
  KEY `idx_status` (`parse_status`),
  KEY `idx_deleted` (`deleted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库文件';

CREATE TABLE IF NOT EXISTS `kb_chunk` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `kb_file_id`  BIGINT UNSIGNED NOT NULL,
  `ordinal`     INT             NOT NULL COMMENT '文件内序号，从 0 开始',
  `content`     TEXT            NOT NULL,
  `token_count` INT             NOT NULL DEFAULT 0,
  `vector_id`   VARCHAR(64)     NULL COMMENT 'Chroma 向量 ID',
  `meta_json`   JSON            NULL COMMENT '页码、标题路径等',
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_file_ordinal` (`kb_file_id`, `ordinal`),
  KEY `idx_vector` (`vector_id`),
  CONSTRAINT `fk_chunk_file` FOREIGN KEY (`kb_file_id`) REFERENCES `kb_file` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='切片';

CREATE TABLE IF NOT EXISTS `parse_task` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `kb_file_id`  BIGINT UNSIGNED NOT NULL,
  `stage`       VARCHAR(16)     NOT NULL COMMENT 'parse/chunk/embed',
  `status`      VARCHAR(16)     NOT NULL DEFAULT 'pending' COMMENT 'pending/running/success/failed',
  `error_text`  TEXT            NULL,
  `started_at`  DATETIME        NULL,
  `finished_at` DATETIME        NULL,
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_file` (`kb_file_id`, `id`),
  KEY `idx_status` (`status`),
  CONSTRAINT `fk_task_file` FOREIGN KEY (`kb_file_id`) REFERENCES `kb_file` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='解析任务';

-- ---------- 缓存与配额 ----------
CREATE TABLE IF NOT EXISTS `search_cache` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `query_hash`  CHAR(64)        NOT NULL COMMENT '规范化查询的 sha256',
  `source`      VARCHAR(16)     NOT NULL COMMENT 'anysearch',
  `result_json` JSON            NOT NULL,
  `expires_at`  DATETIME        NOT NULL,
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_query_source` (`query_hash`, `source`),
  KEY `idx_expires` (`expires_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='外网搜索缓存（省配额）';

CREATE TABLE IF NOT EXISTS `api_quota` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_key`   VARCHAR(64)     NOT NULL COMMENT '用户 ID 或匿名 IP 的哈希',
  `quota_date` DATE            NOT NULL,
  `used`       INT             NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_key_date` (`user_key`, `quota_date`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='每日外网检索配额';

CREATE TABLE IF NOT EXISTS `audit_log` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `actor_id`   BIGINT UNSIGNED NULL,
  `action`     VARCHAR(64)     NOT NULL,
  `target`     VARCHAR(128)    NULL,
  `ip`         VARCHAR(45)     NULL,
  `trace_id`   VARCHAR(32)     NULL,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_actor` (`actor_id`, `created_at`),
  KEY `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='审计日志';

-- ---------- 模型版本 ----------
CREATE TABLE IF NOT EXISTS `model_version` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`          VARCHAR(64)     NOT NULL COMMENT '如 qwen2.5-7b-instruct-lora-v1',
  `base_model`    VARCHAR(128)    NOT NULL,
  `base_revision` VARCHAR(64)     NULL COMMENT '基座 commit/revision，必须可追溯',
  `adapter_path`  VARCHAR(512)    NULL COMMENT 'LoRA adapter 路径；空=用基座',
  `eval_score`    DECIMAL(6,4)    NULL,
  `status`        VARCHAR(16)     NOT NULL DEFAULT 'candidate' COMMENT 'candidate/active/retired',
  `notes`         VARCHAR(512)    NULL,
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='模型版本登记';
