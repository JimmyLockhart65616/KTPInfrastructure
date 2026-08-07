-- Replace the single `scope` column with level + group.
--
-- The live users.ini (audited 2026-08-05) holds 52 accounts across four
-- headings but only TWO flag sets, so one column could not describe a grant:
-- 1.3 Discord General Admins and S9 Captains both carry `cl` and differ only
-- by the heading their line sits under. Level decides the flags; group decides
-- the heading, and the group is what a postseason captain sweep filters on.
--
-- Safe as a straight swap: the table had no rows when this was applied.

ALTER TABLE support_tickets
  ADD COLUMN level      VARCHAR(8)  NOT NULL DEFAULT 'cl'        AFTER id,
  ADD COLUMN group_name VARCHAR(32) NOT NULL DEFAULT 'ktp_admin' AFTER level;

ALTER TABLE support_tickets DROP COLUMN scope;

-- The captain sweep queries group + status + season together.
ALTER TABLE support_tickets DROP INDEX ix_support_tickets_expiry;
ALTER TABLE support_tickets
  ADD INDEX ix_support_tickets_expiry (group_name, status, season);

INSERT IGNORE INTO support_schema_migrations (version) VALUES ('0002_level_group');
