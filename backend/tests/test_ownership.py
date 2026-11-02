"""v17's threat model, exercised end to end: a non-owner (admin or not) must never
observe or affect another user's jobs/tracks through list endpoints or direct-id
endpoints. Direct-id endpoints return 404, never 403, so an id's existence is never
confirmed to a non-owner. The SSE stream's equivalent property is proven from the wire
against the real stack (see the plan's verification section), not here."""

import pytest

from app.models import Job, JobSourceType, JobState, Track, TrackState


def _make_job(db_session, owner, *, state=JobState.EXPANDED):
    job = Job(
        source_url="https://open.spotify.com/album/x",
        source_type=JobSourceType.ALBUM,
        state=state,
        user_id=owner.id,
    )
    db_session.add(job)
    db_session.commit()
    return job


def _make_track(db_session, job, *, state=TrackState.WAITING):
    track = Track(
        job_id=job.id,
        spotify_track_id=f"{job.id}-track",
        song_json={"name": "Song"},
        state=state,
    )
    db_session.add(track)
    db_session.commit()
    return track


def _as(client, cookie: dict[str, str]):
    """Switches the shared `client` fixture to a given identity for the calls that
    follow -- set directly on the client's own jar (clearing first) rather than passed
    per-request, since per-request `cookies=` is deprecated on httpx's TestClient and
    ambiguous about persistence besides."""
    client.cookies.clear()
    client.cookies.update(cookie)
    return client


def test_list_jobs_and_tracks_contain_zero_of_the_other_users_rows(client, db_session, make_user, session_cookie):
    user_a = make_user("a@example.com")
    user_b = make_user("b@example.com")
    cookie_a = session_cookie("a@example.com")
    cookie_b = session_cookie("b@example.com")

    job_a = _make_job(db_session, user_a)
    _make_track(db_session, job_a)
    job_b = _make_job(db_session, user_b)
    _make_track(db_session, job_b)

    jobs_as_b = _as(client, cookie_b).get("/api/jobs").json()["items"]
    assert all(j["id"] != str(job_a.id) for j in jobs_as_b)
    assert any(j["id"] == str(job_b.id) for j in jobs_as_b)

    tracks_as_b = _as(client, cookie_b).get("/api/tracks").json()["items"]
    assert all(t["job_id"] != str(job_a.id) for t in tracks_as_b)

    jobs_as_a = _as(client, cookie_a).get("/api/jobs").json()["items"]
    assert all(j["id"] != str(job_b.id) for j in jobs_as_a)


_DIRECT_ID_CASES = [
    ("GET", "/api/jobs/{job_id}"),
    ("GET", "/api/jobs/{job_id}/tracks"),
    ("DELETE", "/api/jobs/{job_id}"),
    ("GET", "/api/tracks/{track_id}"),
    ("DELETE", "/api/tracks/{track_id}"),
    ("POST", "/api/tracks/{track_id}/retry"),
    ("GET", "/api/tracks/{track_id}/attempts"),
    ("GET", "/api/tracks/{track_id}/file"),
    # v63
    ("PUT", "/api/jobs/{job_id}/watch"),
    ("POST", "/api/jobs/{job_id}/reexpand"),
    ("POST", "/api/jobs/{job_id}/retry-failed"),
    # A non-owner's admin-only flag is still a 404 (the job's existence first), never 403.
    ("POST", "/api/jobs/{job_id}/retry-failed?include_not_found=true"),
]


@pytest.mark.parametrize("method, path_template", _DIRECT_ID_CASES)
def test_direct_id_endpoint_404s_for_non_owner(
    method, path_template, client, db_session, make_user, session_cookie
):
    """Tested endpoint by endpoint (parametrized, not looped-and-asserted-once) -- one
    passing endpoint proves nothing about the others, per the plan's own standard."""
    owner = make_user("owner@example.com")
    stranger_cookie = session_cookie("stranger@example.com")

    job = _make_job(db_session, owner)
    track = _make_track(db_session, job, state=TrackState.WAITING)

    path = path_template.format(job_id=job.id, track_id=track.id)
    kwargs = {"json": {"priority": 1}} if method == "PATCH" else {}
    if method == "PUT":
        kwargs = {"json": {"interval_hours": 24}}

    response = _as(client, stranger_cookie).request(method, path, **kwargs)

    assert response.status_code == 404


