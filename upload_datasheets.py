#!/usr/bin/env python3
"""
Upload PDF datasheets to datasheets.md

Bulk-uploads PDF files to the datasheets.md service using its "quick upload"
API. The backend automatically extracts manufacturer, part number, and
category from each PDF -- no manual metadata is needed.

Successfully uploaded files are recorded in a local tracking file
(.uploaded.json by default) so the script can be safely re-run without
duplicating work.

Requirements:
    pip install requests

Usage examples:
    # Preview what would be uploaded (dry run)
    python upload_datasheets.py --dir ./my_pdfs --dry-run

    # Upload all PDFs in a folder
    python upload_datasheets.py --dir ./my_pdfs --email user@example.com

    # Upload specific files
    python upload_datasheets.py --files part1.pdf part2.pdf --email user@example.com

    # Upload as private (default is public)
    python upload_datasheets.py --dir ./my_pdfs --private

    # Re-upload everything, ignoring the tracking file
    python upload_datasheets.py --dir ./my_pdfs --all
"""

import argparse
import getpass
import json
import os
import sys
import time

import requests

BASE_URL = "https://datasheets.md"
LOGIN_URL = f"{BASE_URL}/api/auth/login"
UPLOAD_URL = f"{BASE_URL}/api/priv_components/"
DEFAULT_TRACKING_FILE = ".uploaded.json"


