# alarm-flood-analyzer

ISA 18.2 style alarm metrics from a historian CSV export, aimed at the first
pass of an alarm rationalisation.

```bash
$ python3 alarm_analysis.py examples/alarm_log.csv
Window      : 2026-11-15T00:05:00 -> 2026-11-15T04:38:00 (4.5 h)
Alarms      : 27 active of 52 events
Rate        : 5.9 alarms/hour
Peak 10 min : 12 at 2026-11-15T01:00:00
Priorities  : CRITICAL=1, HIGH=14, LOW=2, MEDIUM=10

Bad actors (top 10)
  PT-103.PV        12   44.4%
  LT-101.PV         7   25.9%
  ...
Chattering (>= 3 transitions/hour)
  PT-103.PV        12 transitions
  ...
```

Add `--html report.html` for a self-contained report you can attach to a
review pack.

## Input

CSV with these columns:

```csv
timestamp,tag,event,priority,description
2026-11-15T00:05:00,LT-101.PV,ACTIVE,MEDIUM,Wet well level high
2026-11-15T00:08:00,LT-101.PV,CLEAR,MEDIUM,Wet well level high
```

- `timestamp` - ISO 8601. Be consistent about local vs UTC; the report repeats
  whatever is in the file without shifting it.
- `event` - `ACTIVE` or `CLEAR`.
- `priority` - free text (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL` by convention).

Most historians can produce this with a tag/event/priority export. If yours
uses `ALARM`/`NORMAL`, map it in the export query rather than editing the CSV.

## What is calculated

| Metric | Definition used here |
|---|---|
| Alarms per hour | ACTIVE events divided by the observation window |
| Peak 10 minutes | highest number of ACTIVE events in any rolling 10 min window |
| Flood | peak of 10 or more ACTIVE events in 10 minutes |
| Bad actor | tag ranking by ACTIVE count (Pareto) |
| Chattering | 3 or more ACTIVE transitions for one tag within an hour |
| Standing | an ACTIVE with no matching CLEAR by the end of the export |

## Honest limits

- No state model beyond ACTIVE/CLEAR pairs; shelving, suppression, disabled
  and repeat alarms are not represented.
- Priorities are counted, not weighted.
- A short export cannot distinguish a genuinely quiet plant from a broken
  collector - check the event count before celebrating.

## License

MIT.

---

Maintained by Glen Marsh · Helix Corp Ltd
