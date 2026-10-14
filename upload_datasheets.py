#!/usr/bin/env python3
"""Upload PDF datasheets to datasheets.md -- no part numbers needed.

Send a folder of PDFs as one import job. The parser reads each datasheet, finds
every part number in its ordering table, and creates a component for each one.
A datasheet listing 40 orderable variants gives you 40 parts.

The script then waits for parameter extraction to finish on every part, so a
clean exit means the data is actually ready -- not merely that the upload
landed.

    pip install requests
    export DATASHEETS_TOKEN=dsh_...        # datasheets.md -> Integrations -> API
    python upload_datasheets.py ./my_pdfs

The PDFs go straight to the object store through presigned URLs; the API only
hands out the URLs and then registers what arrived. Everything here uses the
public API under /api/v1, documented at https://api.datasheets.md/api/v1/docs/.

The main flow is the numbered blocks at the bottom. Everything above them is
argument handling, the upload itself and error reporting.
"""

import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

POLL_SECONDS = 20
MAX_FILES = 500        # server-side cap for one job
PARALLEL_UPLOADS = 4   # PUTs to the object store at once

JOB_DONE = ("completed", "blocked", "cancelled")


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
        "DATASHEETS_URL", "https://api.datasheets.md"),
        help="API origin (or set DATASHEETS_URL); self-hosted: the address "
             "you reach the API at, e.g. https://datasheets.example.com")
    p.add_argument("--token", default=os.environ.get("DATASHEETS_TOKEN"),
                   help="personal API token (or set DATASHEETS_TOKEN)")
    return p.parse_args()


def error_text(r):
    try:
        body = r.json()
        return body.get("message") or body.get("error") or r.text[:300]
    except ValueError:
        return r.text[:300]


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
    }.get(r.status_code)
    sys.exit(f"HTTP {r.status_code}: {error_text(r)}" + (f" ({why})" if why else ""))


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
        sys.exit(f"{len(pdfs)} files exceeds the {MAX_FILES}-per-job cap; "
                 f"split the folder and run again")
    names = [p.name for p in pdfs]
    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        sys.exit(f"two files share a name, which one job cannot hold: {dupes[:5]}")
    return pdfs, skipped


def sha256_of(path):
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def put_file(path, grant):
    """PUT one file to its presigned URL. A fresh request, not the API
    session: the URL carries its own credential, and an Authorization header
    on top makes the object store refuse it."""
    with path.open("rb") as fh:
        r = requests.put(grant["url"], data=fh, headers=grant.get("headers") or {},
                         timeout=600)
    if r.status_code in (200, 201, 204):
        return
    hint = {
        403: "the URL expired (over 15 minutes -- upload fewer files per run) or "
             "the server's public address (MINIO_PUBLIC_ENDPOINT) is not the one "
             "this machine reaches it at",
        404: "the server does not route /api/s3/ to its object store -- its "
             "nginx configuration predates presigned uploads",
    }.get(r.status_code, r.text[:200])
    sys.exit(f"upload of {path.name} failed: HTTP {r.status_code} ({hint})")


def upload(s, api, pdfs, is_public):
    """Presign, PUT every file, register: returns the import job's uuid.
    Nothing is created until the last step, so an interrupted upload leaves
    no half-finished job behind (the staged files are swept server-side)."""
    r = s.post(f"{api}/workspace/imports/datasheets/presign/", json={
        "is_public": is_public,
        "files": [{"filename": p.name, "size": p.stat().st_size} for p in pdfs],
    })
    if r.status_code == 503:
        sys.exit(f"HTTP 503: {error_text(r)} -- if it says UPLOADS_NOT_CONFIGURED, "
                 f"the server has no public object-store address (MINIO_PUBLIC_ENDPOINT); "
                 f"otherwise it is at capacity, retry later")
    staged = check(r).json()
    grants = {g["filename"]: g for g in staged["files"]}

    with ThreadPoolExecutor(PARALLEL_UPLOADS) as pool:
        digests = list(pool.map(sha256_of, pdfs))
        list(pool.map(lambda p: put_file(p, grants[p.name]), pdfs))

    r = check(s.post(f"{api}/workspace/imports/datasheets/", json={
        "staging_uuid": staged["staging_uuid"],
        "is_public": is_public,
        "files": [{"key": grants[p.name]["key"], "filename": p.name, "sha256": d}
                  for p, d in zip(pdfs, digests)],
    }))
    return r.json()["job_uuid"]


