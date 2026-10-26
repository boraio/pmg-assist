-- Measure bronze committee-question before designing silver.
-- Run from the repo root:  duckdb < ingest/sql/measure_committee_question.sql
--
-- UNTESTED: written without a DuckDB to run it against. Expect to fix syntax
-- on the first run. Paste the output back, errors included.
--
-- `results` is read as JSON rather than an inferred struct, following the
-- ghpulse lesson: inferring one struct over drifting records is fragile.
-- hive_partitioning=false also follows ghpulse; partitions come from the filename.

CREATE OR REPLACE TEMP VIEW pages AS
SELECT
    filename,
    regexp_extract(filename, 'year=([0-9]+)', 1)::INT AS part_year,
    regexp_extract(filename, 'fetched=([0-9TZ]+)', 1)  AS fetched,
    "count"                                            AS api_count,
    results
FROM read_json(
    'data/bronze/committee-question/year=*/fetched=*/page=*.json',
    columns = {'count': 'BIGINT', 'next': 'VARCHAR', 'results': 'JSON[]'},
    filename = true,
    hive_partitioning = false,
    maximum_object_size = 268435456
);

-- Only the newest fetch of each year that has a complete marker is used.
-- Markers are not read here, so this takes the newest fetch per year:
-- run it only after the backfill prints OK for every year.
CREATE OR REPLACE TEMP VIEW recs AS
WITH latest AS (
    SELECT part_year, max(fetched) AS fetched FROM pages GROUP BY part_year
)
SELECT p.part_year, unnest(p.results) AS r
FROM pages p JOIN latest l USING (part_year, fetched);

CREATE OR REPLACE TEMP TABLE cq AS
SELECT
    part_year,
    (r->>'id')::BIGINT                 AS id,
    r->>'code'                         AS code,
    (r->>'date')::DATE                 AS date,
    (r->>'year')::INT                  AS year,
    r->>'answer_type'                  AS answer_type,
    r->'house'->>'name_short'          AS house,
    (r->>'minister_id')::BIGINT        AS minister_id,
    r->>'question_to_name'             AS question_to_name,
    r->>'asked_by_name'                AS asked_by_name,
    (r->>'asked_by_member_id')::BIGINT AS asked_by_member_id,
    r->>'question'                     AS question,
    r->>'answer'                       AS answer_html,
    -- crude tag strip, enough to measure; silver does this properly
    trim(regexp_replace(coalesce(r->>'answer', ''), '<[^>]+>|&nbsp;', ' ', 'g')) AS answer_text,
    (r->'source_file') IS NOT NULL AND (r->>'source_file') <> 'null' AS has_source_file
FROM recs;

.print '== totals: rows vs distinct ids (should be equal)'
SELECT count(*) AS rows, count(DISTINCT id) AS ids FROM cq;

.print '== per year: rows, date range, and records whose own year disagrees with the partition'
SELECT part_year, count(*) AS rows, min(date) AS first, max(date) AS last,
       count(*) FILTER (WHERE year IS DISTINCT FROM part_year) AS year_mismatch
FROM cq GROUP BY part_year ORDER BY part_year;

.print '== reply coverage: is the answer in the body, or only in an attached file?'
SELECT
    count(*)                                                       AS rows,
    count(*) FILTER (WHERE answer_html IS NULL)                    AS answer_null,
    count(*) FILTER (WHERE length(answer_text) = 0)                AS answer_empty,
    count(*) FILTER (WHERE length(answer_text) BETWEEN 1 AND 49)   AS answer_under_50_chars,
    count(*) FILTER (WHERE length(answer_text) < 50 AND has_source_file) AS short_but_has_file
FROM cq;

.print '== the short answers, to see what they say (e.g. "Find reply here")'
SELECT answer_text, count(*) AS n
FROM cq WHERE length(answer_text) BETWEEN 1 AND 49
GROUP BY 1 ORDER BY n DESC LIMIT 15;

.print '== text volume (MB) and reply length percentiles (chars)'
SELECT
    round(sum(length(question)) / 1e6, 1)   AS question_mb,
    round(sum(length(answer_text)) / 1e6, 1) AS answer_mb,
    quantile_cont(length(answer_text), 0.5)  AS answer_p50,
    quantile_cont(length(answer_text), 0.95) AS answer_p95,
    max(length(answer_text))                 AS answer_max
FROM cq;

.print '== attribution coverage: who asked, who was asked'
SELECT
    count(*) FILTER (WHERE asked_by_member_id IS NULL) AS no_asker_id,
    count(*) FILTER (WHERE asked_by_name IS NULL)      AS no_asker_name,
    count(*) FILTER (WHERE minister_id IS NULL)        AS no_minister_id
FROM cq;

.print '== codes are not unique ids: codes reused across years'
SELECT count(*) AS codes_reused FROM (
    SELECT code FROM cq GROUP BY code HAVING count(DISTINCT year) > 1
);

.print '== answer type and house'
SELECT answer_type, house, count(*) AS n FROM cq GROUP BY ALL ORDER BY n DESC;

.print '== addressee names per minister_id (more than one name = portfolio renamed or reshuffled)'
SELECT minister_id, count(DISTINCT question_to_name) AS names,
       string_agg(DISTINCT question_to_name, ' | ') AS as_recorded
FROM cq GROUP BY minister_id HAVING count(DISTINCT question_to_name) > 1
ORDER BY names DESC LIMIT 15;
