import asyncio
import hashlib
import logging
import signal
from pathlib import Path

import httpx
from telegram import Update
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          ContextTypes, filters)

from wc2026bot.config import load_settings
from wc2026bot.db import connect, init_db, seed_teams
from wc2026bot.teams import load_teams, by_espn_name, by_fd_name
from wc2026bot.validation import parse_submission, ValidationError
from wc2026bot.feeds.espn import EspnClient
from wc2026bot.feeds.footballdata import FootballDataClient
from wc2026bot.poller import run_poller
from wc2026bot import handlers, notify

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("wc2026bot")


def build_app() -> tuple:
    s = load_settings()
    conn = connect(s.db_path)
    init_db(conn)
    teams_path = Path(__file__).resolve().parent.parent / "data" / "teams.csv"
    teams = load_teams(str(teams_path))
    seed_teams(conn, teams)
    team_names = {t.zindi_id: t.country for t in teams.values()}
    valid_ids = set(teams.keys())
    http = httpx.AsyncClient(timeout=15)
    clients = [
        EspnClient(by_espn_name(teams), http),
        FootballDataClient(by_fd_name(teams), http, s.footballdata_key),
    ]

    async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        handlers.register_user(conn, update.effective_chat.id)
        await update.message.reply_text(handlers.cmd_start_text())

    async def help_cmd(update: Update, _ctx):
        await update.message.reply_text(handlers.cmd_start_text())

    async def me(update: Update, _ctx):
        await update.message.reply_text(
            handlers.me_text(conn, update.effective_chat.id))

    async def rank(update: Update, _ctx):
        await update.message.reply_text(handlers.rank_text(conn))

    async def team(update: Update, ctx):
        if not ctx.args:
            await update.message.reply_text("Usage: /team <ISO3>")
            return
        await update.message.reply_text(
            handlers.team_text(conn, update.effective_chat.id,
                               ctx.args[0], team_names))

    async def upload_doc(update: Update, _ctx):
        doc = update.message.document
        if doc is None:
            await update.message.reply_text("Reply with a .csv file.")
            return
        f = await doc.get_file()
        data = await f.download_as_bytearray()
        text = bytes(data).decode("utf-8", errors="replace")
        try:
            rows = parse_submission(text, valid_ids)
        except ValidationError as e:
            await update.message.reply_text(f"❌ {e}")
            return
        handlers.store_submission(
            conn, update.effective_chat.id, rows,
            hashlib.sha256(text.encode()).hexdigest())
        await update.message.reply_text(
            "✅ Submission stored. /me for your live standing.")

    app = Application.builder().token(s.bot_token).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("team", team))
    app.add_handler(MessageHandler(filters.Document.ALL, upload_doc))

    async def on_finished(match_ids: list[str]):
        for mid in match_ids:
            msg = notify.build_finish_message(conn, mid, team_names)
            for cid in notify.affected_users(conn, mid):
                try:
                    await app.bot.send_message(cid, msg)
                except Exception as e:  # noqa: BLE001
                    log.warning("push to %s failed: %s", cid, e)

    return app, conn, clients, on_finished, http


async def _run():
    app, conn, clients, on_finished, http = build_app()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, AttributeError):
            pass  # not supported on this platform (e.g. Windows)
    async with app:
        await app.start()
        await app.updater.start_polling()
        poller_task = asyncio.create_task(
            run_poller(conn, clients, on_finished, stop))
        try:
            await stop.wait()
        finally:
            stop.set()
            await poller_task
            await http.aclose()
            await app.updater.stop()
            await app.stop()
            conn.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
