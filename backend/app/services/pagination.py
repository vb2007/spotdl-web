"""Generic cursor (keyset) pagination -- shared by every v18 listing endpoint.

Offset pagination silently skips/duplicates rows when the underlying table is being
written to concurrently (jobs/tracks change state constantly while a user pages through
them), which is exactly the failure mode v18's plan calls out. Keyset pagination on
`(sort_key, id)` doesn't have that problem: each page's cursor is "everything strictly
after this exact row" in the current ordering, so a row inserted or mutated elsewhere in
the table never shifts where an already-issued cursor resumes.

Deliberately not built on SQL row-value comparison (`(a, b) > (c, d)`): that construct
breaks the moment `a` can be NULL, because SQL's three-valued logic makes `NULL > x`
neither true nor false -- exactly the case a nullable sort key (e.g. `next_retry_at`)
hits for every non-waiting job. The explicit OR/AND expansion below handles the NULLS
LAST group as a second, separately-ordered partition instead of folding it into one
tuple comparison, and works identically on Postgres and the test suite's SQLite engine.
"""

import base64
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, and_, or_

CAP = 1000  # limit ceiling; a client asking for more gets clamped, not rejected
DEFAULT_LIMIT = 50


class InvalidCursor(ValueError):
    pass


def _encode_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return {"$dt": value.isoformat()}
    if isinstance(value, uuid.UUID):
        # Self-describing, not a bare `str(value)` -- the row id is always a UUID and
        # must decode back into one (the id column's bind parameter needs an actual
        # `uuid.UUID`, not a string that merely looks like one), while an ordinary string
        # sort key (e.g. title) must decode back as plain text.
        return {"$uuid": str(value)}
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and "$dt" in value:
        return datetime.fromisoformat(value["$dt"])
    if isinstance(value, dict) and "$uuid" in value:
        return uuid.UUID(value["$uuid"])
    return value


def encode_cursor(parts: tuple[Any, ...]) -> str:
    payload = json.dumps([_encode_value(p) for p in parts], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[Any, ...]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        if not isinstance(payload, list):
            raise ValueError("cursor payload is not a list")
        return tuple(_decode_value(p) for p in payload)
    except Exception as exc:
        raise InvalidCursor(f"malformed cursor: {cursor!r}") from exc


@dataclass
class SortKey:
    """One sort dimension. `expr` is the SQL expression to order/filter by. `nullable`
    switches on NULLS-LAST handling: a NULL always sorts after every non-NULL value,
    regardless of `dir` -- there's no meaningful "ascending" vs "descending" position for
    e.g. a job with no upcoming retry, it's simply not applicable rather than smaller or
    larger than one that has a value."""

    expr: ColumnElement
    nullable: bool = False


def cursor_for_row(sort_value: Any, row_id: Any, *, nullable: bool = False) -> str:
    if nullable:
        return encode_cursor((sort_value is None, sort_value, row_id))
    return encode_cursor((sort_value, row_id))


def order_by_clauses(sort_key: SortKey, id_column: ColumnElement, *, descending: bool) -> list[ColumnElement]:
    direction = (lambda c: c.desc()) if descending else (lambda c: c.asc())
    if sort_key.nullable:
        # `expr IS NULL` is a boolean (False < True on every backend we run against), so
        # ordering by it ascending first always groups non-NULL rows before NULL ones,
        # independent of `descending` -- which only affects ordering *within* each group.
        return [sort_key.expr.is_(None).asc(), direction(sort_key.expr), direction(id_column)]
    return [direction(sort_key.expr), direction(id_column)]


def _non_nullable_where(expr: ColumnElement, id_column: ColumnElement, cursor_val: Any, cursor_id: Any, *, descending: bool):
    if descending:
        return or_(expr < cursor_val, and_(expr == cursor_val, id_column < cursor_id))
    return or_(expr > cursor_val, and_(expr == cursor_val, id_column > cursor_id))


def apply_cursor(
    stmt: Select,
    sort_key: SortKey,
    id_column: ColumnElement,
    *,
    descending: bool,
    cursor: str | None,
) -> Select:
    stmt = stmt.order_by(*order_by_clauses(sort_key, id_column, descending=descending))
    if cursor is None:
        return stmt

    if sort_key.nullable:
        values = decode_cursor(cursor)
        if len(values) != 3:
            raise InvalidCursor(f"cursor has {len(values)} parts, expected 3")
        cursor_is_null, cursor_val, cursor_id = values
        if cursor_is_null:
            # Already in the NULLS-LAST partition -- only later NULL rows remain, in id
            # order; non-NULL rows never reappear since they all sort strictly earlier.
            id_cmp = id_column < cursor_id if descending else id_column > cursor_id
            where = and_(sort_key.expr.is_(None), id_cmp)
        else:
            # Still in the non-NULL partition: remaining non-NULL rows after the cursor,
            # then -- unconditionally, since NULLs always sort after every non-NULL
            # value -- every NULL row (ORDER BY still places them last on this page).
            remaining_non_null = and_(sort_key.expr.isnot(None), _non_nullable_where(
                sort_key.expr, id_column, cursor_val, cursor_id, descending=descending
            ))
            where = or_(remaining_non_null, sort_key.expr.is_(None))
        return stmt.where(where)

    values = decode_cursor(cursor)
    if len(values) != 2:
        raise InvalidCursor(f"cursor has {len(values)} parts, expected 2")
    cursor_val, cursor_id = values
    return stmt.where(_non_nullable_where(sort_key.expr, id_column, cursor_val, cursor_id, descending=descending))


def clamp_limit(limit: int) -> int:
    return max(1, min(limit, CAP))
