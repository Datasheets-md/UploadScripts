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

> **Switch to the workspace you want to upload into before creating the token.**
> A token is permanently bound to whichever workspace was active when you
> generated it, and that workspace is where every upload lands. See
> [Tokens are workspace-scoped](#tokens-are-workspace-scoped) below.

Sign in to datasheets.md, switch to your target workspace, then go to
**Integrations → API**
([datasheets.md/integrations/api](https://datasheets.md/integrations/api)) and
generate a personal token. It looks like `dsh_...`.

```bash
export DATASHEETS_TOKEN=dsh_your_token_here
```

The token is shown once, so store it somewhere safe. Treat it like a password
and keep it out of version control.

### Tokens are workspace-scoped

A personal API token is bound to **exactly one workspace** — the one that was
active when you created it. That binding decides where your uploads go:

- Everything this script creates lands in the token's workspace.
- The binding is fixed at creation and **cannot be changed or overridden**. The
  server ignores any workspace sent by a client, so there is no flag on this
  script to redirect uploads elsewhere. The token alone decides.
- To upload into a different workspace, switch to it in the web app and generate
  a **second token**. Keep the two apart — the only visible difference is the
  workspace you were in when each was created.

Integrations → API lists **only the tokens belonging to the workspace you are
currently in**. So if a token you created is not in the list, you are looking at
a different workspace — switch workspace and check again.

That also means the page cannot tell you which workspace an unlabelled token
came from. Name tokens after their workspace (`upload-acme-prod`,
`upload-scratch`) so they stay distinguishable later, especially if you run
uploads on a schedule.

If parts land somewhere unexpected, the token is almost always the reason.

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
      part numbers discovered in 0/2 datasheets | 2 parsing or queued | 0 duplicate | 0 failed
      part numbers discovered in 1/2 datasheets | 1 parsing or queued | 0 duplicate | 0 failed
      part numbers discovered in 2/2 datasheets | 0 parsing or queued | 0 duplicate | 0 failed
      job completed
      MCP6006.pdf: created, 25 part numbers ['MCP6006T-E/OT', ...]
      AP7343.pdf: created, 40 part numbers ['AP7343-09FS4-7B', ...]
[3/3] extracting parameters (65 parts, every family member)
      52/65 parts ready
      65/65 parts ready
```

`duplicate` counts files that were byte-identical to an earlier file in the same
upload. They are skipped rather than parsed twice, and the four numbers always
add up to the total.

The three phases:

1. **Upload** — all files go in a single request. Every file is hashed,
   deduplicated and staged before anything is written, so an interrupted upload
   leaves no half-finished job behind.
2. **Processing** — each datasheet is parsed and its part numbers become
   components.
3. **Parameters** — extraction runs on every part that was created, and the
   script waits for all of them. One datasheet mints a whole family, so this
   covers every part number the upload produced, not just one per file.

   This works the same whether you published the parts or kept them private
   with `--private`.

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
| `HTTP 403` | The token's workspace is gone, or your access to it was removed. |
| Parts in the wrong workspace | The token decides the destination. Create a token while in the workspace you want. |
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