def load_tracking(path):
    """Load the set of already-uploaded filenames from the tracking file."""
    if not os.path.exists(path):
        return set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("uploaded", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_tracking(path, uploaded):
    """Persist the set of uploaded filenames to the tracking file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"uploaded": sorted(uploaded)}, f, indent=2)


def get_auth_token(email=None, password=None):
    """Authenticate with datasheets.md and return a JWT access token."""
    if not email:
        email = os.environ.get("DATASHEETS_EMAIL") or input("Email: ").strip()
    if not password:
        password = os.environ.get("DATASHEETS_PASSWORD") or getpass.getpass("Password: ").strip()
    print(f"Logging in as {email}...")

    try:
        response = requests.post(LOGIN_URL, json={"email": email, "password": password})
        response.raise_for_status()
        token = response.json()["access"]
        print("Login successful!")
        return token
    except requests.exceptions.RequestException as e:
        print(f"Login failed: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Server response: {e.response.text}")
        return None
    except KeyError:
        print(f"Login failed: unexpected response format.")
        print(response.json())
        return None


def discover_files(directory, already_uploaded, skip_uploaded=True):
    """Find all PDF files in a directory, optionally skipping already-uploaded ones."""
    pdf_files = []
    for name in sorted(os.listdir(directory)):
        if name.lower().endswith(".pdf"):
            if skip_uploaded and name in already_uploaded:
                continue
            pdf_files.append(name)
    return pdf_files


def upload_files(token, directory, files, *, tracking_path, already_uploaded,
                 is_public=True, delay=2, batch_size=10, batch_pause=30):
    """Upload PDF files to datasheets.md.

    Args:
        token:            JWT access token.
        directory:        Folder containing the PDFs.
        files:            List of filenames to upload.
        tracking_path:    Path to the JSON tracking file.
        already_uploaded: Mutable set of already-uploaded filenames (updated in place).
        is_public:        Whether to mark uploads as public.
        delay:            Seconds to wait between individual uploads.
        batch_size:       Number of uploads before a longer pause.
        batch_pause:      Seconds to wait after each batch.
    """
    headers = {"Authorization": f"Bearer {token}"}
    success_count = 0
    fail_count = 0

    print(f"\nUploading {len(files)} file(s) to {UPLOAD_URL}")
    print(f"Visibility: {'public' if is_public else 'private'}")
    print(f"Pacing: {delay}s between files, {batch_pause}s every {batch_size} files")
    print("-" * 60)

    for i, filename in enumerate(files, 1):
        file_path = os.path.join(directory, filename)

        if not os.path.exists(file_path):
            print(f"[{i}/{len(files)}] SKIP (not found): {file_path}")
            fail_count += 1
            continue

        print(f"[{i}/{len(files)}] Uploading {filename}...", end=" ", flush=True)

        form_data = {}
        if is_public:
            form_data["is_public"] = "true"

        try:
            with open(file_path, "rb") as f:
                resp = requests.post(
                    UPLOAD_URL,
                    headers=headers,
                    data=form_data,
                    files={"datasheet_file": (filename, f, "application/pdf")},
                )

            if resp.status_code in (200, 201):
                uuid = resp.json().get("private_component_uuid", "N/A")
                print(f"OK (uuid: {uuid})")
                success_count += 1
                already_uploaded.add(filename)
                save_tracking(tracking_path, already_uploaded)
            else:
                print(f"FAILED ({resp.status_code})")
                print(f"  {resp.text[:200]}")
                fail_count += 1

        except Exception as e:
            print(f"ERROR: {e}")
            fail_count += 1

        # Pacing
        if i < len(files):
            if i % batch_size == 0:
                print(f"\n--- Batch pause ({batch_pause}s) ---\n")
                time.sleep(batch_pause)
            else:
                time.sleep(delay)

    print("-" * 60)
    print(f"Done. Success: {success_count}, Failed: {fail_count}, Total: {len(files)}")


def main():
    parser = argparse.ArgumentParser(
        description="Upload PDF datasheets to datasheets.md (metadata auto-extracted)"
    )
    parser.add_argument(
        "--dir", default=".",
        help="Directory containing PDFs to upload (default: current directory)"
    )
    parser.add_argument(
        "--files", nargs="+",
        help="Upload specific files instead of scanning a directory"
    )
    parser.add_argument(
        "--tracking-file", default=DEFAULT_TRACKING_FILE,
        help=f"JSON file tracking uploaded filenames (default: {DEFAULT_TRACKING_FILE})"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Upload all PDFs, ignoring the tracking file"
    )
    parser.add_argument(
        "--private", action="store_true",
        help="Upload as private (default is public)"
    )
    parser.add_argument(
        "--delay", type=float, default=2,
        help="Seconds between uploads (default: 2)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=10,
        help="Files per batch before a longer pause (default: 10)"
    )
    parser.add_argument(
        "--batch-pause", type=float, default=30,
        help="Seconds to pause between batches (default: 30)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List files that would be uploaded without uploading"
    )
    parser.add_argument(
        "--email",
        help="Login email (or set DATASHEETS_EMAIL env var)"
    )
    parser.add_argument(
        "--password",
        help="Login password (or set DATASHEETS_PASSWORD env var)"
    )

    args = parser.parse_args()

    # Resolve tracking file path (store next to the PDF directory)
    if os.path.isabs(args.tracking_file):
        tracking_path = args.tracking_file
    else:
        tracking_path = os.path.join(args.dir, args.tracking_file)

    already_uploaded = load_tracking(tracking_path) if not args.all else set()

    # Build file list
    if args.files:
        files = args.files
    else:
        if not os.path.isdir(args.dir):
            print(f"Error: directory not found: {args.dir}")
            sys.exit(1)
        files = discover_files(args.dir, already_uploaded, skip_uploaded=not args.all)

    if not files:
        print("No files to upload.")
        sys.exit(0)

    print(f"Found {len(files)} file(s) to upload from: {os.path.abspath(args.dir)}")
    if already_uploaded:
        print(f"({len(already_uploaded)} file(s) previously uploaded — skipped)")
    for f in files:
        print(f"  - {f}")

    if args.dry_run:
        print("\n(Dry run -- nothing uploaded)")
        sys.exit(0)

    token = get_auth_token(email=args.email, password=args.password)
    if not token:
        sys.exit(1)

    upload_files(
        token=token,
        directory=args.dir,
        files=files,
        tracking_path=tracking_path,
        already_uploaded=already_uploaded,
        is_public=not args.private,
        delay=args.delay,
        batch_size=args.batch_size,
        batch_pause=args.batch_pause,
    )


if __name__ == "__main__":
    main()
