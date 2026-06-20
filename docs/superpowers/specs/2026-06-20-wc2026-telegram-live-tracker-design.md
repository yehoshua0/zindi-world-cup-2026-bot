# WC2026 Telegram Live Tracker — Design

**Date:** 2026-06-20
**Status:** Approved (design), pending implementation plan
**Scope:** v1 — Telegram bot only. No web PWA.

## 1. Purpose

A public, multi-user Telegram bot that tracks participants' submissions for the
[Zindi World Cup 2026 Goal Prediction Challenge](https://zindi.africa/competitions/world-cup-2026-goal-prediction-challenge)
against live tournament results (Jun 11 – Jul 19, 2026).

Users upload their submission CSV; the bot evaluates it live against real match
outcomes and reports trailing metrics, leaderboard rank, and pushes alerts when
goals are scored or matches finish.

This project is independent of any prior modeling work. It consumes only the
official competition assets (`Test.csv`, `SampleSubmission.csv`) and public live
match feeds. Reading live results in the bot is allowed — the external-data ban
applies only to competition *submissions*, not to a tracking tool.

## 2. Competition facts (authoritative)

- **Submission format:** `ID, total_goals, Target` (one row per team).
- **IDs:** `WC-2026_<ISO3>` (e.g. `WC-2026_AUT`). `Test.csv` carries a `country`
  column, so ID → country is a direct lookup. (The Zindi page's `ROW_...` example
  is generic boilerplate and does not match the real files.)
- **Teams:** 48.
- **Metric:** `Overall = 0.60 × RMSE(total_goals) + 0.40 × F1(Target)`.
  RMSE lower is better; F1 higher is better.
- **Stage labels (7):** `group`, `roundof32`, `roundof16`, `qf`, `sf`,
  `runnerup`, `champion`.
- **Timeline:** submissions locked Jun 19, 2026; tournament Jun 11 – Jul 19;
  results reveal Jul 19. Private leaderboard = 80% of test data, final after the
  tournament.

## 3. Decisions

| Area | Decision |
|---|---|
| Audience | Public, multi-user |
| Channels | Telegram only (web PWA dropped) |
| Analytics depth | Current-state only (trailing RMSE + Macro F1). No Monte Carlo in v1. |
| Interaction | Commands + push notifications |
| Live feed | Multi-source with fallback: ESPN keyless (live primary), Football-Data.org (verify/finalize) |
| Language | Python, `python-telegram-bot` v21 (async) |
| Persistence | SQLite |
| Hosting | Always-on host (Railway / Fly / Render); long-polling, host-agnostic |
| ID mapping | Static `teams.csv` built once from `Test.csv` |

## 4. Architecture

Single always-on Python process (asyncio). Components:

1. **Bot interface** — `python-telegram-bot` v21, long-polling (no public URL
   required). Handles commands and dispatches push messages.
2. **Ingestion poller** — state-machine scheduler controlling poll cadence:
   - **Dormant** (no active games): every 6h — schedule/venue refresh.
   - **Pre-match** (kickoff − 30 min): every 5 min.
   - **In-play**: every 60s, ESPN keyless live feed.
   - **Finalize**: on match end, cross-check ESPN + Football-Data before
     committing the final scoreline.
3. **Tournament state store** (SQLite): `teams_state`, `matches`, `users`,
   `submissions`, `predictions`.
4. **Evaluation engine** — computes current-state RMSE and Macro F1 per
   submission; normalizes RMSE across the user cohort; produces the combined
   score and rank.
5. **Notification dispatcher** — on goal / match-finish events, computes each
   affected user's metric delta and sends a personalized push.
6. **Team mapping** — static `teams.csv`: `zindi_id, country, iso3, espn_name,
   fd_name`. Resolves feed team names to competition IDs.

### Data flow

```
poll feed -> diff vs DB -> update teams_state/matches
          -> recompute affected submissions -> push deltas to users
```

## 5. Evaluation semantics (current-state)

### Goals (RMSE)
- `actual_goals` = goals scored so far (penalty-shootout goals excluded).
- `predicted` = user's `total_goals` (full-tournament prediction).
- Because actual is partial and predicted is full-tournament, RMSE is large
  early and shrinks over time. This is acceptable: it is used for *relative*
  ranking across users at the same point in time. Display both raw RMSE and rank.

### Stage (Macro F1)
- `current_stage` = furthest round a team has reached so far; once eliminated it
  is the team's final exit stage.
- F1 compares predicted `Target` against `current_stage` as the "actual-so-far"
  label, macro-averaged over the 7 classes.
- Early in the tournament most teams sit at `group`, so macro-F1 is noisy at the
  start. This is an honest "so far" measure and is accepted for v1.

### Leaderboard
- Combined score `0.60 × RMSE_norm + 0.40 × MacroF1`.
- `RMSE_norm` = min-max normalization of raw RMSE across the active user cohort
  (`1 − (rmse − min) / (max − min)`), so higher is better and aligns with F1.
- Rank users by combined score, descending.

### Penalty shootouts
Shootout goals are excluded from `actual_goals`. Filter by match event type
(`goalType` vs `penaltyShootout`) before committing.

## 6. Commands

| Command | Behavior |
|---|---|
| `/start` | Register user (telegram_chat_id) |
| `/upload` | Accept CSV → validate → store as active submission |
| `/me` | User's current RMSE, Macro F1, combined score, rank |
| `/rank` | Top leaderboard |
| `/today` | Today's matches + user's impact |
| `/yesterday` | Yesterday's finished matches recap |
| `/team <code>` | Team status + user's prediction for it |
| `/help` | Command list |

## 7. Upload validation

Reject with a specific reason on any of:
- Row count ≠ 48.
- Any ID not exactly matching `Test.csv` IDs (or duplicates / missing teams).
- `total_goals` not a non-negative number (warn on outliers > 35).
- `Target` not one of the 7 valid stage labels.

On success: store parsed predictions, mark submission active (one active
submission per user; new upload supersedes the previous).

## 8. Push notifications

Triggered on **goal scored** (live) and **match finished**. Per-user payload
includes: predicted vs real for the involved teams, ΔRMSE / ΔMacroF1 since the
event, and a cohort comparison line. Only users with an active submission
referencing an affected team receive the push.

## 9. Error handling & robustness

- Feed source unavailable → fall back to the next source.
- Final scores committed only after 2-source cross-check.
- Event processing is idempotent — dedupe by event/match id so repeated polls do
  not double-count goals.
- Respect each source's rate limits via the polling state machine.

## 10. Database schema (SQLite)

- `users(user_id, telegram_chat_id UNIQUE, created_at)`
- `submissions(submission_id, user_id, file_hash, uploaded_at, is_active)`
- `teams_state(team_id PK, country, iso3, actual_goals, current_stage)`
- `predictions(prediction_id, submission_id, team_id, predicted_goals, predicted_stage)`
- `matches(match_id PK, home_team_id, away_team_id, home_score, away_score, status, match_stage, kickoff_time)`

Indexes on `predictions(submission_id)`, `teams_state(current_stage)`,
`matches(status)`.

## 11. Testing

- Mock feed fixtures (ESPN / Football-Data JSON samples).
- Simulated match progression driving the poller → state → push path.
- Eval engine unit tests against hand-computed RMSE / Macro F1 values.
- Upload validation tests for each rejection case.

## 12. Out of scope (v1)

Deferred to later iterations: Monte Carlo projection (expected final score /
rank), SVG bracket image rendering, web push, divergence / surprise / consensus
indexes, web PWA.

## 13. Open risks

- **Feed team-name matching** for all 48 teams, including debutants
  (CPV, CUW, JOR, UZB). Requires a verification pass when building `teams.csv` to
  confirm every country resolves to a unique ESPN and Football-Data team name.
- **ESPN feed stability** — unofficial endpoint; may change format. Football-Data
  fallback mitigates for final scores but not for live goal granularity.
