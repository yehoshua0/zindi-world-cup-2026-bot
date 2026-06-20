# WC2026 Telegram Live Tracker

Live tracker for the Zindi World Cup 2026 Goal Prediction Challenge.

## Setup
    python -m venv .venv && . .venv/Scripts/activate
    pip install -r requirements.txt
    python scripts/build_teams_csv.py

## Run
    BOT_TOKEN=xxx DB_PATH=wc2026.db FOOTBALLDATA_KEY=yyy python -m wc2026bot.main

`FOOTBALLDATA_KEY` is optional (ESPN works keyless).

## Test
    pytest -q

Locally you can instead copy `.env.example` to `.env` and just run
`python -m wc2026bot.main` (the entrypoint loads `.env`).

## Deploy to Railway

Always-on single process via long-polling — **no public URL / web port needed**.
Run it as a **Worker**, not a Web service.

1. **Install the CLI and log in**

       npm i -g @railway/cli
       railway login

2. **Create the project and deploy from this directory** (no GitHub required)

       railway init            # create a new project
       railway up              # build with Nixpacks + deploy (uses the Procfile)

   `Procfile` declares `worker: python -m wc2026bot.main`. `runtime.txt` pins
   Python 3.11. `data/teams.csv` is committed, so no build step is required.

3. **Add a persistent volume** (Railway dashboard → service → Variables/Volumes →
   New Volume). Mount path: `/data`. This is where SQLite lives so uploads
   survive redeploys.

4. **Set environment variables** (dashboard → Variables):

   | Variable | Value |
   |---|---|
   | `BOT_TOKEN` | your @BotFather token |
   | `FOOTBALLDATA_KEY` | your football-data.org token |
   | `DB_PATH` | `/data/wc2026.db` (on the mounted volume) |

5. **Redeploy** after setting vars. Tail logs with `railway logs`.

**Do not scale beyond 1 instance** — SQLite is single-writer; a second
instance would split the database. Keep replicas = 1.

When the tournament ends (after 2026-07-19) you can pause or delete the service.
