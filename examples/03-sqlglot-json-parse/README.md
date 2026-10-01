# Example 3: sqlglot, Redshift `JSON_PARSE` (the counter-case: sharing adds nothing)

## What you are looking at

This is a **replay**. No memory system was run, and no product appears here. We took a run that a third party had
already recorded: the agent Qwen3-Coder-480B-A35B-Instruct, working in OpenHands, on one task from the SWE-rebench
benchmark. Its trajectory comes from the public dataset `nebius/SWE-rebench-openhands-trajectories`. After the fact, we
checked which of its exploration steps (file reads, directory listings, searches) had already been done by earlier
recorded runs on the same repository. The earlier runs are dealt to three simulated "tenants" (see
[How to read these examples](../../README.md#how-to-read-these-examples) in the top-level README).

This task belongs to tenant-3. It is the **counter-case**. Its own tenant's history already covers exploration steps
worth half (51.5%) of the run's tokens. Pooling the other two tenants' history adds **zero** further overlap at path
level, and only a 2.8% sliver once you ask which remembered copies are still byte-identical. Every number below is in
[data.json](data.json), with its source. [build_data.py](build_data.py) regenerates all of it. Tokens mean
characters/4. They are not dollars.

## The problem

- Task: `tobymao__sqlglot-2443` from SWE-rebench (test split). Task created 2023-10-23 (`created_at` is the creation
  time of the upstream pull request).
- Repository at the base commit:
  [tobymao/sqlglot @ fdb1668](https://github.com/tobymao/sqlglot/tree/fdb166801144b721677d23c195e5bd3d35ee8841)
  (sqlglot 18.16, MIT licence).
- Issue [#2442](https://github.com/tobymao/sqlglot/issues/2442), fixed by PR
  [#2443](https://github.com/tobymao/sqlglot/pull/2443). The issue text, verbatim as given to the agent:

> Erroneous handling of redshift's JSON_PARSE
> **sqlglot version: 18.16.1**
>
> **Fully reproducible code snippet**
> ```python
> import sqlglot
> sql = "SELECT JSON_PARSE('[10001,10002,\"abc\"]');"
> parsed = sqlglot.parse_one(sql,dialect="redshift")
> parsed.sql(dialect="redshift")
> #'SELECT PARSE_JSON(\'[10001,10002,"abc"]\')'
> ```
> The generated sql triggers an error when executed in redshift
>
> >Failed to execute query: ERROR: function parse_json("unknown") does not exist
>   Hint: No function matches the given name and argument types. You may need to add explicit type casts.
>
> **Official Documentation**
> https://docs.aws.amazon.com/redshift/latest/dg/JSON_PARSE.html

## The real solution

This is the upstream fix (the benchmark's gold patch, [gold.patch](gold.patch)):

```diff
diff --git a/sqlglot/dialects/redshift.py b/sqlglot/dialects/redshift.py
index 51b91150..df70aa77 100644
--- a/sqlglot/dialects/redshift.py
+++ b/sqlglot/dialects/redshift.py
@@ -175,6 +175,7 @@ class Redshift(Postgres):
             exp.GeneratedAsIdentityColumnConstraint: generatedasidentitycolumnconstraint_sql,
             exp.JSONExtract: _json_sql,
             exp.JSONExtractScalar: _json_sql,
+            exp.ParseJSON: rename_func("JSON_PARSE"),
             exp.SafeConcat: concat_to_dpipe_sql,
             exp.Select: transforms.preprocess(
                 [transforms.eliminate_distinct_on, transforms.eliminate_semi_and_anti_joins]
```

The bug: `exp.ParseJSON` renders as its default name `PARSE_JSON`. Presto already overrides that to `JSON_PARSE`, and
Redshift did not. The fix is one line in Redshift's generator that copies Presto's override. The hidden test
([test.patch](test.patch)) adds `self.validate_identity("SELECT JSON_PARSE('[]')")` to
`tests/dialects/test_redshift.py`.

## What the agent did

The recorded run `chatcmpl-98873fbf910d2c75c859d7a413fd1875` took 63 LLM calls (one tool call each) and **resolved**
the task (the hidden tests pass). Its change to `sqlglot/dialects/redshift.py` is identical to the gold line
([agent.patch](agent.patch)). Its submitted diff also contained 3 scratch files it created (`reproduce_issue.py`,
`comprehensive_test.py` and `test_json_parse_fix.py`) and `issue.md`. The agent did not write `issue.md`: it is a copy
of the issue text that was already in the sandbox before the agent's first action (it appears in the step-2 listing).
It is not part of the repository at the base commit, so the diff shows it as a new file.

Key steps follow. All 63 steps are in [trajectory-excerpt.md](trajectory-excerpt.md). "Tokens" is the cache-weighted
footprint: the observation plus the call that issued it, counted in full on the first LLM call that reads it and at 0.1
on every later LLM call that carries it in context (the issuing call is also counted once as model output). "Earlier
work?" says whether an earlier task in the same tenant ("own") or in another tenant ("other") had already explored the
same path or run the same search.

| Step | Action | File / query | Tokens | Earlier work? |
|---:|---|---|---:|---|
| 2 | list | sandbox root (outside the repo) | 1,883 | own 30 tasks, other 64 |
| 3 | list | `.` (repo root) | 7,794 | own 16, other 38 (latest own: sqlglot-2412) |
| 4 | read | `README.md` (full) | 30,343 | own 32, other 66 (latest own: sqlglot-2412) |
| 5 | read | `Makefile` | 1,442 | own 11, other 22 (latest own: sqlglot-2412) |
| 7 | run | reproduce: output is `SELECT PARSE_JSON(...)` | 1,264 | not exploration |
| 9 | list | `tests/dialects` | 2,724 | own 7, other 7 |
| 11 | search | `find ... grep -l "JSON_PARSE\|PARSE_JSON"` | 1,307 | **no** |
| 12 | list | `sqlglot/dialects` | 5,789 | own 19, other 26 (latest own: sqlglot-2412) |
| 14 | search | `grep ... presto.py`: finds `exp.ParseJSON: rename_func("JSON_PARSE")` | 592 | **no** |
| 15 | read | `sqlglot/expressions.py` [4705-4720] | 1,359 | own 18, other 35 |
| 16 | read | `sqlglot/dialects/redshift.py` (full) | 14,196 | own 2, other 2 (latest own: sqlglot-2412) |
| 22 | search | `grep -rn "ParseJSON" sqlglot/dialects/` | 1,016 | **no** |
| 25 | read | `sqlglot/generator.py` [1-50] | 3,529 | own 15, other 20 |
| 31 | read | `tests/dialects/test_redshift.py` (full) | 19,837 | own 1, other 1 (latest own: sqlglot-2412) |
| 33 | think | "Presto overrides this ... Redshift doesn't have any override for ParseJSON" | 1,843 | not exploration |
| 38 | read | `sqlglot/dialects/bigquery.py` [1-50] | 2,390 | own 4, other 4 |
| 43 | edit | `redshift.py`: adds `exp.ParseJSON: rename_func("JSON_PARSE"),` | 4,707 | not exploration |
| 47 | run | `python -m unittest tests.dialects.test_redshift`: 8 tests OK | 732 | not exploration |
| 63 | finish | submit | 842 | |

Totals for the run:

- 177,418 cache-weighted tokens. Of these, 28,753 are the system and task prompts and 148,665 are the 63 steps.
- 30 first-touch exploration actions, costing 105,046 tokens:
  - 11 repeat earlier work: the 11 non-search rows above marked with "own".
  - The other 19 are new: 18 searches, plus a read of `issue.md`, the sandbox copy of the issue text.
- **None of the 18 searches had ever been run by any earlier task, in any tenant.** Those searches are what found the
  fix (steps 11, 14, 22).
- Why the README costs so much: it was read once at step 4, at 4,420 tokens, and then carried in context for the rest
  of the run. The observation therefore counts 6.8 times (1.0 on the first call that reads it, plus 0.1 on each of
  the 58 calls after that). With the call that issued it, its footprint is 30,343 tokens.

## The shared memory

At this task's creation time, tenant-3 had 32 earlier tasks on sqlglot and the 3-tenant pool had 98. Two of the
earlier tenant-3 tasks matter most here.

### tobymao__sqlglot-2412 (tenant-3, 2023-10-15, 7.8 days earlier)

- Issue [#2411](https://github.com/tobymao/sqlglot/issues/2411), "Redshift Dialect - GROUP BY clause causes parsing
  error although query is valid", fixed by PR [#2412](https://github.com/tobymao/sqlglot/pull/2412) ("Fix(redshift):
  add a missing retreat in the group by parser"). The gold fix is in `sqlglot/parser.py` (+3 lines).
- Recorded run `chatcmpl-0d54e25a2a739d51306048474118081c`: resolved, 97 LLM calls, 421,154 cache-weighted tokens. It
  edited `sqlglot/parser.py` and `tests/dialects/test_redshift.py`.
- Overlap with this task: steps 3, 4, 5, 12, 16 and 31, i.e. the repo root listing, `README.md`, `Makefile`, the
  `sqlglot/dialects` listing, **`redshift.py` (the file the fix goes into)** and `test_redshift.py`. That is
  **79,401 tokens (44.8% of this task)**.
- None of its 20 searches matches a search this task ran. They were about `CREATE VIEW`, the select and
  query-modifier parsing code, tokens such as `NO` and `WITH`, and `AT TIME ZONE`. None of them mentions JSON.
- Illustrative memory note: [memory-note-sqlglot-2412.md](memory-note-sqlglot-2412.md).

### tobymao__sqlglot-1143 (tenant-3, 2023-02-09, 255 days earlier)

- Issue [#1141](https://github.com/tobymao/sqlglot/issues/1141), "snowflake: transpiling "COPY INTO" raises
  ParseError", fixed by PR [#1143](https://github.com/tobymao/sqlglot/pull/1143) ("Add COPY as a command"). The gold
  fix touches `sqlglot/dialects/redshift.py` and `sqlglot/tokens.py` (+1/-1).
- Recorded run `chatcmpl-35f84b1cce52d989c43407acc407525d`: resolved, 54 LLM calls, 194,532 cache-weighted tokens. Its
  agent fixed the problem in `snowflake.py` instead, but it read `redshift.py` in full along the way.
- Overlap with this task: steps 2, 3, 4, 5, 12 and 16 (sandbox root, repo root, `README.md`, `Makefile`,
  `sqlglot/dialects`, `redshift.py`). That is **61,447 tokens (34.6%)**.
- Illustrative memory note: [memory-note-sqlglot-1143.md](memory-note-sqlglot-1143.md).

**About the memory notes.** Both notes are **ILLUSTRATIVE**. No memory system produced them. `build_data.py` generates
them mechanically from the recorded earlier trajectories: the paths those runs listed, read and searched, the files they
edited, and the outcome. Entries that this task later explored again are marked `[overlap]`.

The other tenants' history covers nothing extra. Every one of the 11 repeated actions is already covered by
tenant-3's own history, so the cross-tenant pool adds no action. Tenant-2's history does hold the other two earlier
tasks whose gold fixes edited `redshift.py` (sqlglot-767 and sqlglot-790, from 2022). Tenant-3's own history already
had two such tasks (sqlglot-1143 and sqlglot-1640).

## What it would have saved (ceiling)

| | Repeated first-touch actions | Tokens (cache-weighted) | Share of task |
|---|---:|---:|---:|
| Own history (tenant-3 only) | 11 of 30 | 91,286 | 51.5% |
| Pool (all 3 tenants) | 11 of 30 | 91,286 | 51.5% |
| **Cross-tenant increment** | **0** | **0** | **0.0%** |

- Of the 91,286 own-history tokens, 79,401 come from sqlglot-2412 alone. The remaining 11,885 come from older tenant-3
  tasks: the sandbox listing, `tests/dialects`, `expressions.py`, `generator.py` and `bigquery.py`.
- Counting each repeated observation once, with no re-read weighting, the repeats are 15,716 tokens for own history and
  15,716 for the pool.
- **This is a ceiling, not a saving.**
  - It assumes that any repeated read, listing or search could be skipped entirely.
  - The agent edited `redshift.py`, so it would still have to open that file: an editor cannot replace text it has
    not seen.
  - The steps that actually found the fix were new searches that no earlier task had run.
- This task is not typical for its own-history share.
  - Its 51.5% is the **2nd-highest of all 1,179 replayed tasks**.
  - On sqlglot (275 tasks) the median own share is 19.0% and the median cross-tenant increment is 0.37%.
- The zero increment is common.
  - 107 of the 275 sqlglot tasks, and 376 of all 1,179, have a zero increment.
  - Among the 308 tasks that already have 20 or more own-history tasks, 123 have a zero increment.

## Staleness check

Path-level overlap ignores whether the remembered content is still current. For each overlapping repo path,
`scripts/staleness.py` compares the git object id at the earlier task's base commit with the one at this task's base
commit. Files use blob ids. Directories use tree ids, which is strict: any change anywhere below the directory counts
as stale.

- **sqlglot-2412 → this task:** 39 commits and 80 changed files apart
  ([compare](https://github.com/tobymao/sqlglot/compare/f2ce11ffa7bb6c4eec5e9ad1f8dfe78112e00d58...fdb166801144b721677d23c195e5bd3d35ee8841)).
  - Still byte-identical: `README.md` and `Makefile`, 31,785 of the 79,401 tokens (40.0%).
  - Changed: both directory listings, `redshift.py` and `test_redshift.py`.
  - The `redshift.py` change is only 2 added lines (214 → 216 lines), both unrelated to JSON: the import and the
    `TRANSFORMS` entry for `generatedasidentitycolumnconstraint_sql`.
  - `test_redshift.py` gained 17 lines and lost 8 (439 → 448 lines), and none of those lines mentions JSON.
  - So the stale copy of `redshift.py` would still have shown that Redshift has no `ParseJSON` override. [Reasoned
    from the diff]
- **sqlglot-1143 → this task:** 1,330 commits and 232 changed files apart
  ([compare](https://github.com/tobymao/sqlglot/compare/bb01c7efcfa85384fe7b9e02b33f5bc8fe54af95...fdb166801144b721677d23c195e5bd3d35ee8841)).
  - All 5 overlapping repo paths changed, so 0% of the 59,564 checkable tokens is fresh. (The sandbox-root listing is
    outside the repo and cannot be checked.)
  - `redshift.py` grew from 130 to 216 lines: +154/-68 by the Python difflib line diff that `build_data.py` runs.
    `git diff` (and so the compare page) splits the same change slightly differently, with the same net +86 lines.

**The only place the other tenants matter is freshness.** Take, for each repeated path, the most recent remembered
copy, and keep it only if it is still byte-identical:

| | Byte-identical tokens | Share of task |
|---|---:|---:|
| Freshest copy in own history | 31,785 (`README.md`, `Makefile`) | 17.9% |
| Freshest copy in the pool | 36,673 (adds `expressions.py`, `generator.py`) | 20.7% |
| **Content-level cross-tenant increment** | **4,888** | **2.8%** |

- The extra copies come from tenant-2's `sqlglot-2439`, created 20 hours before this task. Its base commit is 2 commits
  behind this task's. Tenant-3's newest copies of those two files come from sqlglot-2296 and sqlglot-2306, about a
  month earlier and 142 and 133 commits behind. Both files have changed since.
- Every directory listing is stale under the strict tree-id test.

## Caveats

- **Replay, not a live system.** These are recorded third-party runs. Nothing was skipped in reality, and nobody
  measured how an agent with memory would behave.
- **Path/query-level ceiling.** "Repeated" means that the same path or the exact same search command appeared earlier.
  It does not mean the earlier observation would have answered this task's question. For example, the same file can be
  read for different reasons.
- **The cost of the memory itself is not counted.** A real note injected into context also costs tokens, and it costs
  them on every call.
- **The agents had no memory.** Earlier runs explored for their own task, so what they "remember" is incidental.
- **One model, one scaffold.** All runs are Qwen3-Coder-480B-A35B-Instruct on OpenHands v0.54.0, with one trajectory
  per task (the one with the lowest md5 of its trajectory id).
- **Simulated tenants.** Tasks from one public repository are dealt round-robin to 3 tenants. Real tenants would have
  different repositories, forks and timing.
- **`created_at` is a proxy for time.** It is the PR creation time. History means tasks with a strictly earlier
  `created_at`.
- **Tokens are characters/4**, not tokenizer counts, and not dollars.
- **Atypical selection.** This task was chosen as the counter-case. Its own-history share is 2nd-highest of 1,179
  tasks.

## Data, licences and attribution

- Trajectories: [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories)
  (CC BY 4.0). Trofimova et al., "OpenHands Trajectories with Qwen3-Coder-480B-A35B-Instruct", Nebius blog, 2025.
  Excerpts in [trajectory-excerpt.md](trajectory-excerpt.md) and the illustrative notes are trimmed, and their sandbox
  paths are shortened to repo-relative paths. Those changes are stated in each file.
- Task metadata, issue text and gold/test patches: [nebius/SWE-rebench](https://huggingface.co/datasets/nebius/SWE-rebench)
  (CC BY 4.0). Badertdinov et al., "SWE-rebench: An Automated Pipeline for Task Collection and Decontaminated
  Evaluation of Software Engineering Agents", arXiv:2505.20411, 2025.
- Code excerpts from [tobymao/sqlglot](https://github.com/tobymao/sqlglot) (MIT, Copyright (c) 2023 Toby Mao). See
  [LICENSE-sqlglot.txt](LICENSE-sqlglot.txt).
- To reproduce, run [../../scripts/extract_examples.py](../../scripts/extract_examples.py) from the repo root (see
  "Reproduce" in the [top-level README](../../README.md)). It downloads the two HF datasets into `data/`, builds
  `trajs.parquet` and `actions.parquet` (extraction), the replay outputs (`scripts/per_task_replay.py`) and the
  staleness JSONs (`scripts/staleness.py`), and then runs
  `uv run --with pyarrow --with pandas python examples/03-sqlglot-json-parse/build_data.py`. The freshness checks need
  the `gh` CLI, because they call the public GitHub API.