def test_direct_id_endpoint_200s_for_the_real_owner(client, db_session, make_user, session_cookie):
    """Sanity check alongside the 404 sweep above: the same job/track *does* resolve for
    its actual owner, so the 404s above are proven to be an ownership check and not a
    routing bug that 404s for everyone."""
    owner = make_user("owner@example.com")
    owner_cookie = session_cookie("owner@example.com")
    job = _make_job(db_session, owner)

    assert _as(client, owner_cookie).get(f"/api/jobs/{job.id}").status_code == 200
    assert _as(client, owner_cookie).get(f"/api/jobs/{job.id}/tracks").status_code == 200
    track = _make_track(db_session, job)
    assert _as(client, owner_cookie).get(f"/api/tracks/{track.id}").status_code == 200


@pytest.mark.parametrize("who", ["owner", "stranger"])
def test_priority_endpoints_404_for_every_non_admin(who, client, db_session, make_user, session_cookie):
    """v48: priority and bump are admin-only, so they left the 404 sweep above. A non-admin
    gets the same answer on their own job and on someone else's, so it confirms nothing
    about a foreign job: v56 (A6) made it an unknown route's 404 (v48's was 403)."""
    owner = make_user("owner@example.com")
    cookie = session_cookie("owner@example.com" if who == "owner" else "stranger@example.com")
    job = _make_job(db_session, owner)

    patched = _as(client, cookie).patch(f"/api/jobs/{job.id}/priority", json={"priority": 1})
    bumped = _as(client, cookie).post(f"/api/jobs/{job.id}/bump")

    assert (patched.status_code, bumped.status_code) == (404, 404)


def test_admin_has_full_read_and_write_access_to_a_foreign_job(client, db_session, make_user, session_cookie):
    owner = make_user("owner@example.com")
    make_user("root@example.com", is_admin=True)
    admin_cookie = session_cookie("root@example.com", is_admin=True)

    job = _make_job(db_session, owner)
    track = _make_track(db_session, job, state=TrackState.WAITING)

    get_response = _as(client, admin_cookie).get(f"/api/jobs/{job.id}")
    assert get_response.status_code == 200
    assert get_response.json()["owner_email"] == "owner@example.com"

    assert _as(client, admin_cookie).post(f"/api/jobs/{job.id}/bump").status_code == 200
    assert _as(client, admin_cookie).post(f"/api/tracks/{track.id}/retry").status_code == 200
    assert _as(client, admin_cookie).get(f"/api/tracks/{track.id}/attempts").status_code == 200
    assert _as(client, admin_cookie).get(f"/api/tracks/{track.id}").json()["job"]["owner_email"] == "owner@example.com"
    assert _as(client, admin_cookie).delete(f"/api/jobs/{job.id}").status_code == 200


def test_download_track_file_404s_for_non_owner_and_200s_for_owner_and_admin(
    client, db_session, make_user, session_cookie
):
    """The generic direct-id sweep above proves the 404 with a file-less track (ownership
    is checked before file resolution, so either gate alone would produce that result).
    This proves the *positive* case for v27's own endpoint specifically: a real file
    resolves for its owner and for an admin, and a stranger still gets 404 even though the
    file genuinely exists."""
    owner = make_user("owner@example.com")
    owner_cookie = session_cookie("owner@example.com")
    stranger_cookie = session_cookie("stranger@example.com")
    make_user("root@example.com", is_admin=True)
    admin_cookie = session_cookie("root@example.com", is_admin=True)

    job = _make_job(db_session, owner)
    track = _make_track(db_session, job, state=TrackState.COMPLETED)
    track.output_path = "/downloads/Song.mp3"
    db_session.commit()

    assert _as(client, owner_cookie).get(f"/api/tracks/{track.id}/file").status_code == 200
    assert _as(client, admin_cookie).get(f"/api/tracks/{track.id}/file").status_code == 200
    assert _as(client, stranger_cookie).get(f"/api/tracks/{track.id}/file").status_code == 404
    # v35 (e): the frontend's HEAD probe goes through the same gate.
    assert _as(client, owner_cookie).head(f"/api/tracks/{track.id}/file").status_code == 200
    assert _as(client, stranger_cookie).head(f"/api/tracks/{track.id}/file").status_code == 404


