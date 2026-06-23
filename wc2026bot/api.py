"""Public REST API — leaderboard, web upload, feedback.

Runs as a uvicorn task inside the same asyncio loop as the Telegram bot.
All DB calls are wrapped in asyncio.to_thread (check_same_thread=False set).
A separate SQLite connection is used (WAL mode allows concurrent readers).
"""

import asyncio
import hashlib
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from wc2026bot.db import connect
from wc2026bot.notify import cohort_scores, user_metrics
from wc2026bot.validation import ValidationError, parse_submission

# ── State ─────────────────────────────────────────────────

_conn: sqlite3.Connection | None = None

NAME_MIN, NAME_MAX = 2, 32


# ── Lifespan ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _conn
    db_path = os.environ.get("DB_PATH", "wc2026.db")
    _conn = connect(db_path)
    yield
    if _conn:
        _conn.close()
        _conn = None


# ── App factory ───────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(title="WC2026 Tracker API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "https://heoshua.com",
            "https://www.heoshua.com",
            "http://localhost:3000",
            "http://localhost:3001",
        ],
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # ── Leaderboard ──────────────────────────────────────

    @app.get("/leaderboard")
    async def leaderboard():
        def _fetch():
            assert _conn is not None
            scores = cohort_scores(_conn)
            result = []
            for s in scores:
                row = _conn.execute(
                    "SELECT display_name FROM users WHERE user_id=?",
                    (s.user_id,),
                ).fetchone()
                name = (
                    row["display_name"]
                    if row and row["display_name"]
                    else f"user_{s.user_id}"
                )
                result.append({
                    "rank": s.rank,
                    "name": name,
                    "score": round(s.combined, 4),
                    "rmse": round(s.raw_rmse, 4),
                    "f1": round(s.f1, 4),
                })
            return result

        return await asyncio.to_thread(_fetch)

    # ── Web upload ───────────────────────────────────────

    @app.post("/upload", status_code=201)
    async def upload_csv(
        file: UploadFile = File(...),
        session_id: str = Form(...),
        name: str = Form(...),
    ):
        name = " ".join(name.split())
        if not (NAME_MIN <= len(name) <= NAME_MAX):
            raise HTTPException(
                400, f"Name must be {NAME_MIN}-{NAME_MAX} characters")

        raw = await file.read()
        text = raw.decode("utf-8", errors="replace")

        class _NameTaken(Exception):
            pass

        def _process():
            assert _conn is not None
            valid_ids = {
                r["team_id"]
                for r in _conn.execute("SELECT team_id FROM teams_state")
            }
            try:
                rows = parse_submission(text, valid_ids)
            except ValidationError as exc:
                raise ValueError(str(exc)) from exc

            # Name uniqueness: allow if the same session already holds it
            clash = _conn.execute(
                "SELECT web_session_id FROM users "
                "WHERE display_name=? COLLATE NOCASE",
                (name,),
            ).fetchone()
            if clash and clash["web_session_id"] != session_id:
                raise _NameTaken(
                    f"'{name}' is already taken. Pick another name.")

            # Upsert web user
            _conn.execute(
                """
                INSERT INTO users(web_session_id, display_name) VALUES (?, ?)
                ON CONFLICT(web_session_id)
                  DO UPDATE SET display_name=excluded.display_name
                """,
                (session_id, name),
            )
            _conn.commit()

            user_id = _conn.execute(
                "SELECT user_id FROM users WHERE web_session_id=?",
                (session_id,),
            ).fetchone()["user_id"]

            # Deactivate previous submissions, insert new one
            _conn.execute(
                "UPDATE submissions SET is_active=0 WHERE user_id=?", (user_id,))
            cur = _conn.execute(
                "INSERT INTO submissions(user_id, file_hash, is_active) "
                "VALUES (?,?,1)",
                (user_id, hashlib.sha256(text.encode()).hexdigest()),
            )
            sub_id = cur.lastrowid
            _conn.executemany(
                "INSERT INTO predictions"
                "(submission_id, team_id, predicted_goals, predicted_stage) "
                "VALUES (?,?,?,?)",
                [(sub_id, r.team_id, r.total_goals, r.target) for r in rows],
            )
            _conn.commit()

            rmse_val, f1_val = user_metrics(_conn, sub_id)
            scores = cohort_scores(_conn)
            rank = next(
                (s.rank for s in scores if s.user_id == user_id), len(scores))
            return {
                "name": name,
                "rmse": round(rmse_val, 4),
                "f1": round(f1_val, 4),
                "rank": rank,
                "total": len(scores),
            }

        try:
            return await asyncio.to_thread(_process)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except _NameTaken as exc:
            raise HTTPException(409, str(exc)) from exc

    # ── My score ────────────────────────────────────────

    @app.get("/me")
    async def my_score(session_id: str):
        def _fetch():
            assert _conn is not None
            row = _conn.execute(
                """
                SELECT u.user_id, u.display_name, s.submission_id
                FROM users u
                JOIN submissions s
                  ON s.user_id=u.user_id AND s.is_active=1
                WHERE u.web_session_id=?
                """,
                (session_id,),
            ).fetchone()
            if not row:
                return None
            rmse_val, f1_val = user_metrics(_conn, row["submission_id"])
            scores = cohort_scores(_conn)
            rank = next(
                (s.rank for s in scores if s.user_id == row["user_id"]), None)
            return {
                "name": row["display_name"],
                "rmse": round(rmse_val, 4),
                "f1": round(f1_val, 4),
                "rank": rank,
                "total": len(scores),
            }

        result = await asyncio.to_thread(_fetch)
        if result is None:
            raise HTTPException(404, "No submission found for this session")
        return result

    # ── Feedback POST ────────────────────────────────────

    class FeedbackIn(BaseModel):
        rating: Annotated[int, Field(ge=1, le=5)]
        lang: str = "en"

    @app.post("/feedback", status_code=201)
    async def post_feedback(body: FeedbackIn):
        def _write():
            assert _conn is not None
            _conn.execute(
                "INSERT INTO web_feedback(rating, lang) VALUES (?, ?)",
                (body.rating, body.lang[:5]),
            )
            _conn.commit()

        await asyncio.to_thread(_write)
        return {"ok": True}

    # ── Feedback summary GET ─────────────────────────────

    @app.get("/feedback/summary")
    async def feedback_summary():
        def _read():
            assert _conn is not None
            row = _conn.execute(
                "SELECT AVG(rating) avg, COUNT(*) cnt FROM web_feedback"
            ).fetchone()
            return {
                "avg": round(row["avg"] or 0.0, 2),
                "count": row["cnt"] or 0,
            }

        return await asyncio.to_thread(_read)

    # ── Health ───────────────────────────────────────────

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app
