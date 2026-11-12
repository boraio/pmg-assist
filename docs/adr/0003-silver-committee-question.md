# 0003 — Silver for committee-question: text, tables and pointer replies

- Status: Accepted (2026-11-05)
- Date: 2026-11-05
- Milestone: 1

## Context

Bronze 0.2 holds 41,156 `committee-question` records (backfill of
2026-10-29). Measurements in `docs/measurements/2026-10-29-committee-question.md`,
plus queries run on 2026-11-05 over the same data, show:

- **Tables carry half the text.** 7,213 replies contain tables; 59.6 of
  121.5 MB of reply text (49%) sits inside them. 415 of those replies have
  under 50 characters of prose outside their tables.
- **Most tables are small, a few are huge.** 17,101 tables: 5,140 have 1–5
  rows, 8,852 have 6–20, 2,698 have 21–100, 392 have 101–1,000 and 19 have
  more. The longest replies are annexures, for example 14,763 rows listing
  named smallholder farmers with the voucher amount each received.
- **Tables rarely mark a header.** 1,002 tables use `<th>`, 1,003 `<thead>`.
  771 use `rowspan` and 1,393 `colspan` greater than 1; 155 contain a nested
  table.
- **Flattening breaks rows.** A tag strip turns a table into one run of text
  (`Province Surname Firstname District Town 42 000,00 …`). A chunk cut from that
  can pair a name with the wrong amount, which would be a misattribution
  carrying a citation.
- **About 2,940 replies only point to an attachment** ("Find reply here" and
  variants). Length alone does not identify them: 16 replies are a real "No.".
- **Five replies embed `data:` images** of up to 60 million characters.
- **Many tables name private individuals**, not public figures.

## Decisions

### 1. One silver row per record

Silver is rebuilt in full from the newest complete 0.2 fetch of each year.
Each record keeps: `record_id` (`pmg-committee-question-<id>`), PMG's `id`,
PMG's `url` as given, `date`, `year`, `code`, `answer_type`, `house_id`,
`minister_id`, `question_to_name` (PMG's extracted text, never shown as an
office label), `asked_by_name`, `asked_by_member_id`, the question, the reply,
`reply_kind`, the attachment list, and the bronze fetch it came from.

### 2. HTML is parsed, not stripped

Question and reply HTML are parsed with `lxml.html`, which recovers the
implied end tags (`</td>`, `</tr>`, `</p>`) that table structure depends on.
Text is kept verbatim apart from decoding entities and collapsing whitespace.
Images are dropped; bronze keeps them.

### 3. Replies are ordered blocks; tables stay tables

A reply is a list of blocks, each a paragraph or a table. A table is a list of
rows, each a list of cell texts, after expanding `rowspan` and `colspan` into
a full grid (a spanned value is repeated in every cell it covers). A nested
table's rows become text inside its cell, joined with " / ".

No header is inferred, because 94% of tables do not mark one. The first row is
kept as the first row. Gold repeats it at the top of every chunk of a split
table, labelled as the table's first row, never as column names.

**A table chunk is only ever split between rows.** Every "X received Y" in a
table then stays on one row, verbatim, inside one chunk.

### 4. Pointer replies are classified by phrase, not length

`reply_kind` is `in_body`, `attachment_pointer` or `empty`.
`attachment_pointer` is set when the reply text, after normalising case and
whitespace, matches a committed list of pointer phrases taken from the
measurements. These records are indexed by their question, with the citation
link, until attachment extraction (a separate, separately measured step)
supplies the reply.

### 5. Private individuals: unredacted for the lab POC only

Names of private individuals in tables are indexed as published by PMG while
the app is lab-only. Separating private individuals from public figures
(anonymising or excluding the former) **blocks any distribution outside the
lab**, alongside the POPIA and PMG-terms items already listed in PROJECT.md.

### 6. Output

`data/silver/committee-question/version=<v>/records.parquet` plus a
`_marker.json` naming the bronze fetches used and the row count. The silver
step writes JSON Lines; the DuckDB CLI converts them to Parquet, so ingest
needs no DuckDB Python package. `make silver` builds it; a rerun over the same
bronze gives the same rows.

## Consequences

- `lxml` becomes the first ingest dependency, pinned, and is installed in CI.
- Silver checks use fixture HTML for spans, nested tables, unclosed cells,
  `data:` images and each pointer phrase, in the existing standalone check
  style.
- Gold needs a chunker that understands blocks and keeps table chunks on row
  boundaries.
- The bronze-to-silver path is local disk on nia, like bronze, until the
  RadosGW bucket exists.

## Open

- The full pointer-phrase list (the measurement shows the top 15 only).
- Whether very large tables (101+ rows) need different chunk sizes or a
  summary block; decided in gold, with retrieval numbers.
- How private individuals are told apart from public figures before
  distribution.
