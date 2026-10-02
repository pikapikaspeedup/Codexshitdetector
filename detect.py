#!/usr/bin/env python3
"""Flag Codex turns whose first response packet includes reasoning.

Defaults to the last 7 local calendar days and every model. Prints a markdown
report. Counts and project directories only. Does not print session ids or
message text.

    python3 detect.py
    python3 detect.py --since 2026-09-01 --until 2026-09-07 --model gpt-6-astra
    python3 detect.py --model gpt-6.1-sol
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, time, timedelta
from pathlib import Path


def local_now() -> datetime:
    return datetime.now().astimezone()


def parse_day(value: str) -> datetime:
    tz = local_now().tzinfo
    return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=tz)


def local_day(ts: str) -> str:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def filename_day(path: Path) -> str | None:
    name = path.name
    if name.startswith("rollout-") and len(name) >= 18 and name[12] == "-" and name[15] == "-":
        return name[8:18]
    return None


def iter_rollouts(since: datetime, until: datetime) -> list[Path]:
    since_ts = datetime.combine(since.date(), time.min, tzinfo=since.tzinfo).timestamp()
    until_day = until.date().isoformat()
    found: list[Path] = []
    home = codex_home()
    for root in (home / "sessions", home / "archived_sessions"):
        if not root.is_dir():
            continue
        for path in root.rglob("rollout-*.jsonl"):
            day = filename_day(path)
            if day and day > until_day:
                continue
            try:
                if path.stat().st_mtime < since_ts:
                    continue
            except OSError:
                continue
            found.append(path)
    return found


def want(line: str) -> bool:
    if "token_usage_record" in line or "turn_context" in line or "session_meta" in line:
        return True
    if "task_started" in line and "event_msg" in line:
        return True
    if "response_item" in line and '"type":"reasoning"' in line:
        return True
    if "response_item" in line and '"role":"assistant"' in line:
        return True
    return False


def blank_turn(turn_id: str, ts: str) -> dict:
    return {
        "turn_id": turn_id,
        "ts": ts,
        "model": None,
        "cwd": None,
        "first_rsn": None,
        "reasoning_before_speech": False,
        "saw_assistant": False,
    }


def classify(turn: dict) -> str | None:
    if turn["first_rsn"] is not None:
        return "zero" if turn["first_rsn"] == 0 else "reasoned"
    if turn["reasoning_before_speech"]:
        return "reasoned"
    if turn["saw_assistant"]:
        return "zero"
    return None


def consume(path: Path) -> list[dict]:
    turns: dict[str, dict] = {}
    order: list[str] = []
    current: str | None = None
    last_model = None
    last_cwd = None
    session_id = None
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not want(line):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = obj.get("type")
            payload = obj.get("payload") or {}
            ts = obj.get("timestamp") or ""
            if kind == "session_meta":
                session_id = payload.get("session_id") or payload.get("id")
                if payload.get("cwd"):
                    last_cwd = payload.get("cwd")
                continue
            if kind == "event_msg" and payload.get("type") == "task_started":
                turn_id = payload.get("turn_id")
                root = payload.get("root_turn_id")
                if not turn_id or (root and root != turn_id):
                    current = None
                    continue
                current = turn_id
                if turn_id not in turns:
                    turns[turn_id] = blank_turn(turn_id, ts)
                    order.append(turn_id)
                if last_model and not turns[turn_id]["model"]:
                    turns[turn_id]["model"] = last_model
                if last_cwd and not turns[turn_id]["cwd"]:
                    turns[turn_id]["cwd"] = last_cwd
                continue
            if kind == "turn_context":
                turn_id = payload.get("turn_id") or current
                model = payload.get("model")
                cwd = payload.get("cwd")
                if model:
                    last_model = model
                if cwd:
                    last_cwd = cwd
                if turn_id and turn_id in turns:
                    if model:
                        turns[turn_id]["model"] = model
                    if cwd:
                        turns[turn_id]["cwd"] = cwd
                continue
            if kind == "token_usage_record":
                turn_id = payload.get("turn_id") or current
                turn = turns.get(turn_id) if turn_id else None
                if turn is None or turn["first_rsn"] is not None:
                    continue
                usage = payload.get("usage") or {}
                rsn = usage.get("reasoning_output_tokens")
                if rsn is None:
                    continue
                turn["first_rsn"] = rsn
                if not turn["ts"]:
                    turn["ts"] = ts
                continue
            if kind == "response_item" and current and current in turns:
                turn = turns[current]
                item_type = payload.get("type")
                if item_type == "reasoning" and not turn["saw_assistant"]:
                    turn["reasoning_before_speech"] = True
                elif item_type == "message" and payload.get("role") == "assistant":
                    turn["saw_assistant"] = True
    rows = []
    for turn_id in order:
        turn = turns[turn_id]
        label = classify(turn)
        if label is None or not turn["ts"] or not turn["model"]:
            continue
        rows.append(
            {
                "session_id": session_id or turn_id,
                "ts": turn["ts"],
                "day": local_day(turn["ts"]),
                "model": turn["model"],
                "cwd": turn["cwd"] or "",
                "label": label,
            }
        )
    return rows


def pct(part: int, whole: int) -> str:
    if whole == 0:
        return "-"
    return f"{100.0 * part / whole:.0f}%"


def tally(items: list[dict]) -> tuple[int, int]:
    zero = sum(1 for row in items if row["label"] == "zero")
    reasoned = sum(1 for row in items if row["label"] == "reasoned")
    return zero, reasoned


def first_of_session(items: list[dict]) -> list[dict]:
    chosen: dict[str, dict] = {}
    for row in items:
        prev = chosen.get(row["session_id"])
        if prev is None or row["ts"] < prev["ts"]:
            chosen[row["session_id"]] = row
    return list(chosen.values())


def first_of_session_by_day(items: list[dict]) -> dict[str, list[dict]]:
    chosen: dict[tuple[str, str], dict] = {}
    for row in items:
        key = (row["day"], row["session_id"])
        prev = chosen.get(key)
        if prev is None or row["ts"] < prev["ts"]:
            chosen[key] = row
    by_day: dict[str, list[dict]] = defaultdict(list)
    for row in chosen.values():
        by_day[row["day"]].append(row)
    return by_day


def table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


def display_project(cwd: str) -> str:
    if not cwd:
        return "（未记录工作区）"
    home = str(Path.home())
    shown = "~" + cwd[len(home) :] if cwd == home or cwd.startswith(home + "/") else cwd
    return shown.replace("|", "/")


def is_scratch(cwd: str) -> bool:
    return cwd.startswith(("/private/tmp/", "/tmp/", "/var/folders/")) or "/T/" in cwd


def project_rows(rows: list[dict]) -> list[list[str]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row.get("cwd") or ""].append(row)
    ranked = []
    for cwd, items in grouped.items():
        z, r = tally(items)
        if r == 0:
            continue
        days = sorted({item["day"] for item in items if item["label"] == "reasoned"})
        models = sorted({item["model"] for item in items if item["label"] == "reasoned"})
        ranked.append((is_scratch(cwd), -r, cwd, z, r, days, models))
    ranked.sort()
    rendered = []
    for _scratch, _count, cwd, z, r, days, models in ranked:
        rendered.append(
            [
                display_project(cwd),
                str(r),
                str(z + r),
                pct(r, z + r),
                "、".join(models),
                f"{days[0]}–{days[-1]}" if len(days) > 1 else days[0],
            ]
        )
    return rendered


def render(rows: list[dict], since: str, until: str, models: list[str], files: int) -> str:
    tz_name = local_now().tzname() or "local"
    by_model: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_model[row["model"]].append(row)
    zero, reasoned = tally(rows)
    threads = first_of_session(rows)
    tzero, treasoned = tally(threads)
    lines = [
        "# Codex 第一包降智分布",
        "",
        f"- 时间：{since} 至 {until}（本机时区 {tz_name}，含首尾）",
        f"- 模型：{'、'.join(models) if models else '全部'}",
        f"- 扫描会话文件：{files}",
        f"- 计入回合：{len(rows)}",
        "",
        "只看每个用户回合的第一包。推理 token 为 0 记为正常，大于 0 记为降智。没有用量时，开口前已有推理条目记为降智。同一回合后面的包不计入。子回合不计入。",
        "降智回合所在的工作区视为有写入风险：这些回合里改过的代码，按这个口径当成可能写进了 Bug。",
        "",
        "## 合计",
        "",
        table(
            ["范围", "正常", "降智", "降智比例"],
            [
                ["全部回合", str(zero), str(reasoned), pct(reasoned, zero + reasoned)],
                ["每个会话的第一回合", str(tzero), str(treasoned), pct(treasoned, tzero + treasoned)],
            ],
        ),
        "",
        "## 按模型",
        "",
    ]
    model_rows = []
    for model, items in sorted(by_model.items(), key=lambda item: -len(item[1])):
        z, r = tally(items)
        model_rows.append([model, str(z + r), str(z), str(r), pct(r, z + r)])
    lines.append(table(["模型", "回合", "正常", "降智", "降智比例"], model_rows or [["-", "0", "0", "0", "-"]]))
    lines.append("")
    lines.append("## 按日")
    lines.append("")
    by_day: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_day[row["day"]].append(row)
    thread_by_day = first_of_session_by_day(rows)
    day_rows = []
    for day in sorted(by_day):
        z, r = tally(by_day[day])
        tz, tr = tally(thread_by_day.get(day, []))
        day_rows.append(
            [
                day,
                str(z + r),
                str(z),
                str(r),
                pct(r, z + r),
                str(tz + tr),
                str(tr),
                pct(tr, tz + tr),
            ]
        )
    lines.append(
        table(
            ["日期", "回合", "正常", "降智", "回合比例", "新会话", "新会话降智", "新会话比例"],
            day_rows or [["-", "0", "0", "0", "-", "0", "0", "-"]],
        )
    )
    lines.append("")
    lines.append("## 项目预警")
    lines.append("")
    warned = project_rows(rows)
    if not warned:
        lines.append("这个窗口里没有降智回合，没有项目需要预警。")
    else:
        lines.append("下面的工作区在窗口内出现过降智回合。优先复查这些回合里改过的代码。")
        lines.append("")
        lines.append(
            table(
                ["项目", "降智回合", "总回合", "降智比例", "降智模型", "降智日期"],
                warned,
            )
        )
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="最近一周 Codex 第一包降智分布")
    parser.add_argument("--since", help="起始日期 YYYY-MM-DD，本机时区。默认今天往前 6 天")
    parser.add_argument("--until", help="结束日期 YYYY-MM-DD，本机时区。默认今天")
    parser.add_argument("--model", action="append", default=[], help="模型 slug，可重复。省略为全部")
    args = parser.parse_args()
    today = local_now()
    until = parse_day(args.until) if args.until else today
    since = parse_day(args.since) if args.since else until - timedelta(days=6)
    if until.date() < since.date():
        parser.error("--until 早于 --since")
    models = [item.strip() for item in args.model if item.strip()]
    since_s = since.date().isoformat()
    until_s = until.date().isoformat()
    paths = iter_rollouts(since, until)
    rows: list[dict] = []
    for path in paths:
        try:
            found = consume(path)
        except OSError as exc:
            print(f"skip {path.name}: {exc}", file=sys.stderr)
            continue
        for row in found:
            if row["day"] < since_s or row["day"] > until_s:
                continue
            if models and row["model"] not in models:
                continue
            rows.append(row)
    sys.stdout.write(render(rows, since_s, until_s, models, len(paths)))


if __name__ == "__main__":
    main()
