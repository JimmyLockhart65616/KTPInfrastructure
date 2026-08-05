-- support.ktpdod.com — initial schema.
--
-- Two tables and nothing else: report intake, and privilege-request tickets.
-- There is deliberately no table mirroring users.ini. That file holds a
-- plaintext password beside every SteamID; this application never reads or
-- writes it, and a cached copy here would be the same exposure with an extra
-- step.
--
-- ⚠️ GRANTS ARE PER-TABLE ON THIS SERVER. A new table without its own GRANT
-- fails INSERTs *silently* from the app's point of view. Both tables are
-- granted at the bottom of this file — add to that block, never assume a
-- schema-wide grant exists.

CREATE TABLE IF NOT EXISTS support_reports (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  intake_id     CHAR(12)     NOT NULL,           -- shown in the embed, quotable in Discord
  category      VARCHAR(32)  NOT NULL,
  channel       VARCHAR(16)  NOT NULL,           -- derived from category, never submitted
  server_label  VARCHAR(32)  NULL,               -- from the poller's label list, or NULL
  body          VARCHAR(2000) NOT NULL,
  handle        VARCHAR(64)  NULL,               -- optional Discord handle
  ip_hash       CHAR(32)     NOT NULL,           -- salted; we need dedupe, not identities
  relayed       TINYINT(1)   NOT NULL DEFAULT 0, -- 0 = relay failed, retry from here
  created_at    TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_support_reports_intake (intake_id),
  KEY ix_support_reports_created (created_at),
  KEY ix_support_reports_unrelayed (relayed, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- The row is written BEFORE the relay call so a relay outage cannot eat a
-- report; `relayed` is flipped on success and the unrelayed index is the retry
-- queue. No public surface ever reads this table.

CREATE TABLE IF NOT EXISTS support_tickets (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  scope          VARCHAR(32)  NOT NULL,          -- one3_moderator | ktp_admin | season_captain
  steam_id       VARCHAR(32)  NOT NULL,
  display_name   VARCHAR(64)  NOT NULL,
  requested_by   VARCHAR(32)  NOT NULL,          -- Discord snowflake
  requested_note VARCHAR(500) NULL,
  status         VARCHAR(16)  NOT NULL DEFAULT 'submitted',
  season         SMALLINT UNSIGNED NULL,         -- set for season_captain only
  decided_by     VARCHAR(32)  NULL,
  applied_by     VARCHAR(32)  NULL,              -- who edited users.ini by hand
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY ix_support_tickets_status (status),
  KEY ix_support_tickets_expiry (scope, status, season)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- No password column, and there will not be one. The applying admin sets the
-- users.ini password and passes it to the grantee out of band; storing it here
-- would recreate the exposure this whole design exists to avoid.
--
-- `status` is validated in app/tickets.py rather than by an ENUM: the allowed
-- transitions matter more than the allowed values, and a CHECK constraint
-- cannot express "submitted may not become applied".

CREATE TABLE IF NOT EXISTS support_schema_migrations (
  version    VARCHAR(64) NOT NULL,
  applied_at TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (version)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Per-table grants. UPDATE is required on both: support_reports flips `relayed`
-- and support_tickets advances `status`, so SELECT+INSERT alone would let rows
-- be created and then fail to progress.
--
--   GRANT SELECT, INSERT, UPDATE ON hlstatsx.support_reports  TO 'support_web'@'localhost';
--   GRANT SELECT, INSERT, UPDATE ON hlstatsx.support_tickets  TO 'support_web'@'localhost';
--   GRANT SELECT, INSERT         ON hlstatsx.support_schema_migrations TO 'support_web'@'localhost';
--   FLUSH PRIVILEGES;
