# RAV4 Tracker

Checks Toyota inventory for the configured RAV4 criteria, persists every VIN it
has seen in SQLite, posts Discord updates, and records an append-only audit log.

`tracker.py` is deliberately only the stable executable entry point. The
application code lives in `rav4_tracker/`:

- `inventory.py` — browser capture of Toyota GraphQL responses, response
  validation, and client-side filters.
- `store.py` — SQLite schema, migration, and vehicle upserts.
- `notifications.py` — Discord formatting/delivery and Healthchecks.io pings.
- `audit.py` — append-only `data/run_history.jsonl` records.
- `app.py` — the scan workflow that joins those pieces together.

## Configuration

Edit the non-secret search criteria in `config.py`. Keep secrets out of Git:

- `DISCORD_WEBHOOK_URL`
- `HEALTHCHECK_URL`
- browser settings such as `BROWSER_EXECUTABLE_PATH` and `CHROME_PROFILE_DIR`

On the RevPi these are supplied by
`/home/pi/.config/rav4-tracker/tracker.env`; the systemd service runs
`tracker.py` every 20 minutes.

## Development checks

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python tracker.py
```

The full tracker command opens the configured persistent browser profile and
sends the normal real notifications. Unit tests do not make external requests.