def test_all_users_flag_from_non_admin_is_silently_ignored(client, db_session, make_user, session_cookie):
    """v54: so is a non-admin's `view=all`/`view=others` -- normalized to `mine`, never 403."""
    owner = make_user("owner@example.com")
    other = make_user("other@example.com")
    owner_cookie = session_cookie("owner@example.com")

    _make_job(db_session, owner)
    _make_job(db_session, other)

    for query in ("all_users=true", "view=all", "view=others", "view=mine"):
        for path in ("/api/jobs", "/api/jobs?scope=track", "/api/tracks"):
            sep = "&" if "?" in path else "?"
            response = _as(client, owner_cookie).get(f"{path}{sep}{query}")
            assert response.status_code == 200, (path, query)
            if path == "/api/jobs":
                owners = {j["owner_email"] for j in response.json()["items"]}
                assert owners == {"owner@example.com"}, query
                assert sum(response.json()["counts_by_status"].values()) == 1, query


def test_admin_default_view_is_own_jobs_only_and_all_users_reveals_the_rest(
    client, db_session, make_user, session_cookie
):
    """v54: `view=mine` is the default, `view=all` (alias `all_users=true`) is everyone's,
    and `view=others` is everyone's but the admin's own."""
    owner = make_user("owner@example.com")
    admin = make_user("root@example.com", is_admin=True)
    admin_cookie = session_cookie("root@example.com", is_admin=True)

    job = _make_job(db_session, owner)
    own_job = _make_job(db_session, admin)

    def ids(query: str) -> set[str]:
        body = _as(client, admin_cookie).get(f"/api/jobs{query}").json()
        assert sum(body["counts_by_status"].values()) == len(body["items"]), query
        return {j["id"] for j in body["items"]}

    assert ids("") == {str(own_job.id)}
    assert ids("?view=mine") == {str(own_job.id)}
    assert ids("?all_users=true") == {str(job.id), str(own_job.id)}
    assert ids("?view=all") == {str(job.id), str(own_job.id)}
    assert ids("?view=others") == {str(job.id)}
    # all_users=false is the alias's "not all": the admin's own, like the default.
    assert ids("?all_users=false") == {str(own_job.id)}


@pytest.mark.parametrize("path", ["/api/jobs", "/api/jobs?scope=track", "/api/tracks", "/api/stream"])
@pytest.mark.parametrize("query", ["all_users=true&view=all", "all_users=false&view=others", "view=mine&all_users=true"])
def test_all_users_and_view_together_is_a_422(client, make_user, session_cookie, path, query):
    """v54: `all_users` stays an alias of `view=all`; naming both is a conflict, whatever the
    identity (the check runs before the non-admin normalization)."""
    make_user("root@example.com", is_admin=True)
    sep = "&" if "?" in path else "?"
    for cookie in (session_cookie("root@example.com", is_admin=True), session_cookie("owner@example.com")):
        response = _as(client, cookie).get(f"{path}{sep}{query}")
        assert response.status_code == 422, (path, query)
        assert response.json()["code"] == "invalid_list_params"


def test_an_unknown_view_is_a_422(client, make_user, session_cookie):
    make_user("root@example.com", is_admin=True)
    _as(client, session_cookie("root@example.com", is_admin=True))
    for path in ("/api/jobs?view=everyone", "/api/tracks?view=theirs", "/api/stream?view=x"):
        assert client.get(path).status_code == 422, path


