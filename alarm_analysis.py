"""ISA 18.2 style alarm metrics from a historian CSV export.

Input columns: timestamp,tag,event,priority,description
``event`` is ACTIVE or CLEAR. Timestamps are ISO 8601 (local or UTC, be
consistent - the report says which).

The numbers here follow the usual operator-facing metrics: alarms per hour,
peak rate in a 10 minute window, bad actor Pareto, chattering and standing
alarms. They are meant to start an alarm rationalisation conversation, not to
replace a dedicated alarm management system.
"""

from __future__ import annotations

import argparse
import csv
import html
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

FLOOD_WINDOW = timedelta(minutes=10)
CHATTER_WINDOW = timedelta(hours=1)
CHATTER_COUNT = 3


@dataclass
class Event:
    timestamp: datetime
    tag: str
    event: str
    priority: str
    description: str


def load(path: str) -> list[Event]:
    events = []
    with open(path, newline="", encoding="utf-8") as handle:
        for line, row in enumerate(csv.DictReader(handle), start=2):
            try:
                timestamp = datetime.fromisoformat(row["timestamp"].strip().replace("Z", "+00:00"))
            except (KeyError, ValueError) as exc:
                raise ValueError(f"line {line}: bad timestamp: {exc}") from exc
            event = row.get("event", "").strip().upper()
            if event not in ("ACTIVE", "CLEAR"):
                raise ValueError(f"line {line}: event must be ACTIVE or CLEAR")
            events.append(
                Event(
                    timestamp,
                    row.get("tag", "").strip().upper(),
                    event,
                    (row.get("priority") or "-").strip().upper(),
                    (row.get("description") or "").strip(),
                )
            )
    return sorted(events, key=lambda e: e.timestamp)


def analyse(events: list[Event]) -> dict:
    if not events:
        raise ValueError("no events")
    start, end = events[0].timestamp, events[-1].timestamp
    hours = max((end - start).total_seconds() / 3600.0, 1e-9)
    active = [e for e in events if e.event == "ACTIVE"]

    # Peak rate in any 10 minute window (two-pointer).
    peak = 0
    peak_at = None
    left = 0
    for right, event in enumerate(active):
        while event.timestamp - active[left].timestamp > FLOOD_WINDOW:
            left += 1
        count = right - left + 1
        if count > peak:
            peak, peak_at = count, active[left].timestamp

    by_tag = Counter(e.tag for e in active)
    by_priority = Counter(e.priority for e in active)

    # Chattering: several ACTIVE transitions for one tag within an hour.
    timestamps: dict[str, list[datetime]] = defaultdict(list)
    for event in active:
        timestamps[event.tag].append(event.timestamp)
    chattering = []
    for tag, times in timestamps.items():
        left = 0
        worst = 0
        for right, moment in enumerate(times):
            while moment - times[left] > CHATTER_WINDOW:
                left += 1
            worst = max(worst, right - left + 1)
        if worst >= CHATTER_COUNT:
            chattering.append((tag, worst))
    chattering.sort(key=lambda item: -item[1])

    # Standing: an ACTIVE never followed by a CLEAR.
    open_tags: dict[str, datetime] = {}
    standing = []
    for event in events:
        if event.event == "ACTIVE":
            if event.tag not in open_tags:
                open_tags[event.tag] = event.timestamp
        else:
            open_tags.pop(event.tag, None)
    for tag, since in open_tags.items():
        standing.append((tag, (end - since).total_seconds() / 3600.0))
    standing.sort(key=lambda item: -item[1])

    return {
        "window_start": start.isoformat(timespec="seconds"),
        "window_end": end.isoformat(timespec="seconds"),
        "hours": hours,
        "events": len(events),
        "alarms": len(active),
        "per_hour": len(active) / hours,
        "peak_10min": peak,
        "peak_at": peak_at.isoformat(timespec="seconds") if peak_at else None,
        "by_priority": dict(by_priority),
        "bad_actors": by_tag.most_common(10),
        "chattering": chattering[:10],
        "standing": standing[:10],
        "flood": peak >= 10,
    }


