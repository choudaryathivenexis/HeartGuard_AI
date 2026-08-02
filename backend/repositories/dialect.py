"""
Which database is in use, and the small amount of translation that difference needs.

WHY THIS FILE EXISTS
SQLite is the right database for a machine you can point at a file. It is the wrong one
for a serverless host, where the filesystem is read-only and every instance would get
its own copy anyway. Postgres is the right database there and the wrong one to make a
marker install locally. So the application speaks both: SQLite when it is a file on
disk, Postgres when DATABASE_URL says otherwise.

The rest of the repository package is written in ONE dialect — SQLite's, with `?`
placeholders — and this module makes that dialect work on Postgres. Rewriting thirty
queries into a query builder was the alternative; that would have been a larger change
with more places to be wrong, to remove a difference that fits in the four rules below.

THE FOUR DIFFERENCES, AND HOW EACH IS SETTLED

  placeholders   `?` becomes `%s`, by a scanner that knows what a string literal is
                 rather than a blind str.replace. There is no `?` inside a literal in
                 this codebase today; a scanner means there may be one tomorrow.

  timestamps     Both backends store timestamps as TEXT, 'YYYY-MM-DD HH:MM:SS', which
                 is what SQLite's CURRENT_TIMESTAMP produces. Postgres would otherwise
                 hand back datetime objects, and `services/analytics.py` slices the
                 value as a string to group by day — that is a TypeError, not a
                 formatting difference. Storing text keeps every consumer identical.

  new row ids    `cursor.lastrowid` is SQLite's. `insert_returning_id()` uses it there
                 and `RETURNING id` on Postgres.

  row objects    One Row type for both, addressable by name AND position, because the
                 existing code uses both forms.
"""
from __future__ import annotations

import os
import re

__all__ = ["DATABASE_URL", "IS_POSTGRES", "Row", "sqlite_row_factory",
           "pg_row_factory", "to_postgres", "NOW_SQL"]


def _normalise(url: str) -> str:
    """
    Accept the URL shapes hosting providers actually hand out.

    Several of them (Heroku's convention, copied by others) still emit `postgres://`,
    which psycopg rejects outright. Fixing it here rather than asking the operator to
    edit a value they pasted from a dashboard.
    """
    url = (url or "").strip()
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


DATABASE_URL = _normalise(os.environ.get("DATABASE_URL", ""))
IS_POSTGRES = DATABASE_URL.startswith("postgresql://")

# SQLite's CURRENT_TIMESTAMP is UTC and formats as 'YYYY-MM-DD HH:MM:SS'. This is the
# Postgres expression that produces the identical string, used both as the column
# DEFAULT and as the replacement for CURRENT_TIMESTAMP inside translated statements.
NOW_SQL = "to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')"

_CURRENT_TIMESTAMP = re.compile(r"\bCURRENT_TIMESTAMP\b", re.IGNORECASE)


class Row(dict):
    """
    One result row, addressable by column name or by position.

    `sqlite3.Row` supports both, and the repository code uses both: `row["username"]`
    when it wants a field and `row[0]` after a `SELECT COUNT(*)`. A plain dict — which
    is what psycopg's dict_row gives — raises KeyError on `row[0]`, and the failure
    would surface only on the Postgres deployment, on whichever page happened to run a
    COUNT. Supporting both here means neither backend has a special case.

    Ordering is column order: dicts preserve insertion order, and both row factories
    below build from the cursor description.
    """

    __slots__ = ()

    def __getitem__(self, key):
        if isinstance(key, int):
            values = list(self.values())
            try:
                return values[key]
            except IndexError:
                raise IndexError(
                    f"row has {len(values)} column(s), asked for index {key}") from None
        return dict.__getitem__(self, key)


def sqlite_row_factory(cursor, row):
    """Row factory for sqlite3 connections."""
    return Row(zip((column[0] for column in cursor.description), row))


def pg_row_factory(cursor):
    """
    Row factory for psycopg connections.

    psycopg's protocol is two-stage: it calls this once per result set with the cursor,
    and expects a callable back that turns each value sequence into a row.
    """
    description = cursor.description or ()
    names = [column.name for column in description]

    def make_row(values):
        return Row(zip(names, values))

    return make_row


def to_postgres(sql: str, has_params: bool) -> str:
    """
    Rewrite one SQLite statement for Postgres.

    `has_params` controls `%` escaping and is not cosmetic: psycopg treats `%` as the
    start of a placeholder ONLY when parameters are supplied, so escaping it
    unconditionally would corrupt a parameterless statement that contained a literal
    percent sign.

    The scan tracks string literals, including the doubled-quote escape (`'it''s'`), so
    a `?` or a `%` inside quotes is left exactly as written. No query in this codebase
    contains either today — this is here so that adding one is not a silent injection
    of a placeholder into a string.
    """
    sql = _CURRENT_TIMESTAMP.sub(NOW_SQL, sql)

    out: list[str] = []
    in_string = False
    i = 0
    n = len(sql)
    while i < n:
        char = sql[i]

        if in_string:
            if char == "'":
                # A doubled quote is an escaped quote and does NOT end the literal.
                if i + 1 < n and sql[i + 1] == "'":
                    out.append("''")
                    i += 2
                    continue
                in_string = False
            elif char == "%" and has_params:
                out.append("%%")
                i += 1
                continue
            out.append(char)
            i += 1
            continue

        if char == "'":
            in_string = True
        elif char == "?":
            out.append("%s")
            i += 1
            continue
        elif char == "%" and has_params:
            out.append("%%")
            i += 1
            continue

        out.append(char)
        i += 1

    return "".join(out)