def test_search_and_scope_track_never_surface_another_users_rows(client, db_session, make_user, session_cookie):
    """v18 adds real new query paths (search, scope=track, status/state filters) --
    exactly the kind of new surface the project's data-separation invariant calls out as
    needing its own re-run of the cross-user sweep, not just the list endpoints v17
    already covered."""
    stranger = make_user("stranger@example.com")
    victim_job = _make_job(db_session, stranger)
    victim_track = Track(
        job_id=victim_job.id,
        spotify_track_id="victim",
        song_json={"name": "VeryUniqueSearchableTitle", "artists": ["Nobody"]},
        state=TrackState.WAITING,
    )
    db_session.add(victim_track)
    db_session.commit()

    attacker_cookie = session_cookie("attacker@example.com")
    _as(client, attacker_cookie)

    # A search term that *does* match the victim's track must still come back empty for
    # a non-owner, non-admin caller -- across every surface that accepts `q`.
    # v54: the admin-only views are no way around it, `others` least of all.
    for path in ("/api/jobs", "/api/jobs?scope=track", "/api/tracks"):
        for view in ("", "&view=all", "&view=others", "&all_users=true"):
            response = client.get(f"{path}{'&' if '?' in path else '?'}q=VeryUniqueSearchableTitle{view}")
            assert response.status_code == 200
            assert response.json()["items"] == [], (path, view)

    # Same for the victim's job's own /{id}/tracks endpoint -- direct-id, must 404.
    assert client.get(f"/api/jobs/{victim_job.id}/tracks?q=VeryUnique").status_code == 404

    # And status/state filters must not become a side channel either.
    for path in (
        "/api/jobs?status=waiting",
        "/api/tracks?state=waiting",
        "/api/tracks?status=waiting&view=others",
        "/api/jobs?status=waiting&view=others",
    ):
        response = client.get(path)
        assert response.status_code == 200
        ids = {item["id"] for item in response.json()["items"]}
        assert str(victim_job.id) not in ids
        assert str(victim_track.id) not in ids


def test_tracks_scope_counts_by_state_are_owner_scoped(client, db_session, make_user, session_cookie):
    """v35 (g): the tracks scope's state-chip counts are a data surface too -- a stranger's
    tracks must never show up in them, through either URL. An admin's default view is its
    own; all_users is honored for an admin only. v54: so are `view=all`/`view=others`, the
    latter excluding the admin's own tracks."""
    owner = make_user("owner@example.com")
    stranger = make_user("stranger@example.com")
    admin = make_user("root@example.com", is_admin=True)
    owner_cookie = session_cookie("owner@example.com")
    stranger_cookie = session_cookie("stranger@example.com")
    admin_cookie = session_cookie("root@example.com", is_admin=True)

    owner_job = _make_job(db_session, owner)
    _make_track(db_session, owner_job, state=TrackState.WAITING)
    _make_track(db_session, owner_job, state=TrackState.COMPLETED)
    stranger_job = _make_job(db_session, stranger)
    for _ in range(3):
        _make_track(db_session, stranger_job, state=TrackState.WAITING)

    for url in ("/api/tracks", "/api/jobs?scope=track"):
        owner_body = _as(client, owner_cookie).get(url).json()
        assert owner_body["counts_by_state"] == {"waiting": 1, "completed": 1}
        stranger_body = _as(client, stranger_cookie).get(url).json()
        assert stranger_body["counts_by_state"] == {"waiting": 3}
        # A non-admin's all_users is silently ignored, counts included.
        sep = "&" if "?" in url else "?"
        ignored = _as(client, owner_cookie).get(f"{url}{sep}all_users=true").json()
        assert ignored["counts_by_state"] == {"waiting": 1, "completed": 1}
        for query in ("all_users=true", "view=all", "view=others"):
            ignored = _as(client, owner_cookie).get(f"{url}{sep}{query}").json()
            assert ignored["counts_by_state"] == {"waiting": 1, "completed": 1}, query
        admin_own = _as(client, admin_cookie).get(url).json()
        assert admin_own["counts_by_state"] == {}
        admin_all = _as(client, admin_cookie).get(f"{url}{sep}all_users=true").json()
        assert admin_all["counts_by_state"] == {"waiting": 4, "completed": 1}

    # The admin's own tracks now exist: `mine` is just them, `all` adds them, `others` doesn't.
    admin_job = _make_job(db_session, admin)
    _make_track(db_session, admin_job, state=TrackState.LOOKUP_FAILED)
    for url in ("/api/tracks", "/api/jobs?scope=track"):
        sep = "&" if "?" in url else "?"
        expected = {
            "view=mine": {"lookup_failed": 1},
            "view=all": {"waiting": 4, "completed": 1, "lookup_failed": 1},
            "all_users=true": {"waiting": 4, "completed": 1, "lookup_failed": 1},
            "view=others": {"waiting": 4, "completed": 1},
        }
        for query, counts in expected.items():
            body = _as(client, admin_cookie).get(f"{url}{sep}{query}").json()
            assert body["counts_by_state"] == counts, (url, query)
            assert len(body["items"]) == sum(counts.values()), (url, query)
        # The job-status subquery takes the same predicate: `others` + a status filter never
        # reaches the admin's own (settled, partial) job.
        others_settled = _as(client, admin_cookie).get(f"{url}{sep}view=others&status=settled").json()
        assert others_settled["items"] == [], url
        mine_settled = _as(client, admin_cookie).get(f"{url}{sep}view=mine&status=settled").json()
        assert len(mine_settled["items"]) == 1, url


