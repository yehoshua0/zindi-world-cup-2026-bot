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

## Deploy (Railway / Fly / Render)
Single always-on process. Set env vars `BOT_TOKEN`, `DB_PATH`,
optional `FOOTBALLDATA_KEY`. Long-polling — no public URL required.
Persist `DB_PATH` on a volume.
