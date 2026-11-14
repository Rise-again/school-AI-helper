-- 0004：Agent 轨迹落库
--
-- 目的：让"任取一条会话可完整复盘决策路径"成立——意图、改写关键词、
-- 每级检索的分数与条数、降级原因都随消息存一份。
-- 成本：一条消息一行，约 1–3 KB；不占显存、不增加推理耗时。

CREATE TABLE IF NOT EXISTS `agent_trace` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `conversation_id` BIGINT UNSIGNED NOT NULL,
  `message_id` BIGINT UNSIGNED NULL COMMENT '关联的助手消息 id；降级路径可能为空',
  `trace_id` VARCHAR(32) NULL COMMENT '与日志、X-Trace-Id 对应',
  `intent` VARCHAR(16) NULL,
  `keywords` VARCHAR(128) NULL COMMENT '路由产出的检索关键词（改写后）',
  `degraded` VARCHAR(32) NULL,
  `evidence_count` INT NOT NULL DEFAULT 0,
  `prompt_version` VARCHAR(16) NULL,
  `nodes` JSON NOT NULL COMMENT '各节点轨迹：kb/web 命中数、kb_top 分数、是否补联网等',
  `latency_ms` INT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_trace_conv` (`conversation_id`, `id`),
  KEY `idx_trace_msg` (`message_id`),
  CONSTRAINT `fk_trace_conv` FOREIGN KEY (`conversation_id`) REFERENCES `conversation` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent 决策轨迹，用于回答复盘';
