import csv
import io
from dataclasses import dataclass

VALID_STAGES: set[str] = {
    "group", "roundof32", "roundof16", "qf", "sf", "runnerup", "champion",
}
OUTLIER_GOALS = 35.0


class ValidationError(Exception):
    pass


@dataclass(frozen=True)
class ParsedRow:
    team_id: str
    total_goals: float
    target: str


def parse_submission(csv_text: str, valid_ids: set[str]) -> list[ParsedRow]:
    reader = csv.DictReader(io.StringIO(csv_text))
    required = {"ID", "total_goals", "Target"}
    if reader.fieldnames is None or not required.issubset(reader.fieldnames):
        raise ValidationError(
            "CSV must have columns: ID, total_goals, Target")
    rows: list[ParsedRow] = []
    seen: set[str] = set()
    for i, r in enumerate(reader, start=2):
        tid = (r["ID"] or "").strip()
        if tid not in valid_ids:
            raise ValidationError(f"row {i}: unknown team id '{tid}'")
        if tid in seen:
            raise ValidationError(f"row {i}: duplicate team id '{tid}'")
        seen.add(tid)
        raw = (r["total_goals"] or "").strip()
        try:
            goals = float(raw)
        except ValueError:
            raise ValidationError(f"row {i}: total_goals '{raw}' is not a number")
        if goals < 0:
            raise ValidationError(f"row {i}: total_goals is negative")
        target = (r["Target"] or "").strip()
        if target not in VALID_STAGES:
            raise ValidationError(
                f"row {i}: invalid stage '{target}' (allowed: "
                + ", ".join(sorted(VALID_STAGES)) + ")")
        rows.append(ParsedRow(tid, goals, target))
    missing = valid_ids - seen
    if missing:
        raise ValidationError(
            f"missing {len(missing)} team(s): {', '.join(sorted(missing))}")
    return rows
