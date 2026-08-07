"""Persistence for reports and tickets.

Connection-per-call, matching lan-web. This service handles a handful of writes
a day; a pool would be more moving parts than the load justifies.

The write order is the contract: a report row is committed BEFORE the relay is
called, and `relayed` is flipped afterwards. Relay-first would mean a relay
success followed by a database failure loses the audit row, and a relay failure
loses the report outright.
"""

from __future__ import annotations

from contextlib import contextmanager

import pymysql
import pymysql.cursors


def connect(host, port, user, password, database):
    return pymysql.connect(
        host=host, port=port, user=user, password=password, database=database,
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, autocommit=False,
    )


@contextmanager
def transaction(conn):
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def insert_report(conn, intake_id: str, report, ip_hash: str) -> int:
    with transaction(conn), conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO support_reports
              (intake_id, category, channel, server_label, body, handle, ip_hash, relayed)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
            """,
            (intake_id, report.category.value, report.channel.value,
             report.server_label, report.body, report.handle, ip_hash),
        )
        return cur.lastrowid


def mark_relayed(conn, report_id: int) -> None:
    with transaction(conn), conn.cursor() as cur:
        cur.execute("UPDATE support_reports SET relayed = 1 WHERE id = %s", (report_id,))


def unrelayed_reports(conn, limit: int = 50) -> list[dict]:
    """The retry queue. Oldest first so a backlog drains in order."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, intake_id, category, channel, server_label, body, handle
            FROM support_reports
            WHERE relayed = 0
            ORDER BY created_at ASC
            LIMIT %s
            """,
            (limit,),
        )
        return list(cur.fetchall())


def insert_ticket(conn, level, group, steam_id, display_name, requested_by,
                  note, season) -> int:
    """Level decides the flags written to users.ini; group decides which
    heading the line goes under. Both are stored -- two grants can carry the
    same flags under different headings, and the group is what a postseason
    sweep filters on."""
    with transaction(conn), conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO support_tickets
              (level, group_name, steam_id, display_name, requested_by,
               requested_note, status, season)
            VALUES (%s, %s, %s, %s, %s, %s, 'submitted', %s)
            """,
            (level.value, group.value, steam_id, display_name, requested_by,
             note, season),
        )
        return cur.lastrowid


def set_ticket_status(conn, current, target, ticket_id: int, actor: str) -> bool:
    """Advance a ticket, refusing to skip a step.

    The WHERE clause pins the current status, so two admins acting at once
    cannot both move the same ticket -- the second update matches no rows and
    returns False rather than silently overwriting the first decision.
    """
    column = {"applied": "applied_by"}.get(target.value, "decided_by")
    with transaction(conn), conn.cursor() as cur:
        cur.execute(
            f"UPDATE support_tickets SET status = %s, {column} = %s "
            "WHERE id = %s AND status = %s",
            (target.value, actor, ticket_id, current.value),
        )
        return cur.rowcount == 1


def open_tickets(conn) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, level, group_name, steam_id, display_name, requested_by,
                   requested_note, status, season, created_at
            FROM support_tickets
            WHERE status IN ('submitted', 'approved', 'applied', 'active')
            ORDER BY FIELD(status, 'submitted', 'approved', 'applied', 'active'),
                     created_at ASC
            """
        )
        return list(cur.fetchall())
