# Bronze committee-question: measurements, 2026-10-29

Source: `make measure` (`ingest/sql/measure_committee_question.sql`) over the
bronze 0.2 backfill of 2026-10-29. All numbers are from that run.

## Completeness

- 18 years with a complete fetch, 2008–2026 (no records for 2011).
- 41,156 rows, 41,156 distinct ids. The 0.1 backfill had 41,119 rows holding
  only 39,299 ids, because PMG pages by `date desc` alone with LIMIT/OFFSET.
- 0 records whose `year` field disagrees with their partition.
- Busiest year 2025 (7,540). No day exceeded the 500-record page (no year
  aborted); the busiest day in the 0.1 data had 165 records.

## Replies

- 20 replies are empty after stripping tags.
- 2,921 replies are under 50 characters; 2,940 short-or-empty replies have a
  `source_file`. Almost all of the short ones are pointers to an attached
  document ("Find reply here" 1,529, "Find here: Reply" 519, "Attached find
  here: Reply" 144 + 134, and spelling variants).
- 16 replies are literally "No.". A short reply is not always a pointer, so
  silver must match pointer phrases, not length.
- Reply text: 121.5 MB in total, median 1,198 characters, p95 7,649.
- The five largest replies are 9–60 million characters of HTML but only
  2,166–15,768 characters of text. All five carry inline `data:` images.
  Silver strips images; bronze keeps them.
- The longest reply by text is 2,478,334 characters. It is not among the
  image-heavy five. Not yet examined.

## Attachments

- 1,315 records have at least one file in `files` (up to 27); 39,841 have none.

## Attribution

- 51 records have no `asked_by_member_id`, 18 no `asked_by_name`.
- 22 records have no `minister_id`.
- `question_to_name` is extracted text, not a label: up to 72 spellings per
  `minister_id`, some carrying fragments of the question or the asker's
  sentence, and some that name a different office entirely (e.g. "Minister of
  Health" under minister 28, Sport, Arts and Culture). The office shown to a
  user comes from PMG's `minister_id` link, with a link to the PMG record,
  and is labelled as PMG's.

## Houses and answer types

- written, house_id 3: 38,826; written, house_id 2: 1,849; oral, house_id 3: 481.
  (In the 0.1 v1 data house 3 was "NA" and house 2 "NCOP".)

## Open

- What the 2,478,334-character reply is, before chunk sizes are chosen.
- Extracting the ~2,940 attachment-only replies (e.g. `.docx`): a separate
  step with its own measurement.