def test_admin_stats_is_admin_only_and_hidden_from_everyone_else(
    client, db_session, make_user, session_cookie
):
    """v44: the stats page aggregates every user's attempts, so only the admin may read
    it, and a non-admin gets the same 404 an unknown route gives (not 403): its existence
    isn't confirmed. Both identities live, against the same data."""
    victim = make_user("victim@example.com")
    _make_track(db_session, _make_job(db_session, victim))
    stranger_cookie = session_cookie("stranger@example.com")
    admin_cookie = session_cookie("admin@example.com", is_admin=True)

    for window in ("24h", "7d", "30d"):
        assert _as(client, stranger_cookie).get(f"/api/admin/stats?window={window}").status_code == 404
        admitted = _as(client, admin_cookie).get(f"/api/admin/stats?window={window}")
        assert admitted.status_code == 200
        assert admitted.json()["queue"]["counts"]["waiting"] == 1
        # Counts only: the victim's identity never appears, even to the admin.
        assert "victim@example.com" not in admitted.text


def test_keyboard_preference_is_owner_scoped(client, db_session, make_user, session_cookie):
    """v45: the shortcut off switch is a per-user preference. One user switching it off
    changes nothing for another, the admin included, and neither endpoint takes an id that
    could name someone else's row."""
    alice_cookie = session_cookie("alice@example.com")
    bob_cookie = session_cookie("bob@example.com")
    admin_cookie = session_cookie("admin@example.com", is_admin=True)

    assert _as(client, alice_cookie).patch(
        "/api/settings/keyboard", json={"keyboard_shortcuts": False}
    ).json() == {"keyboard_shortcuts": False}

    for cookie in (bob_cookie, admin_cookie):
        assert _as(client, cookie).get("/api/settings/keyboard").json() == {"keyboard_shortcuts": True}
        assert _as(client, cookie).get("/api/auth/me").json()["keyboard_shortcuts"] is True

    # The admin switching theirs doesn't reach Alice's either way.
    _as(client, admin_cookie).patch("/api/settings/keyboard", json={"keyboard_shortcuts": True})
    assert _as(client, alice_cookie).get("/api/auth/me").json()["keyboard_shortcuts"] is False
    assert _as(client, bob_cookie).patch(
        "/api/settings/keyboard", json={"keyboard_shortcuts": True}
    ).json() == {"keyboard_shortcuts": True}
    assert _as(client, alice_cookie).get("/api/settings/keyboard").json() == {"keyboard_shortcuts": False}


