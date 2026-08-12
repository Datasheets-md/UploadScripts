# Upload Scripts for datasheets.md

Command-line tools for bulk-uploading PDF datasheets to [datasheets.md](https://datasheets.md).

## upload_datasheets.py

Point it at a folder of PDFs. You do **not** supply part numbers — the parser
reads each datasheet, finds every part number in its ordering table, and creates
a component for each one. A datasheet listing 40 orderable variants gives you
40 parts, each with extracted parameters.

The script then waits for parameter extraction to finish on every part, so when
it exits cleanly the data is genuinely ready — not merely uploaded.

### Requirements

```bash
pip install requests
```

Python 3.9 or newer.

### Get a token

Sign in to datasheets.md and go to **Integrations → API**
([datasheets.md/integrations/api](https://datasheets.md/integrations/api)) to
generate a personal token. It looks like `dsh_...`.

```bash
export DATASHEETS_TOKEN=dsh_your_token_here
```

The token is shown once, so store it somewhere safe. Treat it like a password
and keep it out of version control.

### Quick start

```bash
# See what would be uploaded (no token needed)
python upload_datasheets.py --dry-run ./my_pdfs

# Upload a folder
python upload_datasheets.py ./my_pdfs

# Upload individual files
python upload_datasheets.py part1.pdf part2.pdf

# Keep the parts in your workspace instead of publishing them
python upload_datasheets.py --private ./my_pdfs
```

### What you will see

```
[1/3] uploading 2 pdf(s)...
      upload complete, 2/2 staged. job 059005ca-e68e-427e-9ece-d476fda418f3
[2/3] processing datasheets (parse -> discover part numbers)
      part numbers discovered in 0/2 datasheets | 2 parsing or queued | 0 failed
      part numbers discovered in 1/2 datasheets | 1 parsing or queued | 0 failed
      part numbers discovered in 2/2 datasheets | 0 parsing or queued | 0 failed
      job completed
      MCP6006.pdf: created, 1 part numbers ['MCP6006T-E/LT']
      AP7343.pdf: created, 40 part numbers ['AP7343-09FS4-7B', ...]
[3/3] extracting parameters (every part, not just the first in the family)
      AP7343.pdf: 130/130 parts ready
```

The three phases:

1. **Upload** — all files go in a single request. Every file is hashed,
   deduplicated and staged before anything is written, so an interrupted upload
   leaves no half-finished job behind.
2. **Processing** — each datasheet is parsed and its part numbers become
   components.
3. **Parameters** — extraction runs on every part that was created.

### Why progress can look stalled

Phase 2 often shows no movement for the first few polls. That is expected.
Several datasheets are parsed at the same time, but a datasheet counts as done
only once its parts have been created, and creation happens strictly in order so
that two datasheets from the same family cannot produce duplicate parts. So
`2 parsing or queued` means work is actively happening.

A large datasheet takes a few minutes. Phase 3 can take several more on a
family with many parts.

### Re-running is safe

Files are deduplicated by content hash. Uploading the same PDF again resolves to
the datasheet already on file instead of parsing and charging for it twice, so
re-running on a folder you have partly uploaded costs nothing extra. There is no
local tracking file to keep in sync.

### Options

| Flag | Default | Description |
|------|---------|-------------|
| `PATH...` | | One or more PDF files and/or folders (required) |
| `--private` | off | Keep parts in your workspace; default publishes them |
| `--dry-run` | off | List what would be uploaded, then stop. No token needed |
| `--no-wait` | off | Exit once parts exist, without waiting for parameters |
| `--base-url` | `https://datasheets.md` | Or set `DATASHEETS_URL` |
| `--token` | | Or set `DATASHEETS_TOKEN` |

### Notes on file selection

- Folders are scanned one level deep. `.pdf` is matched regardless of case, so
  `DATASHEET.PDF` is included.
- Anything in a folder that is not a `.pdf` is listed as skipped rather than
  silently ignored — check that line if a file you expected is missing.
- A file named directly on the command line is uploaded whatever its extension.
- Limits are 500 files per request and 50 MB per file. Split larger sets and run
  the script more than once.

### Troubleshooting

| Message | What it means |
|---|---|
| `HTTP 401` | Token missing, mistyped or revoked. Generate a new one. |
| `HTTP 403` | The token cannot write to that workspace. |
| `HTTP 404` | Batch upload is not enabled on this server. |
| `HTTP 413` | A single file is over 50 MB. |
| `HTTP 429` | Daily digitisation limit reached. Try again tomorrow. |
| `HTTP 503` | The service is at capacity. Retry later. |
| `no PDFs found in: ...` | The folder held no `.pdf` files. Check the skipped lines. |
| `job blocked -- workspace_parts` | Your plan's part limit was reached. Parts already created are kept. |
| `0 part numbers` on a row | The parser found no ordering table. The datasheet is stored, but no parts were created from it. |

### A note on cost

Each part number found becomes a component, and each new datasheet consumes
digitisation quota. One datasheet can yield over a hundred parts, so try a
single file before pointing the script at a large folder.

## License

MIT