def report_rows(rows):
    """Per-datasheet outcome, including the ways one can yield nothing."""
    for row in rows:
        name = row["resolved"].get("filename")
        confirm = row["resolved"].get("confirm") or {}
        found = confirm.get("created", [])
        print(f"      {name}: {row['status']}, {len(found)} part numbers {found[:5]}")
        if row.get("error"):
            print(f"        error: {row['error']}")
        for label in ("rejected", "conflicts", "already_in_workspace"):
            if confirm.get(label):
                print(f"        {label}: {confirm[label][:5]}")


def minted_part_numbers(rows):
    """Every part number this job put in your workspace, across all datasheets.
    One PDF mints a whole family, so this is what must be waited on -- not just
    the row's own component.

    Both outcomes count. `created` is a part this job minted; `linked` is one
    whose datasheet was already in the public catalog, so the job attached the
    existing part instead of digitising it again. Either way it is a new part
    in your workspace with its own uuid."""
    pns = []
    for row in rows:
        confirm = row["resolved"].get("confirm") or {}
        pns.extend(confirm.get("created", []))
        pns.extend(confirm.get("linked", []))
    return pns


def part_status(s, api, part_number):
    """(workspace uuid, ready / processing / pending / failed) for one part
    number, or None if the workspace does not hold it. 404 is an answer here,
    not a fatal error, so this does not go through check()."""
    r = s.get(f"{api}/workspace/components/status/",
              params={"part_number": part_number})
    if r.status_code == 404:
        return None
    newest = check(r).json()["results"][0]
    return newest["component_uuid"], newest["status"]


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

api = f"{args.base_url.rstrip('/')}/api/v1"
s = requests.Session()
s.headers["Authorization"] = f"Bearer {args.token}"

# 1. Upload: presigned URLs, the files straight to the object store, then one
#    call that turns them into an import job.
print(f"[1/3] uploading {len(pdfs)} pdf(s)...")
job = upload(s, api, pdfs, is_public=not args.private)
print(f"      upload complete, {len(pdfs)}/{len(pdfs)} staged. job {job}")

# 2. The upload is done; everything below is server-side progress. Several
#    datasheets are parsed at once, but they are committed strictly in order so
#    that two datasheets from the same family cannot create duplicate parts. A
#    datasheet stays "parsing or queued" until its parts are created, so early
#    polls showing no progress are normal -- a large PDF can take a few minutes.
print("[2/3] processing datasheets (parse -> discover part numbers)")
while True:
    d = check(s.get(f"{api}/workspace/imports/{job}/")).json()
    c = d["counts"]
    # `skipped` is a byte-identical duplicate of an earlier file in this same
    # job. Printed so the numbers always add up to the total -- a datasheet
    # silently missing from the tally reads like a bug.
    print(f"      part numbers discovered in {c.get('created', 0)}/{d['total']}"
          f" datasheets | {c.get('pending', 0) + c.get('deferred', 0)} parsing or queued"
          f" | {c.get('skipped', 0)} duplicate | {c.get('failed', 0)} failed")
    if d["status"] in JOB_DONE:
        break
    time.sleep(POLL_SECONDS)

print(f"      job {d['status']}"
      + (f" -- {d['blocked_reason']}" if d.get("blocked_reason") else ""))
report_rows(d["rows"])

# 3. The parts exist now, but their parameters are still being extracted, and
#    the first part of a family finishes before the rest. Every part number the
#    job put in your workspace is checked, not just the one component each row
#    reports.
#
#    The uuids reported are WORKSPACE component uuids -- your copy of each part
#    -- and that is deliberate: a public upload publishes to the community
#    catalog AND puts a copy in your library. The community part is a different
#    row you do not own, so the workspace uuid is the one to keep in both modes.
wanted = sorted(set(minted_part_numbers(d["rows"])))
if not wanted:
    sys.exit(0)

print(f"[3/3] extracting parameters ({len(wanted)} parts, every family member)")
found, missing, failed = {}, [], []
pending = list(wanted)
while pending:
    still = []
    for pn in pending:
        state = part_status(s, api, pn)
        if state is None:
            missing.append(pn)  # reported, never counted as done
            continue
        found[pn] = state[0]
        if state[1] == "failed":
            failed.append(pn)
        elif state[1] != "ready" and not args.no_wait:
            still.append(pn)
    if not args.no_wait:
        print(f"      {len(wanted) - len(still) - len(missing)}"
              f"/{len(wanted) - len(missing)} parts ready")
    pending = still
    if pending:
        time.sleep(POLL_SECONDS)

print(f"      {len(found)} part(s) in your workspace:")
for part_number in sorted(found):
    print(f"        {found[part_number]}  {part_number}")
if missing:
    print(f"      {len(missing)} part(s) not found in your workspace, "
          f"not checked: {missing[:5]}")
if failed:
    print(f"      {len(failed)} FAILED: {failed[:5]}")
