# Contributing

Thanks for your interest in contributing to the Zindi World Cup 2026 Bot — a Telegram live tracker for the [Zindi World Cup 2026 Goal Prediction Challenge](https://zindi.africa).

## How to contribute

1. Fork the repo and create a branch from `main`
2. Name your branch descriptively: `feat/my-feature`, `fix/bug-name`, `docs/update-readme`
3. Make your changes, write tests if applicable
4. Open a pull request against `main`

## Commit conventions

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add live goal notification
fix: correct RMSE normalization edge case
docs: update setup instructions
test: add validation tests for CSV parser
refactor: extract evaluation engine
```

## Setup

```bash
git clone https://github.com/yehoshua0/zindi-world-cup-2026-bot.git
cd zindi-world-cup-2026-bot
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your Telegram bot token and any API keys.

## Running tests

```bash
pytest
```

## Project structure

```
wc2026bot/        # Core bot and evaluation logic
  feeds/          # Live data ingestion from sports APIs
  evaluation.py   # RMSE + F1 scoring engine
  teams.py        # Team mapping (Test.csv IDs → country names)
  validation.py   # CSV submission validator
scripts/          # One-off data prep scripts
tests/            # Test suite
```

## What to work on

Check [open issues](https://github.com/yehoshua0/zindi-world-cup-2026-bot/issues) for tasks. If you want to tackle something not listed, open an issue first so we can align before you build.

## Code style

- Python 3.10+
- Follow PEP 8
- No comments that restate what the code does — only add one when the **why** is non-obvious

## Questions

Open an issue or start a discussion on the repo.
