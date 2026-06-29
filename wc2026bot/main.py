import asyncio
import hashlib
import logging
import os
import signal
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from telegram import Update, BotCommand
from telegram.ext import (Application, CommandHandler, MessageHandler,
                          ContextTypes, filters)

from wc2026bot.config import load_settings
from wc2026bot.db import connect, init_db, seed_teams, log_event, snapshot_leaderboard
from wc2026bot.teams import load_teams, by_espn_name, by_fd_name
from wc2026bot.validation import parse_submission, ValidationError
from wc2026bot.feeds.espn import EspnClient
from wc2026bot.feeds.footballdata import FootballDataClient
from wc2026bot.poller import run_poller
from wc2026bot import handlers, notify

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("wc2026bot")


async def run_daily_snapshot(conn, stop_event: asyncio.Event) -> None:
    """Fire snapshot_leaderboard once per UTC day, ~00:05 UTC."""
    from datetime import timezone
    while not stop_event.is_set():
        now = datetime.now(timezone.utc)
        target = now.replace(hour=0, minute=5, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        delay = (target - now).total_seconds()
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
        if stop_event.is_set():
            break
        try:
            inserted = snapshot_leaderboard(conn)
            if inserted > 0:
                log_event(conn, "leaderboard_snapshot")
            log.info("leaderboard snapshot: %d rows", inserted)
        except Exception as e:  # noqa: BLE001
            log.warning("snapshot failed: %s", e)


def build_app() -> tuple:
    try:
        from dotenv import load_dotenv
        load_dotenv()  # load a local .env if present; no-op otherwise
    except ImportError:
        pass
    s = load_settings()
    conn = connect(s.db_path)
    init_db(conn)
    teams_path = Path(__file__).resolve().parent.parent / "data" / "teams.csv"
    teams = load_teams(str(teams_path))
    seed_teams(conn, teams)
    team_names = {t.zindi_id: t.country for t in teams.values()}
    valid_ids = set(teams.keys())
    http = httpx.AsyncClient(timeout=15)
    # FD first (authoritative stage), ESPN last so its fresher live score
    # wins; stage-precedence in apply_result protects FD's known stage.
    fd_client = FootballDataClient(by_fd_name(teams), http, s.footballdata_key)
    clients = [
        fd_client,
        EspnClient(by_espn_name(teams), http),
    ]

    # Warn on startup about teams whose ESPN/FD display names may diverge
    # from teams.csv (especially WC2026 debutants: CPV, CUW, JOR, UZB).
    # Verify manually at their first match by checking feed logs.
    _VERIFY_TEAMS = {"WC-2026_CPV", "WC-2026_CUW", "WC-2026_JOR", "WC-2026_UZB"}
    for tid in _VERIFY_TEAMS:
        t = teams.get(tid)
        if t:
            log.warning(
                "feed-name verification needed at first match — %s: "
                "espn=%r fd=%r", t.iso3, t.espn_name, t.fd_name)

    async def start(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        handlers.register_user(conn, update.effective_chat.id)
        log_event(conn, "start", update.effective_chat.id)
        await update.message.reply_text(handlers.cmd_start_text())

    async def help_cmd(update: Update, _ctx):
        log_event(conn, "help", update.effective_chat.id)
        await update.message.reply_text(handlers.cmd_start_text())

    async def setname(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if not ctx.args:
            await update.message.reply_text("Usage: /setname <your name>")
            return
        try:
            name = handlers.set_display_name(
                conn, update.effective_chat.id, " ".join(ctx.args))
        except handlers.SetNameError as e:
            log_event(conn, "setname_fail", update.effective_chat.id)
            await update.message.reply_text(f"❌ {e}")
            return
        log_event(conn, "setname_ok", update.effective_chat.id)
        await update.message.reply_text(
            f"✅ Name set to '{name}'. Now /upload your predictions.")

    async def me(update: Update, _ctx):
        gate = handlers.needs_name_msg(conn, update.effective_chat.id)
        if gate:
            await update.message.reply_text(gate)
            return
        log_event(conn, "cmd_me", update.effective_chat.id)
        await update.message.reply_text(
            handlers.me_text(conn, update.effective_chat.id))

    async def rank(update: Update, _ctx):
        log_event(conn, "cmd_rank", update.effective_chat.id)
        await update.message.reply_text(handlers.rank_text(conn))

    async def today(update: Update, _ctx):
        log_event(conn, "cmd_today", update.effective_chat.id)
        d = datetime.now().astimezone().date().isoformat()
        await update.message.reply_text(
            handlers.matches_on_text(conn, d, team_names, "today"))

    async def yesterday(update: Update, _ctx):
        log_event(conn, "cmd_yesterday", update.effective_chat.id)
        d = (datetime.now().astimezone().date()
             - timedelta(days=1)).isoformat()
        await update.message.reply_text(
            handlers.matches_on_text(conn, d, team_names, "yesterday"))

    async def scorers(update: Update, _ctx):
        log_event(conn, "cmd_scorers", update.effective_chat.id)
        data = await fd_client.fetch_scorers(limit=10)
        await update.message.reply_text(handlers.scorers_text(data))

    async def standings(update: Update, ctx):
        log_event(conn, "cmd_standings", update.effective_chat.id)
        data = await fd_client.fetch_standings()
        grp = ctx.args[0] if ctx.args else None
        await update.message.reply_text(handlers.standings_text(data, grp))

    async def team(update: Update, ctx):
        gate = handlers.needs_name_msg(conn, update.effective_chat.id)
        if gate:
            await update.message.reply_text(gate)
            return
        if not ctx.args:
            await update.message.reply_text("Usage: /team <ISO3>")
            return
        log_event(conn, "cmd_team", update.effective_chat.id)
        await update.message.reply_text(
            handlers.team_text(conn, update.effective_chat.id,
                               ctx.args[0], team_names))

    async def upload_doc(update: Update, _ctx):
        gate = handlers.needs_name_msg(conn, update.effective_chat.id)
        if gate:
            await update.message.reply_text(gate)
            return
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
            log_event(conn, "upload_fail", update.effective_chat.id)
            await update.message.reply_text(f"❌ {e}")
            return
        handlers.store_submission(
            conn, update.effective_chat.id, rows,
            hashlib.sha256(text.encode()).hexdigest())
        log_event(conn, "upload_ok", update.effective_chat.id)
        await update.message.reply_text(
            "✅ Submission stored. /me for your live standing.")

    async def _post_init(application: Application) -> None:
        cmds = [
            BotCommand("start", "Start the bot"),
            BotCommand("help", "Show help"),
            BotCommand("setname", "Set your team name"),
            BotCommand("upload", "Upload your submission CSV"),
            BotCommand("me", "Your predictions and score"),
            BotCommand("rank", "Your rank on the leaderboard"),
            BotCommand("today", "Today's matches"),
            BotCommand("yesterday", "Yesterday's results"),
            BotCommand("team", "Team info"),
            BotCommand("scorers", "Top scorers"),
            BotCommand("standings", "Group standings"),
            BotCommand("feedback", "Send feedback"),
        ]
        await application.bot.set_my_commands(cmds)
        log.info("registered %d bot commands", len(cmds))

    app = (Application.builder()
           .token(s.bot_token)
           .connect_timeout(10.0)
           .read_timeout(20.0)
           .write_timeout(20.0)
           .pool_timeout(10.0)
           .post_init(_post_init)
           .build())
    async def upload_cmd(update: Update, _ctx: ContextTypes.DEFAULT_TYPE):
        gate = handlers.needs_name_msg(conn, update.effective_chat.id)
        if gate:
            await update.message.reply_text(gate)
            return
        log_event(conn, "upload_prompt", update.effective_chat.id)
        await update.message.reply_text(
            "Send me your submission as a .csv file attachment "
            "(columns: ID, total_goals, Target).")

    async def feedback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        cid = update.effective_chat.id
        text = " ".join(ctx.args) if ctx.args else ""
        if not text:
            await update.message.reply_text(
                "Usage: /feedback <your message>")
            return
        log_event(conn, "feedback", cid)
        log.info("feedback from %s: %s", cid, text)
        if s.feedback_chat_id:
            name = handlers.display_name(conn, cid) or str(cid)
            try:
                await app.bot.send_message(
                    s.feedback_chat_id,
                    f"💬 Feedback from {name} ({cid}):\n{text}")
            except Exception as e:  # noqa: BLE001
                log.warning("feedback forward failed: %s", e)
        await update.message.reply_text(
            "✅ Thanks! Your feedback has been noted.")

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("setname", setname))
    app.add_handler(CommandHandler("upload", upload_cmd))
    app.add_handler(CommandHandler("me", me))
    app.add_handler(CommandHandler("rank", rank))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("yesterday", yesterday))
    app.add_handler(CommandHandler("team", team))
    app.add_handler(CommandHandler("scorers", scorers))
    app.add_handler(CommandHandler("standings", standings))
    app.add_handler(CommandHandler("feedback", feedback))
    app.add_handler(MessageHandler(filters.Document.ALL, upload_doc))

    async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        # Transient network blips (TimedOut, ConnectTimeout) are expected;
        # log one line instead of a full traceback.
        log.warning("update error: %s", ctx.error)

    app.add_error_handler(on_error)

    async def _push(match_ids: list[str], kind: str):
        for mid in match_ids:
            for cid, text in notify.personalized_messages(
                    conn, mid, team_names, kind=kind):
                try:
                    await app.bot.send_message(cid, text)
                    log_event(conn, f"notify_{kind}_ok", cid)
                except Exception as e:  # noqa: BLE001
                    log.warning("push to %s failed: %s", cid, e)
                    log_event(conn, f"notify_{kind}_fail", cid)

    async def on_finished(match_ids: list[str]):
        # DISABLED: Notifications causing excessive polling
        # await _push(match_ids, "finish")
        log.info("match finished: %s (notifications disabled)", match_ids)

    async def on_goal(match_ids: list[str]):
        # DISABLED: Notifications causing excessive polling
        # await _push(match_ids, "goal")
        log.info("goal scored: %s (notifications disabled)", match_ids)

    return app, conn, clients, on_finished, on_goal, http


async def _run():
    import uvicorn
    from wc2026bot.api import create_app as create_api

    app, conn, clients, on_finished, on_goal, http = build_app()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except (NotImplementedError, AttributeError):
            pass  # not supported on this platform (e.g. Windows)

    port = int(os.environ.get("PORT", "8080"))
    api_app = create_api()
    uvi_config = uvicorn.Config(
        api_app, host="0.0.0.0", port=port,
        log_level="info", lifespan="on",
    )
    uvi_server = uvicorn.Server(uvi_config)

    async with app:
        await app.start()
        await app.updater.start_polling()
        poller_task = asyncio.create_task(
            run_poller(conn, clients, on_finished, stop, on_goal=on_goal))
        snapshot_task = asyncio.create_task(
            run_daily_snapshot(conn, stop))
        api_task = asyncio.create_task(uvi_server.serve())
        try:
            await stop.wait()
        finally:
            stop.set()
            uvi_server.should_exit = True
            await poller_task
            await snapshot_task
            await api_task
            await http.aclose()
            await app.updater.stop()
            await app.stop()
            conn.close()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()

