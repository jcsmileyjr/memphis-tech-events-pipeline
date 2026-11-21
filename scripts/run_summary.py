"""
run_summary.py -- build the GitHub Actions run summary from the pipeline's log files.

Standard library only. Used by .github/workflows/pipeline.yml:

    python scripts/run_summary.py summary --extract extract.log --transform transform.log \
        --load load.log --output "$GITHUB_STEP_SUMMARY"
    python scripts/run_summary.py gate --load load.log     # exit 1 if any row was rejected

It reads the messages that extract.py, transform.py and load.py log. If a message is
reworded, the summary says "not found" and emits a workflow warning instead of failing
silently; tests/test_run_summary.py runs the real scripts to catch that early.
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

NOT_FOUND = "not found"

# One pattern per log message the summary depends on. Keep in sync with the scripts.
EXTRACT_SAVED = re.compile(r"Saved (\d+) entries to (\S+)")
STANDARDIZED = re.compile(r"(event_type|event_category|time): standardized (\d+) value\(s\)")
GROUP_PRESENT = re.compile(r"group_id: present on (\d+) of (\d+) events")
GROUP_ALL_KNOWN = re.compile(r"group_id: all values exist in the reference groups list")
GROUP_UNKNOWN = re.compile(r"group_id: (\d+) event\(s\) reference an ID not in the groups list")
DUPLICATES = re.compile(r"Duplicate event_id: (none|\d+ rows share an ID)")
TRANSFORM_SAVED = re.compile(r"Saved (\d+) rows to (\S+)")
LOAD_READ = re.compile(r"Read (\d+) rows from .+?: (\d+) valid, (\d+) rejected")
LOAD_RANGE = re.compile(r"Date range (\S+) to (\S+); (\d+) event\(s\) in the catch-all group; (\d+) without a time")
LOAD_RESULT = re.compile(r"fact_events: (\d+) inserted, (\d+) updated, (\d+) flagged is_active = false")
DRY_RUN = re.compile(r"Dry run: validation passed, nothing written")
LEVEL = re.compile(r"\b(WARNING|ERROR)\b")


def _find(pattern: re.Pattern, text: str, last: bool = False):
    matches = list(pattern.finditer(text))
    if not matches:
        return None
    return matches[-1] if last else matches[0]


def parse(extract: str, transform: str, load: str) -> dict:
    """Pull every figure out of the three logs. Missing values are None."""
    info: dict = {}

    m = _find(EXTRACT_SAVED, extract)
    info["extracted"] = int(m.group(1)) if m else None

    for name in ("event_type", "event_category", "time"):
        info[f"std_{name}"] = None
    for m in STANDARDIZED.finditer(transform):
        info[f"std_{m.group(1)}"] = int(m.group(2))

    m = _find(GROUP_PRESENT, transform)
    info["group_present"] = (int(m.group(1)), int(m.group(2))) if m else None

    if _find(GROUP_ALL_KNOWN, transform):
        info["group_ids_known"] = True
    elif _find(GROUP_UNKNOWN, transform):
        info["group_ids_known"] = False
    else:
        info["group_ids_known"] = None

    m = _find(DUPLICATES, transform)
    info["duplicates"] = m.group(1) if m else None

    m = _find(TRANSFORM_SAVED, transform)
    info["transform_rows"] = int(m.group(1)) if m else None

    m = _find(LOAD_READ, load)
    info["read"] = tuple(int(g) for g in m.groups()) if m else None  # rows, valid, rejected

    m = _find(LOAD_RANGE, load)
    info["range"] = m.groups() if m else None  # first, last, catch_all, no_time

    m = _find(LOAD_RESULT, load)
    info["result"] = tuple(int(g) for g in m.groups()) if m else None  # inserted, updated, flagged

    info["dry_run"] = bool(_find(DRY_RUN, load))

    info["issues"] = [
        _strip_prefix(line)
        for text in (extract, transform, load)
        for line in text.splitlines()
        if LEVEL.search(line)
    ]
    return info


def _strip_prefix(line: str) -> str:
    """Drop the 'YYYY-MM-DD HH:MM:SS,mmm ' timestamp and shorten long lines."""
    line = re.sub(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+ ", "", line.strip())
    line = line.replace("```", "'''")  # keep untrusted text from closing the code fence
    return line if len(line) <= 300 else line[:297] + "..."


def render(info: dict, dry_run: bool = False) -> tuple[str, list[str]]:
    """Return (markdown, list of 'not found' items)."""
    missing: list[str] = []

    def show(value, label: str, fmt=str) -> str:
        if value is None:
            missing.append(label)
            return NOT_FOUND
        return fmt(value)

    dry = dry_run or info["dry_run"]
    lines = ["## Pipeline run summary", ""]
    if dry:
        lines += ["**Dry run: validated only, nothing was written to the database.**", ""]

    rows = [
        ("Events extracted", show(info["extracted"], "events extracted")),
        ("Standardized: event type", show(info["std_event_type"], "standardized event_type")),
        ("Standardized: event category", show(info["std_event_category"], "standardized event_category")),
        ("Standardized: time", show(info["std_time"], "standardized time")),
        ("Duplicate event IDs", show(info["duplicates"], "duplicate event IDs")),
        ("Rows saved by transform", show(info["transform_rows"], "transform rows saved")),
    ]

    gp = info["group_present"]
    rows.append(("Group ID present (incl. catch-all)",
                 show(gp, "group ID presence", lambda v: f"{v[0]} of {v[1]}")))
    known = info["group_ids_known"]
    rows.append(("Group IDs all in reference list",
                 show(known, "group ID validation", lambda v: "yes" if v else "NO, see warnings")))

    read, rng = info["read"], info["range"]
    rows.append(("Rows read / valid / rejected",
                 show(read, "load rows read", lambda v: f"{v[0]} / {v[1]} / {v[2]}")))
    if read is not None and rng is not None:
        valid, catch_all = read[1], int(rng[2])
        real = valid - catch_all
        pct = f"{real / valid * 100:.1f}%" if valid else "n/a"
        rows.append(("Events with a real group", f"{real} of {valid} ({pct})"))
    else:
        rows.append(("Events with a real group", show(None, "real group coverage")))
    rows.append(("Date range", show(rng, "load date range", lambda v: f"{v[0]} to {v[1]}")))

    if info["result"] is not None:
        i, u, f = info["result"]
        rows.append(("Load result", f"{i} inserted, {u} updated, {f} flagged inactive"))
    elif dry:
        rows.append(("Load result", "dry run, nothing written"))
    else:
        rows.append(("Load result", show(None, "load result (inserted/updated/flagged)")))

    lines += ["| Step | Value |", "|---|---|"] + [f"| {k} | {v} |" for k, v in rows] + [""]

    if read is not None and read[2] > 0:
        lines += [f"**{read[2]} row(s) were rejected.** The run is marked failed. See the errors below.", ""]
    if missing:
        lines += ["**Not found in the logs (a log message may have been reworded):** " + ", ".join(missing), ""]

    issues = info["issues"]
    if issues:
        lines += [f"### Warnings and errors ({len(issues)})", "", "```"]
        lines += issues[:25]
        if len(issues) > 25:
            lines.append(f"... and {len(issues) - 25} more (see the step logs)")
        lines += ["```", ""]
    else:
        lines += ["No warnings or errors were logged.", ""]
    return "\n".join(lines), missing


def _read(path: Optional[str]) -> str:
    if not path:
        return ""
    p = Path(path)
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def gate(load_text: str) -> tuple[int, str]:
    """Exit code and message for the rejected-rows gate."""
    m = _find(LOAD_READ, load_text)
    if not m:
        return 1, "Could not find the 'rows read / valid / rejected' line in the load log."
    rejected = int(m.group(3))
    if rejected:
        return 1, f"{rejected} row(s) were rejected by load.py. The valid rows were loaded; fix the source data."
    return 0, "No rows were rejected."


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("summary", help="write the markdown run summary")
    s.add_argument("--extract")
    s.add_argument("--transform")
    s.add_argument("--load")
    s.add_argument("--output", help="file to append to (e.g. $GITHUB_STEP_SUMMARY); default: stdout")
    s.add_argument("--dry-run", action="store_true")

    g = sub.add_parser("gate", help="exit 1 if load.py rejected any row")
    g.add_argument("--load", required=True)

    args = parser.parse_args(argv)

    if args.command == "gate":
        code, message = gate(_read(args.load))
        print(("::error::" if code else "") + message)
        return code

    info = parse(_read(args.extract), _read(args.transform), _read(args.load))
    markdown, missing = render(info, dry_run=args.dry_run)
    if args.output:
        with open(args.output, "a", encoding="utf-8") as f:
            f.write(markdown + "\n")
        for item in missing:
            print(f"::warning::Run summary: {item} not found in the logs")
    else:
        print(markdown)
    return 0


if __name__ == "__main__":
    sys.exit(main())
