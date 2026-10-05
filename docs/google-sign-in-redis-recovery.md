# Google sign-in: recover an interrupted Redis session write

## Confirmed incident

The supplied production logs identify the failure on 2026-10-05 at 11:06 Israel
time (08:06 UTC). The screenshot shows the existing `unavailable` sign-in message.

| Israel time | Recorded outcome |
| --- | --- |
| 11:06:10 | Google start returns 303 |
| 11:06:13 | Google's token endpoint returns 200 |
| 11:06:16 | Redis loses its connection while writing the session transaction |
| 11:06:16 | The callback catches the failure and redirects to sign-in |
| 11:06:17 | Anonymous session discovery returns 200 |

The exception is `redis.exceptions.ConnectionError: Error UNKNOWN while writing
to socket. Connection lost.` It escapes `RefreshTokenStore.create_session()` at
`pipe.execute()` after Google verification and the local identity write. This
trace contains no 403; the successful session-discovery request in the screenshot
does not mean a login session was created.

The process shares a Redis pool built with `ConnectionPool.from_url`. In the
installed redis-py 8.1.0, that pool's connections default to zero retries when no
retry policy is supplied. The standalone `Redis` client has a different default,
which is also used by the existing fakeredis fixture. The regression explicitly
matches the production pool's retry policy.

The logs establish where the connection was lost, but not why the remote socket
closed. A stale pooled socket or a network interruption can both cause this error.

## Plan and implementation

1. Reproduce the recorded failure through the real OAuth start/callback/session
   endpoints, injecting a Redis transport failure only at the session transaction.
2. Retry only the session write, once, using the same unpublished token, family ID,
   timestamps, and metadata. Keep the existing transactional HSET/SADD/EXPIRE
   commands so a lost acknowledgement cannot create a second family.
3. Let redis-py discard the broken connection and rebuild the pipeline, whose queued
   commands are cleared after execution. Keep the existing connection/socket timeouts.
4. Propagate a second connection/timeout failure, authentication or authorization
   failure, and command errors. Issue no auth cookies without a successful write.
5. Verify new and returning users, lost writes and replies, bounded failure, refresh,
   logout, and a later successful attempt after an outage. Review and run CI.

The retry belongs in `server/app/stores/refresh_tokens.py`, where this write's
replay behavior is known. It never re-exchanges Google's single-use authorization
code, reruns account creation, or enables retries for unrelated Redis operations.
The warning records the retry without credentials or exception payloads.

[Redis's production guidance](https://redis.io/docs/latest/develop/clients/redis-py/produsage/)
recommends retries for transient connection failures; this implementation limits
them to the session transaction that can safely reuse its original values.

## Regression evidence

The first callback regression failed before the fix with:

```text
Expected: /onboarding
Actual:   /signin?error=unavailable
redis.exceptions.ConnectionError: Error UNKNOWN while writing to socket. Connection lost.
```

It passed after adding the store-level retry. The expanded cases execute real
routes, identity/session services, JWTs, and Redis transactions; Google responses,
SQLite, and fakeredis substitute the external services. A lost-reply case sends
the full transaction to fakeredis before injecting the connection error, exercising
replay after a committed write rather than only retry before a write.

Run from `server`:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_auth_first_session.py -q -p no:cacheprovider
```

The fix recovers one transient Redis failure. A persistent Redis outage still
returns the existing unavailable screen, with no authentication cookies. Production
verification of the deployed change requires a subsequent real Google sign-in.

Local verification: **442 passed, 1 skipped** across the backend suite, including
13 new connection-failure cases. Ruff passes. No production settings or deployment
were changed during this investigation.
