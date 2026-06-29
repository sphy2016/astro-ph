# AI helper workflow

This folder keeps Codex-related helper code separate from the personal astro-ph diary files. The year/month Markdown files remain the source of truth for reading notes.

## Commands

Fetch recent arXiv metadata:

```bash
python ai/arxiv_notes.py fetch
```

By default, `fetch` follows the current `astro-ph` new-list batch from arXiv and then retrieves metadata for those arXiv IDs from the Atom API. This matches the website batch boundary, which can span more than one submitted calendar date. Use `--strict-lookback` to run a submitted-date Atom API search with the 36 hour default lookback instead.

Prepare Codex source material:

```bash
python ai/arxiv_notes.py prepare
```

Check whether analysis should run:

```bash
python ai/arxiv_notes.py status
```

## Working files

`ai/work/` is temporary and ignored by git. It holds the latest fetched JSON, source pack, and manifest.

`ai/state.json` is intentionally not ignored. It records the last material fingerprint only after a digest has actually been appended, so future automation can skip repeated Codex analysis.

Run Codex, and any final humanize pass, only when `prepare` does not print `NO_NEW_MATERIAL`. The source pack contains only arXiv metadata and abstracts, so any summary should stay grounded in those fields.
