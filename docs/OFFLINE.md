# Running Peopleopslab offline

The product runs on one computer. There is no hosted copy: the Render services
and their configuration were retired on 14 November 2026. Nothing in a running
installation calls out to the internet, and the payroll data never leaves the
machine it is on.

## What you need

- **Docker Desktop** (Windows or Mac) or Docker Engine (Linux), running.
- This repository on the computer.
- Internet **once**, for the first start: Docker downloads the Postgres,
  Python and Node base images and the build installs the libraries. After
  that the computer can stay disconnected.

## Start, stop, back up

| | Windows | Mac / Linux |
|---|---|---|
| Start | double-click `offline\start.bat` | `offline/start.sh` |
| Stop | `offline\stop.bat` | `offline/stop.sh` |
| Back up | `offline\backup.bat` | `offline/backup.sh` |

Start builds the app the first time (a few minutes) and then opens it on
**http://localhost:3000**. There is no sign-in: it opens on the dashboard.

Stopping keeps the data. The app also comes back by itself when the computer
or Docker restarts, until you run stop.

Back up writes the whole database to a dated `.sql` file in
`offline/backups/`. That folder is not in git. Copy the file somewhere else —
a backup on the same disk as the data is not a backup.

## Where the data is

In a Docker volume named `docker_pgdata` on this computer. It survives stop,
start, rebuild and an update of the code.

**It is deleted by** `docker compose -f docker/docker-compose.yml down -v`, by
"Clean / Purge data" in Docker Desktop, and by uninstalling Docker. Back up
first.

To restore a backup into a fresh installation, start the app once, stop the
API, and load the file:

```bash
docker compose -f docker/docker-compose.yml stop backend
docker compose -f docker/docker-compose.yml exec -T db sh -c 'psql -U "$POSTGRES_USER" -c "DROP DATABASE \"$POSTGRES_DB\"" -c "CREATE DATABASE \"$POSTGRES_DB\"" postgres'
docker compose -f docker/docker-compose.yml exec -T db sh -c 'psql -U "$POSTGRES_USER" "$POSTGRES_DB"' < offline/backups/<file>.sql
docker compose -f docker/docker-compose.yml start backend
```

## Who can reach it

Only this computer. The web app, the API and Postgres are published on
`127.0.0.1`, so another machine on the same network cannot open them.

That matters because sign-in is off: anyone who can open the page can read and
change everything in it. To let colleagues use it from their own computers,
turn sign-in back on first, then open it to the network:

```bash
AUTH_DISABLED=0 BIND_ADDRESS=0.0.0.0 docker compose -f docker/docker-compose.yml up -d --build
```

On Windows, put `AUTH_DISABLED=0` and `BIND_ADDRESS=0.0.0.0` in a file named
`.env` in the `docker` folder instead, and run `offline\start.bat`.

## What does not work offline

- **PeopleOps Studio connections and webhooks** that reach another system need
  a network path to that system. Nothing else in the product makes an outbound
  call.
- **Statutory rates do not update themselves.** They are whatever this copy of
  the code and your configuration say. When the law changes, update the code or
  the configuration; `docs/STATUTORY_RATE_AUDIT.md` records what was last
  checked and when.
- **Email** (invitations, password resets) was never sent by the product; with
  sign-in off it is not needed.

## Updating

Get the new code (`git pull`), then run start again. It rebuilds what changed
and keeps the data. Back up before an update.

## What was retired

`render.yaml`, `railway.json` and `backend/Procfile` are removed from the
repository. `DEPLOYMENT.md`, `docs/GO_LIVE.md`, `docs/DATABASE_MIGRATION.md`
and the hosting parts of `docs/handbook.html` and `docs/SECURITY.md` describe
the hosted setup as it was; they are kept as a record and are not how the
product runs now.
