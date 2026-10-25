"""The admin's three-way list scope (v54): `mine`, `all`, `others`.

One resolver for every endpoint that takes it (`GET /api/jobs`, `GET /api/tracks`,
`GET /api/stream`), and one predicate for every query that filters on it, so the job list,
the track list and its job-status subquery can never disagree about who "others" are.

The view is decided from the session, never trusted from the client (v17's threat model): a
non-admin asking for `all` or `others` is silently normalized to `mine`, exactly as a
non-admin's `all_users=true` always was.
"""

from typing import Literal

from app.errors import ApiError

View = Literal["mine", "all", "others"]


def resolve_view(view: View | None, all_users: bool | None, *, is_admin: bool) -> View:
    """`all_users` is kept as an alias of `view=all`; naming both is a conflict (422) even when
    they'd agree, since a caller sending both has two sources of truth for one setting."""
    if view is not None and all_users is not None:
        reason = "pass either view or all_users, not both"
        raise ApiError(422, "invalid_list_params", reason, {"reason": reason})
    if view is None:
        view = "all" if all_users else "mine"
    return view if is_admin else "mine"


def owner_condition(column, view: View, user_id):
    """The WHERE clause `view` puts on a job-owner column, or None for no filter (`all`)."""
    if view == "all":
        return None
    if view == "others":
        return column != user_id
    return column == user_id
