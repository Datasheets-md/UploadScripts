# Upload Scripts for datasheets.md

Command-line tools for bulk-uploading PDF datasheets to [datasheets.md](https://datasheets.md).

## upload_datasheets.py

Uploads PDF files to the datasheets.md service. The backend automatically extracts manufacturer, part number, and category from each PDF — no manual metadata needed.

Successfully uploaded files are tracked in a local `.uploaded.json` file so the script can be safely re-run without duplicating work.

### Requirements

```
pip install requests
```

### Quick Start

```bash
# Preview which files would be uploaded
python upload_datasheets.py --dir ./my_pdfs --dry-run

# Upload all PDFs in a folder
python upload_datasheets.py --dir ./my_pdfs --email user@example.com

# Upload specific files
python upload_datasheets.py --files part1.pdf part2.pdf --email user@example.com
```

If `--email` and `--password` are not provided, the script will prompt interactively.

You can also use environment variables:

```bash
export DATASHEETS_EMAIL=user@example.com
export DATASHEETS_PASSWORD=yourpassword
python upload_datasheets.py --dir ./my_pdfs
```

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `--dir` | `.` | Directory containing PDFs to upload |
| `--files` | | Upload specific files instead of scanning a directory |
| `--dry-run` | | List files that would be uploaded without uploading |
| `--private` | | Upload as private (default is public) |
| `--all` | | Upload all PDFs, ignoring the tracking file |
| `--tracking-file` | `.uploaded.json` | JSON file tracking uploaded filenames |
| `--delay` | `2` | Seconds between individual uploads |
| `--batch-size` | `10` | Files per batch before a longer pause |
| `--batch-pause` | `30` | Seconds to pause between batches |
| `--email` | | Login email (or `DATASHEETS_EMAIL` env var) |
| `--password` | | Login password (or `DATASHEETS_PASSWORD` env var) |

### Upload Pacing

To avoid overloading the server, the script waits between uploads:
- 2 seconds between each file (configurable with `--delay`)
- Every 10 files, a 30-second pause (configurable with `--batch-size` / `--batch-pause`)

## License

MIT
