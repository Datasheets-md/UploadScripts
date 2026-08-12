#!/usr/bin/env python3
"""Upload PDF datasheets to datasheets.md -- no part numbers needed.

Send a folder of PDFs in one request. The parser reads each datasheet, finds
every part number in its ordering table, and creates a component for each one.
A datasheet listing 40 orderable variants gives you 40 parts.

The script then waits for parameter extraction to finish on every part, so a
clean exit means the data is actually ready -- not merely that the upload
landed.

    pip install requests
    export DATASHEETS_TOKEN=dsh_...        # datasheets.md -> Integrations -> API
    python upload_datasheets.py ./my_pdfs

The main flow is the three numbered blocks at the bottom. Everything above
them is argument handling and error reporting.
"""

import argparse
import os
import sys
import time
from pathlib import Path

import requests

POLL_SECONDS = 20
MAX_FILES = 500  # server-side cap for one request

JOB_DONE = ("completed", "blocked", "cancelled")
# unified_status: 0 pending / 1 ready / 2 processing / 3-5 failed.
BUSY, FAILED = (0, 2), (3, 4, 5)


# --------------------------------------------------------------------------
# setup and error reporting, kept out of the main flow
# --------------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(
        description="Bulk-upload PDF datasheets to datasheets.md.")
    p.add_argument("paths", nargs="+", metavar="PATH",
                   help="PDF files and/or folders containing PDFs")
    p.add_argument("--private", action="store_true",
                   help="keep the parts in your workspace (default: public)")
    p.add_argument("--dry-run", action="store_true",
                   help="list what would be uploaded, then stop")
    p.add_argument("--no-wait", action="store_true",
                   help="exit once the parts exist, without waiting for parameters")
    p.add_argument("--base-url", default=os.environ.get(
        "DATASHEETS_URL", "https://datasheets.md"))
    p.add_argument("--token", default=os.environ.get("DATASHEETS_TOKEN"),
                   help="personal API token (or set DATASHEETS_TOKEN)")
    return p.parse_args()


def check(r):
    """Explain the API's error responses instead of dumping a traceback."""
    if r.ok:
        return r
    why = {
        401: "check your token -- Integrations -> API on datasheets.md issues a dsh_ key",
        403: "this token cannot write to that workspace",
        404: "batch upload is not enabled on this server",
        413: "a file exceeds the 50 MB per-file limit",
        429: "daily digitisation quota reached -- try again tomorrow",
        503: "the service is at capacity -- retry later",
    }.get(r.status_code)
    sys.exit(f"HTTP {r.status_code}: {why or r.text[:300]}")


def collect_pdfs(paths):
    """Expand paths into PDFs. Folders contribute their PDFs regardless of
    filename case; anything else in a folder is REPORTED, never silently
    dropped -- a file missing without a word is worse than an error."""
    pdfs, skipped = [], []
    for arg in map(Path, paths):
        if arg.is_dir():
            for f in sorted(arg.iterdir()):
                target = pdfs if f.is_file() and f.suffix.lower() == ".pdf" else skipped
                target.append(f)
        elif arg.is_file():
            pdfs.append(arg)  # named explicitly, so trust it
        else:
            sys.exit(f"not found: {arg}")
    if not pdfs:
        sys.exit(f"no PDFs found in: {' '.join(paths)}")
    if len(pdfs) > MAX_FILES:
        sys.exit(f"{len(pdfs)} files exceeds the {MAX_FILES}-per-request cap; "
                 f"split the folder and run again")
    return pdfs, skipped


def report_rows(rows):
    """Per-datasheet outcome, including the ways one can yield nothing."""
    for row in rows:
        name = row["resolved"]["filename"]
        confirm = row["resolved"].get("confirm") or {}
        found = confirm.get("created", [])
        print(f"      {name}: {row['status']}, {len(found)} part numbers {found[:5]}")
        if row.get("error"):
            print(f"        error: {row['error']}")
        for label in ("rejected", "conflicts", "already_in_workspace"):
            if confirm.get(label):
                print(f"        {label}: {confirm[label][:5]}")


# --------------------------------------------------------------------------
# main flow
# --------------------------------------------------------------------------

args = parse_args()
pdfs, skipped = collect_pdfs(args.paths)
for f in skipped:
    print(f"      skipping (not a .pdf): {f.name}")

if args.dry_run:  # before the token check -- a dry run needs no credentials
    print(f"would upload {len(pdfs)} pdf(s):")
    for p in pdfs:
        print(f"  - {p}")
    sys.exit(0)

if not args.token:
    sys.exit("No token. Set DATASHEETS_TOKEN=dsh_... or pass --token.\n"
             "Create one at https://datasheets.md/integrations/api")

s = requests.Session()
s.headers["Authorization"] = f"Bearer {args.token}"

# 1. Upload. Every file is hashed, deduplicated and staged before anything is
#    written, so an interrupted upload leaves no half-finished job behind.
print(f"[1/3] uploading {len(pdfs)} pdf(s)...")
files = [("files", (p.name, p.open("rb"), "application/pdf")) for p in pdfs]
r = check(s.post(f"{args.base_url}/api/priv_components/batch/datasheets/",
                 files=files,
                 data={"is_public": "false" if args.private else "true"}))
job = r.json()["job_uuid"]
print(f"      upload complete, {len(pdfs)}/{len(pdfs)} staged. job {job}")

# 2. The upload is done; everything below is server-side progress. Several
#    datasheets are parsed at once, but they are committed strictly in order so
#    that two datasheets from the same family cannot create duplicate parts. A
#    datasheet stays "parsing or queued" until its parts are created, so early
#    polls showing no progress are normal -- a large PDF can take a few minutes.
print("[2/3] processing datasheets (parse -> discover part numbers)")
while True:
    d = check(s.get(f"{args.base_url}/api/priv_components/batch/{job}/")).json()
    c = d["counts"]
    print(f"      part numbers discovered in {c.get('created', 0)}/{d['total']}"
          f" datasheets | {c.get('pending', 0)} parsing or queued"
          f" | {c.get('failed', 0)} failed")
    if d["status"] in JOB_DONE:
        break
    time.sleep(POLL_SECONDS)

print(f"      job {d['status']}"
      + (f" -- {d['blocked_reason']}" if d.get("blocked_reason") else ""))
report_rows(d["rows"])

if args.no_wait:
    sys.exit(0)

# 3. The parts exist now, but their parameters are still being extracted, and
#    the first part of a family finishes before the rest. Check every part.
print("[3/3] extracting parameters (every part, not just the first in the family)")
for row in d["rows"]:
    if not row["component_uuid"]:
        continue
    name = row["resolved"]["filename"]
    while True:
        members = check(s.get(f"{args.base_url}/api/priv_components/",
                              params={"siblings_of": row["component_uuid"],
                                      "limit": 100})).json()["components"]
        busy = [m for m in members if m["unified_status"] in BUSY]
        print(f"      {name}: {len(members) - len(busy)}/{len(members)} parts ready")
        if not busy:
            break
        time.sleep(POLL_SECONDS)
    failed = [m["part_number"] for m in members if m["unified_status"] in FAILED]
    if failed:
        print(f"      {name}: {len(failed)} FAILED: {failed[:5]}")
