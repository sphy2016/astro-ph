# arXiv daily draft validation

You are helping maintain a personal astro-ph reading diary.

This is a validation workflow only.

Do not append to any monthly diary file.
Do not create or modify `2026/arxiv202606.md` or any other `YYYY/arxivYYYYMM.md` file.
Do not update `ai/state.json`.
Do not modify `ai/work/latest_manifest.json`.
Do not commit changes.
Do not open a pull request.

Read:

- `ai/research_interests.md`
- `ai/work/latest_source_pack.md`
- `ai/work/latest_manifest.json`

Then create or update only:

- `ai/work/draft_entry.md`

Use the research-interest profile to select the most relevant papers from the source pack.

Selection guidance:

- This repo is a personal astro-ph reading diary, not a formal digest site.
- Do not summarize all papers.
- Select a manageable number of papers that best match the interests in `ai/research_interests.md`.
- Prefer papers connected to massive or quiescent galaxies, early galaxy quenching, stellar populations, LyC escape, reionization, galaxy evolution, CGM/IGM, dust, gas, feedback, outflows, or JWST galaxy-evolution science.
- Do not select every high-z or JWST paper automatically.
- If a paper is only loosely relevant, leave it out or put it in a short skipped section.

Writing constraints:

- Use only titles, metadata, and abstracts from `ai/work/latest_source_pack.md`.
- Do not invent results or claims.
- If an abstract is vague, say so briefly.
- Keep the style compact and diary-like.
- English only.
- Use arXiv Markdown links.
- Use `**Aims:**`, `**Methods:**`, `**Results:**`, and `**Conclusions:**` only when useful.
- Avoid hype and generic AI wording.

Expected output file:

`ai/work/draft_entry.md` should contain a draft diary block only. It should be safe for a human to inspect and later append manually.