def render_text(result: dict) -> str:
    lines = [
        f"Window      : {result['window_start']} -> {result['window_end']} "
        f"({result['hours']:.1f} h)",
        f"Alarms      : {result['alarms']} active of {result['events']} events",
        f"Rate        : {result['per_hour']:.1f} alarms/hour",
        f"Peak 10 min : {result['peak_10min']} at {result['peak_at'] or '-'}",
        f"Priorities  : " + ", ".join(f"{k}={v}" for k, v in sorted(result["by_priority"].items())),
        "",
        "Bad actors (top 10)",
    ]
    total = result["alarms"] or 1
    for tag, count in result["bad_actors"]:
        lines.append(f"  {tag:<14}{count:>5}  {count / total * 100:5.1f}%")
    lines.append("")
    if result["chattering"]:
        lines.append("Chattering (>= 3 transitions/hour)")
        for tag, count in result["chattering"]:
            lines.append(f"  {tag:<14}{count:>5} transitions")
    else:
        lines.append("Chattering: none detected")
    if result["standing"]:
        lines.append("")
        lines.append("Standing alarms")
        for tag, hours in result["standing"]:
            lines.append(f"  {tag:<14}{hours:8.1f} h open")
    if result["flood"]:
        lines.append("")
        lines.append("NOTE: alarm flood detected (>10 alarms in 10 minutes).")
    return "\n".join(lines)


def render_html(result: dict, source: str) -> str:
    def rows(items, label):
        return "".join(
            f"<tr><td>{html.escape(str(tag))}</td><td class='n'>{value}</td>"
            f"<td>{label}</td></tr>"
            for tag, value in items
        )

    total = result["alarms"] or 1
    bad = "".join(
        f"<tr><td>{html.escape(tag)}</td><td class='n'>{count}</td>"
        f"<td class='n'>{count / total * 100:.1f}%</td></tr>"
        for tag, count in result["bad_actors"]
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Alarm analysis - {html.escape(source)}</title>
<style>
 body{{font:14px/1.5 system-ui,sans-serif;max-width:900px;margin:2rem auto;color:#1b1f23}}
 h1{{font-size:1.4rem}} .cards{{display:flex;gap:1rem;flex-wrap:wrap;margin:1.5rem 0}}
 .card{{border:1px solid #d6d9dc;border-radius:6px;padding:.8rem 1rem;min-width:150px}}
 .card b{{display:block;font-size:1.6rem}} table{{border-collapse:collapse;width:100%;margin:.5rem 0 1.5rem}}
 th,td{{text-align:left;border-bottom:1px solid #e4e6e8;padding:.35rem .5rem}}
 th{{background:#f4f6f8}} .n{{text-align:right;font-variant-numeric:tabular-nums}}
 .warn{{background:#fff4e5;border-left:4px solid #e08b00;padding:.6rem .9rem}}
</style></head><body>
<h1>Alarm analysis: {html.escape(source)}</h1>
<p>{html.escape(result['window_start'])} &rarr; {html.escape(result['window_end'])}
 ({result['hours']:.1f} h)</p>
<div class="cards">
 <div class="card">Alarms<b>{result['alarms']}</b></div>
 <div class="card">Per hour<b>{result['per_hour']:.1f}</b></div>
 <div class="card">Peak / 10 min<b>{result['peak_10min']}</b></div>
 <div class="card">Bad actor tags<b>{len(result['bad_actors'])}</b></div>
</div>
{'<p class="warn">Alarm flood detected: more than 10 alarms in a 10 minute window.</p>' if result['flood'] else ''}
<h2>Bad actors</h2>
<table><thead><tr><th>Tag</th><th class="n">Alarms</th><th class="n">Share</th></tr></thead>
<tbody>{bad}</tbody></table>
<h2>Chattering</h2>
<table><tbody>{rows(result['chattering'], 'transitions') or '<tr><td>None detected</td></tr>'}</tbody></table>
<h2>Standing alarms</h2>
<table><tbody>{rows(result['standing'], 'hours open') or '<tr><td>None detected</td></tr>'}</tbody></table>
</body></html>"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="alarm-analysis",
        description="ISA 18.2 style metrics from a historian alarm CSV export.",
    )
    parser.add_argument("csv")
    parser.add_argument("--html", metavar="FILE", help="also write an HTML report")
    args = parser.parse_args(argv)
    try:
        events = load(args.csv)
        result = analyse(events)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(render_text(result))
    if args.html:
        with open(args.html, "w", encoding="utf-8") as handle:
            handle.write(render_html(result, args.csv))
        print(f"report written to {args.html}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
