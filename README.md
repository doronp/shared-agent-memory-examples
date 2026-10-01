# Shared memory for coding agents: three worked examples from recorded SWE-rebench runs

When coding agents for different teams work on the same codebase, each agent starts cold and redoes exploration that another agent has already done: it opens the same files, lists the same directories and runs the same searches. A memory shared across those teams could hand over what was already found. This repository walks through three real benchmark tasks and measures, after the fact, how much of a recorded agent run repeated exploration that earlier runs on the same repository had already done, first by the same team and then by any team.

**No memory system was run.** Everything here is a replay of public, recorded third-party agent runs. The overlap is measured at the level of paths and queries, so every saving is a ceiling. Tokens are tokens, not dollars.

## How to read these examples

Read them in this order: 01 is the best case, 02 is a middle case, and 03 is the counter-case. Each example directory has the same layout:

- `README.md`: the problem (issue text as the agent received it), the real solution (the benchmark's gold patch), what the agent did, what the shared memory held, what it would have saved, whether that memory was still true at the task's base commit (staleness), and caveats.
- `data.json`: every number in that README, with where it comes from.
- `gold.patch` (and `test.patch` in 01 and 03): the benchmark's reference fix and hidden tests. `agent.patch` (02 and 03) is the recorded agent's fix; in 03 it is only the agent's change to `sqlglot/dialects/redshift.py`. In 01 the agent's patch is identical to the gold patch apart from the final newline.
- `trajectory-excerpt.md`: the recorded run, step by step, with the replay class of each step.
- `memory-note-*.md` (and an inline note in 02): **illustrative** memory notes. They are generated mechanically from an earlier recorded run and labelled as such. No agent ever read them.
- `LICENSE-<repo>.txt`: the upstream repository's licence, for the quoted code.

Terms used throughout:

- **Tenant**: within each repository, tasks are sorted by the creation time of their upstream pull request and dealt round-robin to three simulated tenants, which stand in for three teams on the same codebase. A task may only draw on tasks created strictly before it.
- **Own history**: the tenant's own earlier tasks. **Pool**: the earlier tasks of all three tenants. **Cross-tenant increment**: what the pool adds on top of own history.
- **Removable tokens**: the cache-weighted tokens of exploration steps (file reads, directory listings, searches, git lookups) whose path or normalised query an earlier task had already explored.

| Example | Repository | Problem (one line) | What the shared memory held | Removable tokens (ceiling): own history / pool / increment | Verdict |
|---|---|---|---|---|---|
| [01](examples/01-ignite-confusion-matrix/) | [pytorch/ignite](https://github.com/pytorch/ignite) (BSD-3-Clause) | `ConfusionMatrix` flattens one-hot ground truth in the wrong order; a one-line fix (`pytorch__ignite-522`) | A run by another tenant (`pytorch__ignite-484`, 30.9 days earlier) had opened the gold file and (in part) its test file; both were byte-identical at this task's base commit | 10,823 (8.2%) / 39,723 (30.0%) / 28,900 (21.9%) | Best case: another team's run had already opened the file to fix. An outlier: the increment is larger than for 99.5% of replayed tasks |
| [02](examples/02-streamlink-powerapp/) | [streamlink/streamlink](https://github.com/streamlink/streamlink) (BSD-2-Clause) | The powerapp plugin does not match `/tvs/` URLs; a one-line regex fix (`streamlink__streamlink-2229`) | Only a `tests/plugins` directory listing from another tenant's task (`streamlink__streamlink-2228`, same base commit, PR opened 5.6 minutes earlier, run not resolved); no earlier task opened the gold file | 34,283 (30.5%) / 46,777 (41.6%) / 12,494 (11.1%) | Orientation, not the answer. Ordered by issue date instead of PR date, its only cross-tenant source would come after it |
| [03](examples/03-sqlglot-json-parse/) | [tobymao/sqlglot](https://github.com/tobymao/sqlglot) (MIT) | Redshift `JSON_PARSE` is rewritten as `PARSE_JSON`; a one-line fix (`tobymao__sqlglot-2443`) | Nothing beyond own history: the tenant's own earlier tasks (mainly `tobymao__sqlglot-2412`) already covered every repeated step | 91,286 (51.5%) / 91,286 (51.5%) / 0 (0.0%) | Counter-case: the tenant was repeating itself, and sharing adds nothing at path level. Counting only remembered copies that are still byte-identical, other tenants' fresher copies add 4,888 tokens (2.8%) |

Percentages are shares of that task's cache-weighted tokens. All three recorded runs resolved their task.

## What this is and is not

- **An offline replay of public recorded runs.** The runs are Qwen3-Coder-480B-A35B-Instruct working in the OpenHands agent scaffold (v0.54.0), from the public dataset [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories), on tasks from [nebius/SWE-rebench](https://huggingface.co/datasets/nebius/SWE-rebench). We did not run any agent.
- **No live system.** No memory system was run, no agent was given a memory, and no product is shown. The memory notes are illustrative, built mechanically from earlier recorded runs.
- **A path-level ceiling, not a measured saving.** A step counts as repeated if an earlier task opened the same path, listed the same directory or ran the same normalised search. That assumes the step could be skipped outright and the rest of the run would not change. It credits partial views as full reads, and the cost of injecting a note is not subtracted unless stated. A real system would also have to retrieve the right note and the agent would have to trust it.
- **Tokens, not dollars.** Tokens are characters / 4. The default measure is cache-weighted: a message counts 1.0 the first time the model reads it and 0.1 on every later call that re-reads it as context, and each model call is also counted once as output. That models prompt caching; it is not any provider's bill.
- **Synthetic tenants and one run per task.** The three tenants are an artificial split of one repository's history. The dataset has several recorded runs per task; the replay uses one, the one with the lowest md5 of its trajectory id. A different run would explore differently.
- **Chosen examples, not typical ones.** The three tasks were picked to be easy to follow and to span the range from large to zero. The aggregate numbers below are the typical picture.

## Headline offline numbers

All from the same offline replay, with no agent run:

1. **Cross-tenant increment.** Over 1,179 tasks in 18 repositories (each with at least 30 recorded tasks), own history covers 14.80% of all cache-weighted tokens and the 3-tenant pool covers 18.05%. Sharing across tenants adds **3.25 percentage points** of tokens.
2. **Cold start.** The increment is largest for a tenant with little history of its own and shrinks as that history grows: **4.5%** of tokens for tasks with 0-4 earlier own tasks (270 tasks), 3.6% with 5-19 (601 tasks), and **1.4%** with 20 or more (308 tasks). Over the same groups, the own-history ceiling grows from 8.7% to 14.5% to 20.6%.
3. **Gold-file reuse.** This one uses only the benchmark's reference patches, not agent runs or tokens. In the SWE-rebench test split (116 repositories with at least 30 tasks, 8,636 tasks whose gold patch changes a code file, same round-robin split), the gold patch of an earlier task of the same tenant had already changed at least one of the files the fix must change in **68.6%** of tasks; counting earlier tasks of any tenant, in **84.5%**.

Where these come from: `check_aggregates` (items 1 and 2) and `check_gold_reuse` (item 3) in [scripts/extract_examples.py](scripts/extract_examples.py) recompute every figure above from the replay output and from the public SWE-rebench patches, and the self-check (see [Reproduce](#reproduce)) fails if any of them differs.

The honest reading: sharing mostly helps new tenants, while they have little history of their own. Most repeat work is a tenant repeating itself: of the 18.05% the pool could cover, 14.80 points are already in the tenant's own history. The patch-level numbers point the same way: own history alone already reaches a file the fix must change in most tasks (68.6%).

## Data and credits

- **Agent runs:** [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories), revision `35455389ab51bf5e2306bfd436ef72d0f98bf882`, CC BY 4.0. Trofimova et al., "OpenHands Trajectories with Qwen3-Coder-480B-A35B-Instruct", Nebius blog, 2025.
- **Tasks** (issue text, base commits, gold and test patches, test lists): [nebius/SWE-rebench](https://huggingface.co/datasets/nebius/SWE-rebench), test split, revision `89cdfbab4ab1bd8f5a658bb212d1b63624f4f881`, CC BY 4.0. Badertdinov et al., "SWE-rebench: An Automated Pipeline for Task Collection and Decontaminated Evaluation of Software Engineering Agents", [arXiv:2505.20411](https://arxiv.org/abs/2505.20411), 2025.
- **Model** that produced the recorded runs: [Qwen/Qwen3-Coder-480B-A35B-Instruct](https://huggingface.co/Qwen/Qwen3-Coder-480B-A35B-Instruct) (Apache-2.0). **Agent scaffold:** [OpenHands](https://github.com/OpenHands/OpenHands) v0.54.0 (MIT). Neither is redistributed here.
- **Upstream code** in the patches and excerpts: [pytorch/ignite](https://github.com/pytorch/ignite) (BSD-3-Clause), [streamlink/streamlink](https://github.com/streamlink/streamlink) (BSD-2-Clause), [tobymao/sqlglot](https://github.com/tobymao/sqlglot) (MIT). Each example directory carries the repository's licence text taken at the task's base commit.
- **Licences of this repository:** the code and prose written here are under the MIT licence ([LICENSE](LICENSE)). The excerpts of the datasets and upstream code remain under their own licences; attribution and the changes we made are listed in [DATA-LICENSE.md](DATA-LICENSE.md). None of the dataset, model, scaffold or repository owners has reviewed or endorsed this work.

## Reproduce

Everything is regenerated by one script, run from the repository root. It needs Python 3 with `pyarrow` and `pandas` (the commands below use [uv](https://docs.astral.sh/uv/) to supply them), and the staleness and builder steps call the public GitHub API through an authenticated [`gh`](https://cli.github.com/) CLI.

```bash
# 1. Download the two datasets (about 2.3 GB) into ./data; sizes and SHA-256 are checked against pinned revisions.
uv run --with pyarrow --with pandas python scripts/extract_examples.py download

# 2. Extract tool calls from the trajectories, run the replay, check staleness on GitHub,
#    rebuild examples/*/data.json and the other generated files, then run the self-check.
uv run --with pyarrow --with pandas python scripts/extract_examples.py all
git diff --stat   # the regenerated files should match the committed ones

# Only the self-check (no network), on data already built:
uv run --with pyarrow --with pandas python scripts/extract_examples.py check
```

Individual steps are `extract`, `replay`, `dumps`, `staleness` and `build`. The data directory is `./data` (git-ignored), or `--data DIR`, or `$SMEM_DATA`. The self-check asserts the headline numbers above, compares every per-task figure in each `data.json` and the overview table with the replay output, compares the patches with the datasets, re-extracts every recorded run the examples depend on, and scans the repository for absolute local paths.

Other files: [scripts/per_task_replay.py](scripts/per_task_replay.py) is the replay, [scripts/staleness.py](scripts/staleness.py) the git-object freshness check, and [scripts/dump_trajectory.py](scripts/dump_trajectory.py) dumps one recorded run.

## Questions

Questions and corrections are welcome as GitHub issues.
