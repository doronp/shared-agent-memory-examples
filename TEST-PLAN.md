# Test plan E0: does memory cut coding-agent cost on top of RTK?

## 1. Purpose

**Question.** Coding agents use [RTK](https://github.com/rtk-ai/rtk) to compact command output. On top of that, does memory cut agent cost while the success rate stays the same? The memory is either a team's own or pooled across 3 teams working on the same codebase.

**Why a paid test.** The replay in the [README](README.md) measured overlap after the fact on recorded runs, so it gives only upper limits:
- no memory system ran;
- it cannot show how an agent acts when handed memory;
- it cannot check that the agent still solves the task.

Settling the question needs live agent runs, paid for and graded by the benchmark's own test verifier. The null hypotheses this test addresses are listed in [HYPOTHESES.md](HYPOTHESES.md), which also records the offline and literature results that set these gates. The gates (section 8) and limits (section 11) below carry the same IDs: S1a, S1b, S2a, S2b, S2c, B1 and B2.

## 2. Status

Pre-registration draft, 2026-10-01. Frozen with a git tag in this repository before the first paid run. Changes after the freeze are listed under Deviations.

Stage 2 items marked **open** are fixed before the first Stage 2 trial. Each such fix is listed under Deviations.

## 3. Setup

### Benchmark and repositories

- **Benchmark.** SWE-bench Pro, as the Harbor dataset `swebenchpro@1.0` (laude-institute/harbor-datasets commit `c8e8f3fac7097accaacf261d74c3d6f441de45b1`). Task images are `jefzda/sweap-images:<tag>`.
  - Only tasks that appear in both the Hugging Face test split and the Harbor dataset are used.
- **Repositories.** `flipt-io/flipt` (Go) and `internetarchive/openlibrary` (Python).
- **Why these two.** Of the 5 SWE-bench Pro repositories we checked, these are the only two where the third-largest team still has at least 11 tasks. Both also show a clear gap between what a team's own history covers and what the three-team pool covers (table below).
  - Django in SWE-bench Verified has a similar structure, but Verified is more exposed to training-data contamination.
  - The SWE-rebench repositories we checked are not in the Harbor registry.
- **Coverage measure.** The mean share of a task's reference-fix files that earlier tasks already touched:

  | Repository | Own history | Three-team pool | Random pool, same size as own |
  |---|---|---|---|
  | flipt | 0.42 | 0.52 | 0.42 |
  | openlibrary | 0.39 | 0.58 | 0.41 |

- **Reading.** A random pool of the same size covers about as much as own history. So, on this measure, any pooling gain here comes from pool size, not from anything specific to other authors.
- **Other reasons.** Both repositories run natively in Harbor and cover two languages. SWE-bench Pro is less exposed to training-data contamination than SWE-bench Verified.

### Teams

- **Definition.** A team is one of the top 3 authors of the fix pull requests in a repository, ranked by task count. The author is the GitHub PR author.
  - Teams are labelled A to C by size. The rule above rebuilds them from public PR data.
- **Evaluation tasks.** A task is an evaluation task if its team has at least 3 of its own tasks created strictly earlier (and its reference patch is non-empty). All other tasks are history tasks.
  - Created time is the creation date of the fix PR, or the commit date when no PR is linked.
  - Tasks with the same created time do not count as earlier than each other. This is why openlibrary team C has 6 history tasks.

| Repository | Team | Tasks | History | Evaluation |
|---|---|---|---|---|
| flipt | A | 36 | 3 | 33 |
| flipt | B | 14 | 3 | 11 |
| flipt | C | 13 | 3 | 10 |
| openlibrary | A | 26 | 3 | 23 |
| openlibrary | B | 23 | 3 | 20 |
| openlibrary | C | 11 | 6 | 5 |
| **Total** | | **123** | **21** | **102** |

### Time order (prequential)

- **Run order.** The plain agent runs history tasks first, then evaluation tasks. Each group runs in order of (created time, repository, task id).
- **Memory admission.** Memory for a task comes only from tasks earlier than it. A past task's record is admitted only if that task's fix commit is an ancestor of the current task's starting commit (`git merge-base --is-ancestor`).

### Harness

- **Harbor and agent.** Harbor 0.23.0 with the `claude-code` agent, Claude Code 2.1.283.
- **RTK 0.50.0.**
  - Binary: the official `x86_64-unknown-linux-musl` release binary, sha256-checked against the release's `checksums.txt` and mounted read-only.
  - Hook: Claude Code `PreToolUse` hook `rtk hook claude` on the Bash tool. Read, Grep and Glob are not rewritten.
  - Settings: tee mode on, so the raw output of every command whose output RTK compacts, including successful ones, is archived to the trial's log directory (`tee_on_success = true`, up to 100,000 files of up to 16 MiB each). RTK telemetry is off.
  - The RTK setup is identical in every arm.
- **Snapshot hook.** A second hook records the code state (section 4) at session start, after every shell command and file edit, and at stop. It never writes to the transcript and never blocks a call.
- **Machine.** One GCP n2d-standard-32 VM runs up to 24 trials at once. Each task container gets 1 CPU and 4 GB, per the task's `task.toml`. The Docker engine is installed at VM boot; its version is not pinned.

### Solver model and provider

- **Model.** GLM-5.3-Flash (`zai-org/GLM-5.3-Flash`), served by DeepInfra in FP4 through its Anthropic-compatible endpoint (`https://api.deepinfra.com/anthropic`).
  - Every Claude Code model slot points to this one model: the main model, the Opus, Sonnet, Haiku and Fable aliases, subagents and background (small-model) calls.
  - No fallback model is set.
- **Fallback provider.** Fireworks (`accounts/fireworks/models/glm-5p3-flash`), used only if DeepInfra fails the smoke checks G1 to G3 (section 8). Switching starts a new configuration (see "Configuration identity" below).
- **Settings.** Reasoning effort high; context window 200,000 tokens; max output 32,000 tokens. Prompt caching stays on.

### Limits and isolation

- **Limits.** At most 150 turns. The agent timeout is 3,000 s and the verifier timeout is 3,000 s.
- **Tools off.** `Task` (subagents), `WebSearch` and `WebFetch` are disallowed. This is how web search is turned off, because Harbor 0.23.0 has no separate switch for it.
- **Fresh state.** Each trial gets a fresh container and a fresh Claude Code config directory, so no auto-memory or settings carry over between trials. Telemetry, error reporting, auto-update and non-essential traffic are off.
- **Run control.**
  - Each trial is its own Harbor job, with no Harbor retries and no resume.
  - A trial counts as finished only if the verifier wrote a reward. Any other trial is failed; it is reported and may be tried once more.
  - At most 2 attempts per arm and task under one configuration hash; a smoke trial gets 1. The first finished attempt counts.
  - "Attempt" here always means a retry after a failed trial. Planned repeats of a whole arm (BASE′, and the second LOCAL-STOP and POOL-STOP runs) are called independent runs.
- **Configuration identity.** A hash covers:
  - the agent settings, provider, model and pipefail setting;
  - the SELECTED header and all versions;
  - the bytes of the hook and RTK config files.

  Only trials with the current hash count. Any change gives a new hash; trials run under an older hash stop counting but are still reported.

## 4. Arms

"Trials" means paid agent trials.

| Arm | What it is | Stage | Trials |
|---|---|---|---|
| **BASE** | Claude Code + RTK, no memory. Its counted runs (the first finished attempt per task) are also the memory source for Stage 2 | 1 | 123 (21 history + 102 evaluation). The 4 smoke trials are the first 4 BASE trials |
| **SELECTED** (oracle) | BASE, with the task instruction prefixed by the list of files the reference fix changes (exact format below). An upper bound on what file selection can save, not a real selector | 1 | 102 |
| **BASE′** | A second, independent BASE run. Gives the noise floor, and the give-up threshold for the BASE run (section 5) | 1 | Up to 102: as many evaluation tasks as the fixed budget allows, in a pre-fixed random order |
| **BASE-STOP** (free stop rule) | BASE with the stop rule in section 5. **Computed offline from the recorded BASE and BASE′ runs.** The code state at each pass stop is re-checked by the verifier, with compute only and no model calls. A give-up counts as unresolved and needs no re-check | 1 | 0 |
| **LOCAL** | RTK + the team's own memory (section 6) | 2 | 102 |
| **POOL** | RTK + memory pooled over the 3 teams of the same repository | 2 | 102 |
| **LOCAL-STOP** | LOCAL + a memory-informed stop and give-up (section 6) | 2 | 204 (2 independent runs × 102) |
| **POOL-STOP** | POOL + the same stop and give-up | 2 | 204 (2 independent runs × 102) |
| **PUBLIC-STOP** | LOCAL + frozen public trajectories, same stop. Runs only if a deterministic public source is fixed before Stage 2 (**open**); otherwise the arm is dropped and the drop is logged under Deviations | 2 | 102 |
| **SIZE-STOP** | POOL-STOP with the pool subsampled to the team's own pool size (fixed random seed per task). **Conditional:** runs only if POOL-STOP is at least 5% cheaper than LOCAL-STOP. It separates pool size from cross-team content | 2, conditional | 102 |
| **DOWNSHIFT** | GLM-5.3-Flash + POOL compared with a Claude Sonnet 5 BASE reference on 50 to 60 tasks. The GLM BASE arm is the cheap control. **Optional** | 2, optional | 100 to 120 |

**Totals.**
- Stage 1: up to 327 agent trials (123 + 102 + up to 102).
- Stage 2: 714 agent trials, plus 102 if SIZE-STOP runs, plus 100 to 120 if DOWNSHIFT runs.

**Not in E0.**
- An arm without RTK.
- A placebo-memory arm.
- A repeat with teams on different repositories (cross-company). It runs as a separate follow-up only if this test shows a sharing effect.

**SELECTED prefix.** This block is placed before the original task instruction. Nothing else in the task changes.

```
The following files are relevant to this task and will likely need to be changed:
- <file 1>
- <file 2>

---

```

- The file list comes from the reference patch shipped with the Harbor task, which is the one the verifier uses.
- For 21 of the 102 evaluation tasks this list is a strict superset of the list in the newer Hugging Face release.

**Why BASE-STOP can be computed offline.**
- The stop rule only cuts a run short. Everything before the cut is identical to the recorded BASE run, token for token, so the cost of the stopped run is exactly the cost of the recorded run up to and including the stop call.
- The outcome is a different matter: the code at the cut is not the code at the end. A hook therefore records, after every shell command and file edit, the repository's diff against the task's starting commit. The diff includes new untracked files that git does not ignore. Among those it skips cache, virtual-environment and `node_modules` directories, any file over 5 MiB, and anything beyond 50 MiB in total; skipped files are logged. The patch at the stop call is applied to a clean copy of the task and graded by the same test verifier.
- Until a stop point is re-checked, it is marked pending.
- **Caveats.**
  - Only the repository diff is captured. Changes outside it (installed packages, files in other directories, a running process) are not, so grading in a fresh container can differ from what the agent had at the cut.
  - Missing usage records are covered by scaling the whole run's cost to Claude Code's final usage event (section 7). The stopped cost uses the same whole-run factor, so it is exact only up to that scaling.
  - The give-up threshold is cross-fitted by run, not by task: a task's BASE′ run helps set the threshold applied to its BASE run, and the other way round (section 5).
- What the simulation cannot see: an agent that is told to stop might act differently before the stop point (section 11).

## 5. The stop rule (BASE-STOP)

Walk through the tool calls of a recorded run in order. Stop at the first call that is either a pass or a give-up.

**1. Pass.** A test-runner call whose exit code is the runner's own and is provably 0.
- **Test-runner calls** include `go test`, `pytest`, `python -m pytest` or `unittest`, `tox`, `npm test`, `make test`, `cargo test` and similar. Listing, collect-only and help calls do not count.
- **Any test command counts**, not only the task's target tests. The re-check in section 4 decides whether the code at that point actually resolves the task.
- **"Provably 0"** means:
  - Claude Code's error flag on the result is false (Claude Code sets it on any nonzero exit);
  - the call was not interrupted and not moved to the background.
- **"The runner's own"** means nothing after the runner can change the exit code:
  - no pipe, unless pipefail is on (below);
  - no later `||`;
  - no later command after `;`, a newline or `&`;
  - not backgrounded.
- **No text parsing.** RTK's compressed output text is never parsed. Pass or fail comes only from the exit code and the error flag. RTK passes the wrapped command's exit code through.

**2. Give-up.** The call number reaches the give-up threshold.
- The run counts as unresolved, and its cost is cut at that call.
- If a call is both a pass and at the threshold, it counts as a pass.

**3. Natural end.** If neither happens, BASE-STOP equals BASE.

**Give-up threshold.** The nearest-rank 75th percentile (an observed value, never interpolated) of tool-call counts. It is cross-fitted between the two plain runs, so no run helps set its own threshold (the split is by run, not by task; section 4):
- BASE runs use the 75th percentile of BASE′ counts on evaluation tasks.
- BASE′ runs use the 75th percentile of BASE counts on evaluation tasks.
- If the other run has fewer than 20 counts, use the 75th percentile of BASE counts on the 21 history tasks.

**Piped test commands.**
- **Default: never a pass.** A pipeline's exit code is the last command's, so a piped test command never counts as a pass and is flagged.
- **Why this matters.** In a scan of 60 earlier Claude Code sessions, 94% of test commands were piped and none was a provable pass. If the solver behaves the same way, the rule reduces to give-up only.
- **Pre-registered option.** If the smoke test shows that most test calls are piped, all arms run with a single `PreToolUse` hook instead. It applies the RTK rewrite, then prefixes `set -o pipefail; ` to piped commands, so a piped test returns the runner's exit code and can count.
  - It is decided after the smoke test and before the full run.
  - It applies to every arm and starts a new configuration hash.

**Cost at the stop point.** The token usage of all model messages up to and including the one that issued the stop call. Side-chain messages count by timestamp. The same final-usage scaling as in section 7 is applied.

## 6. What each memory arm gets (Stage 2)

**Common to all memory arms** (LOCAL, POOL, LOCAL-STOP, POOL-STOP, PUBLIC-STOP, SIZE-STOP):

| Item | Rule |
|---|---|
| Source | Counted BASE runs of earlier tasks (history and evaluation tasks), captured under the same RTK setup as the arms that use them. Large tool outputs that Claude Code moves to side files are captured too. RTK recall pointers are stripped |
| Payload | Distilled, versioned experiences: one distillation call per finished task, and one renderer for all memory arms. The distillation prompt and model are **open** |
| Entry metadata | Outcome of the source run (failed runs are kept, not filtered); RTK version; the task's starting commit; hashes of the files the entry refers to |
| Admission | Prequential (section 3) |
| Leakage filter | Drop any entry that contains the current task's fix commit SHA (7 or more characters) or any line of 30 or more characters added by its reference patch, verbatim. The dropped share is reported |
| Staleness | An entry is dropped if the files it refers to have changed between its capture and the current task's starting commit (file-hash check) |
| Retrieval | BM25 keyword search, with the current task's problem statement as the query |
| Similarity gate | Nothing is injected below a similarity threshold (value **open**) |
| How many | At most the top 3 entries |
| Size limit | At most 5,000 tokens per task |
| No LLM at selection time | Retrieval, gate and ranking are deterministic. No model call decides what is injected |
| Injection | Once, as a quoted block placed before the task instruction, so the prompt prefix stays stable and cacheable. The block notes that its content may be outdated and must be verified |
| Cost of memory | Distillation, gate and injection tokens all count toward the arm's cost |

**What each arm's pool contains.**

| Arm | Pool |
|---|---|
| LOCAL, LOCAL-STOP | Entries from the task's own team only |
| POOL, POOL-STOP | Entries from all 3 teams of the same repository |
| SIZE-STOP | The POOL entries, randomly subsampled to the size of the team's own pool (fixed seed per task) |
| PUBLIC-STOP | The team's own entries, plus frozen public trajectories from a source fixed before Stage 2 (**open**) |

**Memory-informed stop** (all `-STOP` arms):
- **When it fires.** After a test-pass or edit milestone, the agent is asked for a 0 to 100 confidence that the task is done, with the top retrieved experiences in view.
- **Stop.** At 90 or above, the trial ends and the working diff goes to the verifier.
- **Give up.** When confidence is below 40 and the call count is above the 75th percentile of successful runs in the arm's pool.
- **Test-pass milestones** are detected with the exit-code rule in section 5.
- **Open.** The exact prompt and thresholds are fixed before Stage 2.
- **Who decides.** The confidence comes from the solver during the run. Choosing which memory to show stays deterministic.

**Stage 2 order.** Every memory arm runs on the same 102 evaluation tasks (the optional DOWNSHIFT comparison uses 50 to 60 of them). Arm order is randomized per task, and arms are interleaved in time so they share provider conditions.

## 7. Measurements

**Cost.**
- **Source.** Per-message token usage from Claude Code's session log, de-duplicated by message id.
- **Categories.**
  - uncached input;
  - cache read;
  - cache write (cache creation);
  - output.
- **Scaling.** When Claude Code's final usage event is present, totals are scaled to it, so calls that are missing from the session log still count.
- **Prices.** Each category is priced at the solver model's public per-token list price, fixed for the whole study. That list price was the same at four providers on 2026-10-01.
- **Only relative prices matter**, because every endpoint is a ratio. Per token, relative to uncached input = 1:
  - cache read = 0.2;
  - cache write = 0 (no cache-write charge is listed);
  - output = 10/3.
- **The bill is not the endpoint.** The provider bill is checked against our meter (smoke check G3), but every endpoint uses this fixed repricing.

**Success.**
- Graded by the benchmark's verifier in Harbor: the task's fail-to-pass tests must pass and its pass-to-pass tests must still pass. The test lists are the ones shipped with the Harbor tasks.
- A trial without a verifier reward is failed, not unresolved, and is reported separately.

**False stops.**
- A false stop is a run that BASE resolved but whose stopped version does not: either the code at a pass stop fails the re-check, or the rule gave up.
- A lucky stop (BASE unresolved, code at a pass stop resolved) is reported separately. It is not netted against false stops.
- Rate = false stops ÷ evaluation tasks with a finished BASE trial.
- The worst-case rate also counts every pass stop not yet re-checked as false, wherever BASE resolved.

**Also recorded.**
- **Per trial:** wall time, tool calls, timeouts and failed attempts.
- **Leakage flags.** Commands that could look into the future are flagged, not excluded: `git log --all` and similar, reflog, `rev-list --all`, the fix SHA. Whether the fix commit is reachable in each repository's image is logged at setup.
- **Stage 2 extras:**
  - injected tokens per task;
  - share of tasks with nothing injected;
  - dropped and stale entries;
  - stop and give-up rates.

## 8. Gates

The ID in parentheses after a gate name (S1a to S2c, B1) is the null hypothesis it tests. Each one is stated, with its evidence and status, in the summary table of [HYPOTHESES.md](HYPOTHESES.md#summary-table).

### Stage 1

| Endpoint | Comparison | Pass | Kill | Otherwise |
|---|---|---|---|---|
| **1. Free stop rule (S1a)** | BASE-STOP vs BASE, evaluation tasks, BASE runs. BASE′ runs give a secondary replicate | Savings ≥ 8% **and** worst-case false stops ≤ 3% | n/a | **Pending re-check** if savings ≥ 8%, measured false stops ≤ 3% and some stop points are not yet re-checked. Once every stop point is re-checked, the worst-case and measured rates are equal and the verdict is Pass or Fail. **Fail** in every other case |
| **2. Oracle file list (S1b)** | SELECTED vs BASE, on evaluation tasks where both finished | Savings ≥ 20%, 95% CI lower bound ≥ 10%, **and** resolve drop ≤ 3pp | Savings < 15% **or** resolve drop > 5pp. A kill removes LOCAL and POOL from Stage 2 and changes nothing else | **Inconclusive.** The result is labelled complete only when all 102 pairs exist |

**Savings** = 1 − (total cost of the arm ÷ total cost of the comparator), on the same tasks.

**Smoke checks.** Each smoke trial (up to 4) must have:
- a verifier reward and no exception;
- a session log;
- the model id equal to the configured model;
- a starting commit equal to the task's;
- at least one code snapshot.

In addition:
- **G1.** Every response reports cache-read tokens, and the cache hit rate is at least 0.80.
- **G2.** After turn 2, the median share of uncached input is below 0.5.
- **G3** (manual). The metered cost is within ±5% of the provider's usage page.
- **G4.** No 4xx or unsupported-parameter errors.
- **G5.** No mention of `api.anthropic.com` in the trial logs.

If G1 to G3 fail on DeepInfra, the run switches to Fireworks.

G1, G2, G4 and G5 are checked on every smoke trial; G3 is checked once by hand.

**Run-control stops.**
- 5 consecutive failed trials stop the run as a systemic fault.
- The budget guard and the re-plan rule are described in section 10.

### Stage 2

| Gate | Comparison | Pass | Stop |
|---|---|---|---|
| **Sharing (primary, S2b)** | POOL-STOP vs LOCAL-STOP, **and** POOL-STOP vs PUBLIC-STOP | At least 5% cheaper than both; both CIs exclude 0, corrected for 2 comparisons (correction method **open**) | Either upper bound < 5%: no sharing effect |
| Memory over a free rule (S2a) | LOCAL-STOP or POOL-STOP vs BASE-STOP | At least 5% cheaper at equal resolve | Upper bound < 5%: memory adds nothing to stopping |
| Injection memory (S2c) | POOL or LOCAL vs BASE. Runs only if SELECTED was not killed | Savings ≥ 10%, or the stricter savings ≥ 20% with 95% CI lower bound ≥ 10%; which one is **open**. Resolve drop ≤ 3pp | Point estimate < 10% |
| False stops (every STOP arm) | Stopped and failed where BASE resolved | ≤ 3% of paired tasks | > 3%: pause the arm and review before continuing |
| SIZE-STOP trigger | POOL-STOP vs LOCAL-STOP | POOL-STOP at least 5% cheaper: run SIZE-STOP | n/a |
| Downshift (optional) | GLM-5.3-Flash + POOL vs Sonnet 5 BASE | At least 30% cheaper, with resolve within a margin fixed before the arm runs (**open**) | The resolve gap is above the margin, or GLM BASE already matches (then memory gets no credit) |
| Any equal-quality claim (B1) | n/a | The cost target is met **and** the one-sided 97.5% lower bound of the resolve difference is above −3pp | Equal success on the point estimate is not enough. Such a claim needs a separate, larger run (section 11) |

How "equal resolve" in the Stage 2 table is judged, and its margin, are **open**. Stage 1 uses a 3pp bound on the point estimate.

### Primary endpoints and the pre-registered prediction

**Stage 1.** Endpoints 1 and 2 above.

**Stage 2.**
- **Primary endpoint:** the ratio of total costs, POOL-STOP vs LOCAL-STOP.
- The paired mean log ratio is also reported.
- The resolve difference is always reported alongside it.

**Prediction (null, S2b).** Pooled memory will **not** be 5% or more cheaper than the team's own memory.
- **Basis.** An offline stop-rule replay over 67,074 public recorded runs found the following, at a resolve loss of at most 1 point. The runs come from the same public trajectory dataset as the README (Qwen3-Coder-480B on OpenHands, not Claude Code).
  - Pooled vs own memory, for a give-up rule: +0.5 percentage points of spend saved (95% CI −0.7 to +1.6).
  - A pooled-memory give-up vs a no-memory give-up rule: +1.1 points (95% CI −0.1 to +2.6).
  - The memory rules in that replay predicted each run's outcome with a TF-IDF nearest-neighbour model over earlier tasks' problem statements, not with the solver's own confidence, which the Stage 2 stop arms use. The replay is a proxy, not a measurement of these arms.
- **README replay.** It puts the extra removable exploration from sharing at +3.25 points of tokens, as an upper limit.
- **Reading.** All three numbers are below the 5% gates. We therefore expect the sharing gate, and likely the memory-over-a-free-rule gate, not to pass.

## 9. Analysis

**Estimators.**
- **Ratio of totals (primary):** savings = 1 − Σ cost(arm) ÷ Σ cost(comparator), over tasks where both trials finished.
- **Paired mean log ratio:** the mean over tasks of log(cost(arm) ÷ cost(comparator)), also reported as the geometric saving 1 − exp(mean).
- **Resolve difference:** in percentage points, on the same pairs.

**Confidence intervals.**
- Method: 95% percentile bootstrap, 10,000 resamples, seed 20261001.
- Tasks are resampled with replacement within each repository (task-clustered, stratified by repository), and the same bootstrap is used for the resolve difference.
- A "CI lower bound" is the 2.5th percentile of the two-sided 95% interval.

**Noise floor.** σ = the standard deviation of the paired log cost ratio between BASE and BASE′, on evaluation tasks that have both. It is reported with every comparison and shows how much of a difference is run-to-run noise. Because BASE′ is partial, σ comes from as many tasks as the budget covered.

**Trial selection.** For each arm, independent run and task, the first finished attempt under the current configuration hash. Failed attempts are reported. How the two independent runs of LOCAL-STOP and POOL-STOP are combined in the estimators is **open** and fixed before Stage 2.

**Multiple comparisons.**
- **Stage 1:** two primary endpoints, each judged by its own gate, with no correction. Only the oracle gate uses a confidence interval; the free-stop gate uses point thresholds.
- **Stage 2:** the two comparisons inside the sharing gate are corrected for 2 comparisons (method **open**). Every other gate is judged on its own, with no correction.

We state this so readers can discount accordingly.

## 10. Spending order

The fixed budget is set before the first paid run.

1. **Smoke test.** The first 4 BASE trials: the first 2 history tasks per repository in BASE order. There are no retries, and the smoke checks in section 8 are run.
2. **Decisions after the smoke test,** before the full run:
   - the pipefail option (section 5);
   - the provider fallback, if G1 to G3 fail;
   - the **re-plan**, below.

   Any change to the configuration gives a new hash, and the smoke test is then re-run under it.
3. **Plain agent (BASE) on all 123 tasks:** history first, then evaluation, in time order. If the configuration hash has not changed, the smoke trials count here.
4. **Oracle arm (SELECTED)** on the 102 evaluation tasks.
5. **Second plain run (BASE′).** It covers as many evaluation tasks as the fixed budget allows, in a pre-fixed random order: tasks are sorted by the sha256 hex of `20261001:<task id>`. Any prefix of that order is roughly balanced between the two repositories, for example:

   | First N tasks | flipt | openlibrary |
   |---|---|---|
   | 10 | 5 | 5 |
   | 51 | 28 | 23 |
   | 102 | 54 | 48 |

6. **Offline.**
   - Simulate BASE-STOP.
   - Re-check the stop points with the verifier. This is compute only, with no model calls.
   - Analyse.

**Rolling pool.** Up to 24 trials run at once. The next group can start while the last trials of the previous group finish.

**Budget guard.** Spend counts model tokens at the provider's billed prices plus compute. Before every trial launch, the runner adds up:
- the spend so far;
- for every running trial, the larger of its live cost and a per-trial projection;
- the projection once more, for the new trial;
- a compute reserve that covers the longest possible drain of a running trial (agent plus verifier timeouts).

The projection is a fixed prior until 4 trials have finished, then the nearest-rank 90th percentile of finished trials. No new trial starts if the total reaches a halt line set below the fixed budget. A separate kill switch stops all running trials when spend plus live cost reaches a second line, just below the budget. Two backstops sit outside the runner: a spending limit on the provider key and a maximum run time on the VM.

**Re-plan after the smoke test.** The runner uses the measured cost and duration per trial to estimate how many trials the remaining budget allows:

| Verdict | When | Action |
|---|---|---|
| As planned | All of BASE and SELECTED fit | Run |
| BASE plus partial SELECTED | Only BASE fits fully | Run; SELECTED gets a partial result |
| Halt | Not even BASE fits | Stop and ask the study owner before going on |

In every verdict, BASE′ gets whatever budget is left after BASE and SELECTED (section 4).

The re-plan can stop the run, but it never admits a trial; only the budget guard does.

**Stage 2.**
- It starts only after Stage 1 is complete and analysed. Stage 1's budget does not cover it; its budget is decided before it starts.
- From Stage 1, a SELECTED kill removes LOCAL and POOL and changes nothing else. BASE-STOP is the comparator for the memory-over-a-free-rule gate.
- Open items are fixed before the first Stage 2 trial.

## 11. What this test cannot show

**Equal success within 3pp (B1).**
- Certifying that needs about 1,742 to 2,613 paired tasks. This test has 102.
- At n = 102, the CI of the resolve difference is about ±8.7 to ±10.6pp.
- Any "resolve drop ≤ 3pp" result here is a point estimate, not a test.

**Small cost effects.**
- At n = 102, the cost CI half-width is about ±5.8%, ±9.7% or ±15.5% for σ = 0.3, 0.5 or 0.8. A 10% cost effect is detectable only if σ is about 0.5 or lower.
- The predicted +0.5pp sharing effect is far below what this test can detect (B2).

**Cross-company sharing.**
- The teams share one codebase, so their memories can point at the same files.
- This is an upper bound for sharing between companies, where only generic knowledge would carry over.

**Other models.** Results come from one cheap open model (GLM-5.3-Flash, served in FP4) in one harness (Claude Code on Harbor). They may differ for frontier models.

**Breadth.**
- 2 repositories.
- One run per arm, with two exceptions: BASE is partly repeated as BASE′, and LOCAL-STOP and POOL-STOP get two independent runs each.
- σ comes from one partial replicate.
- Stage 1 arms run one after another (BASE, then SELECTED, then BASE′), not interleaved, so a change in provider behaviour during the run can show up as a difference between arms.

**A real selector or a real early stop.**
- SELECTED is an oracle upper bound.
- BASE-STOP is simulated, so it cannot show how an agent that knows it will be stopped behaves, or what the stop signal itself costs.

**Contamination.** The fix commit may be reachable inside the task image, and the solver's training cutoff is unknown. Leakage is flagged, not removed.

**Bills.** Costs are tokens weighted by fixed list prices. Actual bills depend on provider discounts and caching.

## 12. Deviations

| Date | Change | Reason |
|---|---|---|
| | | |