def test_language_preference_is_owner_scoped(client, db_session, make_user, session_cookie):
    """v46: the interface language is a per-user preference, like v45's shortcut switch. One
    user choosing Hungarian changes nothing for another, the admin included, and neither
    endpoint takes an id that could name someone else's row."""
    alice_cookie = session_cookie("alice@example.com")
    bob_cookie = session_cookie("bob@example.com")
    admin_cookie = session_cookie("admin@example.com", is_admin=True)

    assert _as(client, alice_cookie).patch(
        "/api/settings/language", json={"language": "hu"}
    ).json() == {"language": "hu"}

    for cookie in (bob_cookie, admin_cookie):
        assert _as(client, cookie).get("/api/settings/language").json() == {"language": None}
        assert _as(client, cookie).get("/api/auth/me").json()["language"] is None

    # The admin and Bob choosing theirs don't reach Alice's.
    _as(client, admin_cookie).patch("/api/settings/language", json={"language": "en"})
    assert _as(client, bob_cookie).patch(
        "/api/settings/language", json={"language": "en"}
    ).json() == {"language": "en"}
    assert _as(client, alice_cookie).get("/api/auth/me").json()["language"] == "hu"
    assert _as(client, alice_cookie).get("/api/settings/language").json() == {"language": "hu"}



def test_clock_preference_is_owner_scoped(client, db_session, make_user, session_cookie):
    """v46: the time format is per user, like the language: one user pinning 24-hour changes
    nothing for another, the admin included, and no endpoint takes an id."""
    alice_cookie = session_cookie("alice@example.com")
    bob_cookie = session_cookie("bob@example.com")
    admin_cookie = session_cookie("admin@example.com", is_admin=True)

    assert _as(client, alice_cookie).patch("/api/settings/clock", json={"clock": "24h"}).json() == {
        "clock": "24h"
    }
    for cookie in (bob_cookie, admin_cookie):
        assert _as(client, cookie).get("/api/settings/clock").json() == {"clock": None}
        assert _as(client, cookie).get("/api/auth/me").json()["clock"] is None

    _as(client, admin_cookie).patch("/api/settings/clock", json={"clock": "12h"})
    assert _as(client, alice_cookie).get("/api/auth/me").json()["clock"] == "24h"


def test_v63_job_actions_leave_a_foreign_job_untouched(client, db_session, make_user, session_cookie, monkeypatch):
    """v63's watch, "check now" and "retry failed", by a non-admin on someone else's job:
    a 404, and nothing changed (no watch, no run, the waiting track's slot as it was)."""
    from datetime import datetime, timedelta, timezone

    from app.models import JobSourceType
    from app.tasks import expand as expand_task

    sent = []
    monkeypatch.setattr(expand_task.expand_job, "delay", lambda *a, **k: sent.append(a))
    owner = make_user("owner@example.com")
    stranger = _as(client, session_cookie("stranger@example.com"))
    job = _make_job(db_session, owner)
    job.source_type = JobSourceType.PLAYLIST
    track = _make_track(db_session, job, state=TrackState.WAITING)
    slot = datetime.now(timezone.utc) + timedelta(hours=4)
    track.scheduled_at = slot
    db_session.commit()

    assert stranger.put(f"/api/jobs/{job.id}/watch", json={"interval_hours": 24}).status_code == 404
    assert stranger.post(f"/api/jobs/{job.id}/reexpand").status_code == 404
    assert stranger.post(f"/api/jobs/{job.id}/retry-failed").status_code == 404

    db_session.refresh(job)
    db_session.refresh(track)
    assert job.watch_interval_hours is None and job.last_expanded_at is None
    assert track.scheduled_at == slot
    assert sent == []
