"""Public REST API — leaderboard + web feedback.

Runs as a uvicorn task inside the same asyncio loop as the Telegram bot.
All DB calls are wrapped in asyncio.to_thread so they don't block the loop.
A separate SQLite connection is used (WAL mode allows concurrent readers).
"""

import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from wc2026bot.db import connect
from wc2026bot.notify import cohort_scores

# ── State ─────────────────────────────────────────────────

_conn: sqlite3.Connection | None = None


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


# ── App ───────────────────────────────────────────────────

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
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
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
