"""
Proves the request path makes no network calls.

This is the load-bearing guarantee of the whole design: if any endpoint still
reaches upstream, the app cannot be hosted for free (stats.nba.com blocks
datacenter IPs) and will break under rate limiting. On a developer laptop a
stray call succeeds silently, so this test severs the socket layer first and
makes any residual call fail loudly.

    python scripts/check_offline.py
"""

import os
import socket
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))


class NetworkBlocked(RuntimeError):
    pass


def sever_network():
    """Break outbound sockets while leaving the in-process test transport alone."""
    def _blocked(*a, **kw):
        raise NetworkBlocked("request path attempted a network call")

    socket.socket.connect = _blocked
    socket.create_connection = _blocked
    socket.getaddrinfo = _blocked


def main():
    # Load the snapshot BEFORE cutting the network: startup is allowed to
    # download it, the request path is not allowed to fetch anything.
    from app import store
    try:
        store.load()
    except store.SnapshotUnavailable as e:
        print(f"FAIL: {e}")
        return 1

    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    # Warm the app up (lifespan runs) while the network still works.
    client.get("/health")

    sever_network()
    print("Network severed. Exercising every endpoint...\n")

    pid = store.search_players("jokic")[0]["id"]
    any_team = store._db().execute(
        "SELECT team_id FROM players WHERE team_id IS NOT NULL LIMIT 1"
    ).fetchone()[0]

    checks = [
        ("GET /",                       "/"),
        ("GET /health",                 "/health"),
        ("GET /players/search",         "/players/search?q=curry"),
        ("GET /players/{id}/stats",     f"/players/{pid}/stats"),
        ("GET /injuries",               "/injuries"),
        ("GET /teams/defense-ratings",  "/teams/defense-ratings"),
        ("GET /games/today",            "/games/today"),
        ("GET /games/upcoming",         "/games/upcoming"),
        ("GET /teams/{id}/players",     f"/teams/{any_team}/players"),
    ]

    failures = []
    for label, path in checks:
        try:
            r = client.get(path)
        except NetworkBlocked as e:
            print(f"  {label:<30} NETWORK CALL — {e}")
            failures.append(f"{label}: made a network call")
            continue
        except Exception as e:
            print(f"  {label:<30} ERROR {type(e).__name__}: {e}")
            failures.append(f"{label}: {type(e).__name__}")
            continue

        body = r.json()
        size = len(body) if isinstance(body, (list, dict)) else 1
        ok = r.status_code == 200
        # /games/today is legitimately empty out of season.
        empty_ok = path.startswith("/games")
        if ok and not size and not empty_ok:
            ok = False
        print(f"  {label:<30} {r.status_code}  n={size}  {'OK' if ok else 'EMPTY/FAIL'}")
        if not ok:
            failures.append(f"{label}: status={r.status_code} size={size}")

    # 404s must still work offline.
    r = client.get("/players/999999/stats")
    print(f"  {'GET unknown player -> 404':<30} {r.status_code}  "
          f"{'OK' if r.status_code == 404 else 'FAIL'}")
    if r.status_code != 404:
        failures.append("unknown player did not 404")

    print("\n" + "=" * 62)
    if failures:
        print("OFFLINE CHECK FAILED:")
        for f in failures:
            print("  -", f)
        return 1
    print("OFFLINE CHECK PASSED — every endpoint served with the network severed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
