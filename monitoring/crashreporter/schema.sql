-- KTP crashreporter — MySQL schema for v1.5 trend tracking.
--
-- v1 (host-side daemon) does NOT write to MySQL — embeds + on-disk
-- sidecars only. v1.5 will extend the existing KTPProfileAggregator
-- (which already SSHes to every host on a 5-min cycle) to ingest each
-- host's `*.reported` JSON sidecars into this table.
--
-- Apply on the data server's `hlstatsx` database (or whatever DB the
-- aggregator uses — check `ktp_telemetry_metrics` location and match it).

CREATE TABLE IF NOT EXISTS ktp_telemetry_crashes (
    id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    host_alias      VARCHAR(8)   NOT NULL,            -- "ATL3", "DAL5", "CHI?"
    region          VARCHAR(4)   NOT NULL,            -- "ATL", "DAL", …
    port            INT          NULL,                -- 27015..27019; NULL when port resolution failed
    host_ip         VARCHAR(45)  NOT NULL,            -- IPv4 only today, IPv6-ready
    binary_name     VARCHAR(64)  NOT NULL,            -- "hlds_linux", "engine_i486.so", …
    pid             INT UNSIGNED NOT NULL,
    crashed_at      DATETIME     NOT NULL,            -- from core filename %t (UTC)
    signal_name     VARCHAR(16)  NOT NULL,            -- "SIGSEGV", "SIGABRT", …
    signal_desc     VARCHAR(128) NULL,                -- "Segmentation fault", …
    top_frame       VARCHAR(255) NULL,                -- parsed from gdb bt #0
    core_path       VARCHAR(255) NOT NULL,            -- /tmp/core.<exe>.<pid>.<ts>
    discord_posted  TINYINT(1)   NOT NULL DEFAULT 0,
    reported_at     DATETIME     NOT NULL,            -- when daemon emitted the alert
    ingested_at     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uniq_core (host_alias, pid, crashed_at),
    KEY idx_alias_time (host_alias, crashed_at),
    KEY idx_top_frame (top_frame),
    KEY idx_signal (signal_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
