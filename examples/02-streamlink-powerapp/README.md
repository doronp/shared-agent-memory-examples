# Example 2: streamlink #2229, where another team's directory listing helps (orientation, not the answer)

## What you are looking at

This is a **replay**. It is not a live product and not a live experiment. A third party, Nebius, published recorded runs of a coding agent (Qwen3-Coder-480B-A35B-Instruct on OpenHands v0.54.0) solving benchmark tasks from SWE-rebench. We took one recorded run and, after the fact, compared each exploration step (opening a file, listing a directory, running a search) with the recorded runs of *earlier* tasks on the same repository. Those earlier tasks were split between three simulated "tenants". The question is: how much of this run repeated work that an earlier run had already done? We ask it twice, once for the same tenant's history and once for a pool shared by all three tenants. No memory system was run and no agent ever saw a memory note. The overlap is matched on file paths and normalised commands, so every saving below is an **upper bound (a ceiling)**, not a measured result. Tokens are counted as characters / 4 and are not dollars.

## The problem

- Benchmark task: SWE-rebench (test split), `streamlink__streamlink-2229`
- Repository: [streamlink/streamlink at base commit 94a8a73](https://github.com/streamlink/streamlink/tree/94a8a7301c45dfdee89dd7d4d14043438dda4b38)
- Upstream fix: [PR #2229, "plugin.powerapp: support for "tvs" URLs"](https://github.com/streamlink/streamlink/pull/2229), which fixes [issue #2221](https://github.com/streamlink/streamlink/issues/2221)
- Hidden test that must flip from fail to pass: `tests/plugins/test_powerapp.py::TestPluginPowerApp::test_can_handle_url`. Test that must keep passing: `test_can_handle_url_negative`.

The issue text, as given to the agent (the benchmark's `problem_statement`, trimmed):

> **powerapp.py No plugin can handle URL**
>
> [...]
>
> ### Description
> powerapp.com.tr should be able to play the stations
>
> ### Expected / actual behavior
> Inserting the page in the streamlink does not play the stream. About my web browser Firefox I see the picture and hear the sound synonymous
>
> ### Reproduction steps / Explicit stream URLs to test
> 1.www.powerapp.com.tr/tvs/powertv/
>
> streamlink http://www.powerapp.com.tr/tvs/powertv best
>
> ### log output
> \> streamlink http://www.powerapp.com.tr/tvs/powertv best
> error: No plugin can handle URL: http://www.powerapp.com.tr/tvs/powertv
> [...]

## The real solution

The benchmark's gold patch ([gold.patch](gold.patch)):

```diff
diff --git a/src/streamlink/plugins/powerapp.py b/src/streamlink/plugins/powerapp.py
index 0ad0dda1..702505e5 100644
--- a/src/streamlink/plugins/powerapp.py
+++ b/src/streamlink/plugins/powerapp.py
@@ -7,7 +7,7 @@ from streamlink.stream import HLSStream
 
 
 class PowerApp(Plugin):
-    url_re = re.compile(r"https?://(?:www.)?powerapp.com.tr/tv/(\w+)")
+    url_re = re.compile(r"https?://(?:www.)?powerapp.com.tr/tvs?/(\w+)")
     api_url = "http://api.powergroup.com.tr/Channels/{0}/?appRef=iPowerWeb&apiVersion=11"
     api_schema = validate.Schema(validate.all({
         "errorCode": 0,
```

In one line: the plugin's URL pattern accepted only `/tv/<channel>`, and the fix makes the `s` optional so that `/tvs/<channel>` also matches. The upstream PR also adds the `/tvs/` URL to the plugin's test, and that test is the benchmark's hidden test.

The recorded agent wrote the same regex as `tv[s]?/` and added two `/tvs/` URLs to the test ([agent.patch](agent.patch)). Its run **resolved** the task: the hidden tests pass.

## What the agent did

These are the key steps of the recorded run (tenant-1). All 37 steps are in [trajectory-excerpt.md](trajectory-excerpt.md). "Tokens" is the step's cache-weighted footprint: the observation plus the assistant message that issued it, counted in full on first read and at 0.1 on every later call (prompt caching), plus the assistant output counted once.

| step | action | file / query | tokens | already done by an earlier task? |
|---:|---|---|---:|---|
| 2 | list | `/workspace` (sandbox root) | 3,018 | yes, own tenant (886, 2102) and others |
| 3 | list | repo root | 6,698 | yes, own tenant (886, 2102) and others |
| 4 | read | `README.md` | 7,644 | yes, own tenant (886, 2102) and others |
| 5 | list | `src/streamlink` (two levels deep, `powerapp.py` is visible) | 16,923 | yes, own tenant (2102) and tenant-2 (2160) |
| 6 | read | `src/streamlink/plugins/powerapp.py` | 1,581 | no |
| 7 | list | `tests/plugins` (177 entries, 174 test files) | 12,494 | **only another tenant: tenant-3 (2228)** |
| 8 | read | `tests/plugins/test_powerapp.py` | 1,073 | no |
| 9 | run | `python -m pytest tests/plugins/test_powerapp.py -v` fails: `ModuleNotFoundError: No module named 'streamlink'` | 6,669 | not exploration (setup detour, see below) |
| 10 | run | `pip install -e .` | 2,659 | not exploration (setup detour) |
| 14 | search | `grep -r "powerapp" src/` | 750 | no |
| 16 | list (glob) | `ls src/streamlink/plugins/*turk*` | 350 | no |
| 17 | read | `src/streamlink/plugins/turkuvaz.py` | 1,924 | no |
| 18 | read | `src/streamlink/plugins/dogan.py` lines 1-30 | 1,190 | no |
| 22 | edit | `src/streamlink/plugins/powerapp.py` | 1,944 | not exploration |
| 26 | edit | `tests/plugins/test_powerapp.py` | 1,280 | not exploration |
| 35 | run | re-runs the powerapp plugin tests | 2,116 | not exploration |
| 37 | finish | submit | 816 | not exploration |

Totals: 37 LLM calls; **112,421 cache-weighted tokens** (32,948 if each message is counted once); resolved = 1. The run made 11 first-touch exploration actions. Of these, 4 repeat tenant-1's own history and 5 repeat the shared pool. Steps 32-33 re-read files within the same run and are not counted.

## The shared memory

Within each repository, the replay sorts tasks by the creation time of their upstream PR and deals them round-robin to three tenants. A task may draw only on tasks created strictly before it. This task belongs to tenant-1. Its earlier tasks and the steps above that each one had already explored:

| earlier task | tenant | PR created (UTC) | relation | target steps it had already explored |
|---|---|---|---|---|
| [#886](https://github.com/streamlink/streamlink/pull/886) | tenant-1 | 2017-05-05 16:07 | own | 2, 3, 4 |
| [#1660](https://github.com/streamlink/streamlink/pull/1660) | tenant-2 | 2018-05-16 14:48 | other | 2, 3, 4 |
| [#1878](https://github.com/streamlink/streamlink/pull/1878) | tenant-3 | 2018-06-28 23:50 | other | 2, 4 |
| [#2102](https://github.com/streamlink/streamlink/pull/2102) | tenant-1 | 2018-10-07 00:44 | own | 2, 3, 4, 5 |
| [#2160](https://github.com/streamlink/streamlink/pull/2160) | tenant-2 | 2018-11-09 19:15 | other | 2, 3, 4, 5 |
| [#2228](https://github.com/streamlink/streamlink/pull/2228) | tenant-3 | 2019-01-03 12:48 | other | 2, 3, 4, **7** |

Only one step was explored by another tenant and never by tenant-1's own history: **step 7, the `tests/plugins` listing**. Its only source is `streamlink__streamlink-2228` (tenant-3, recorded run `chatcmpl-acf28a425900fef52b385c8c53172185`, full step list in [earlier-trajectory-excerpt.md](earlier-trajectory-excerpt.md)). That task's PR was opened 5.6 minutes before this one, from the same base commit. It fixes a similar bug in a different plugin ([issue #2222](https://github.com/streamlink/streamlink/issues/2222), FilmOn URLs such as `/tv/channel-4`). No earlier task ran the target's search (step 14) or its glob listing (step 16). No earlier task opened or edited the gold file `powerapp.py`, and no earlier gold patch touches it. Its file name does appear in the directory-listing output of earlier runs (for example the `src/streamlink` listings of 2102 and 2160), but nobody looked inside it. The `tests/plugins` listing that 2228's run saw is byte-identical (12,598 characters) to the one this run saw at step 7.

**The earlier run failed** (resolved = 0). Its regex change captures `4` instead of `channel-4` for `https://www.filmon.com/tv/channel-4`. We checked this by applying its added pattern to `filmon.py` at the base commit (`earlier_fix_check` in [data.json](data.json); its full patch is in [earlier-agent.patch](earlier-agent.patch)). So any memory of *its fix* would have been wrong. The only reusable part is orientation: where the plugin tests live, and what it takes to make them run.

To make this concrete, here is what a memory note from that run *could* look like:

```
# ILLUSTRATIVE memory note (generated from the recorded run of streamlink__streamlink-2228, tenant-3, base 94a8a73)
directories listed: ., src, src/streamlink/plugins, tests/plugins
tests/plugins listing (step 7): 174 files named tests/plugins/test_<plugin>.py
files read: README.md, src/streamlink/plugins/filmon.py, tests/plugins/test_filmon.py
setup: step 8 `python -m pytest tests/plugins/test_filmon.py -v` failed with ModuleNotFoundError: No module named 'streamlink'; step 9 ran `pip install -e .`; the error does not recur afterwards
repo files edited: src/streamlink/plugins/filmon.py, tests/plugins/test_filmon.py
final diff: src/streamlink/plugins/filmon.py +2/-0, test_issue_reproduction.py +49/-0, tests/plugins/test_filmon.py +22/-0
outcome: resolved=0 (the recorded run did not pass the hidden tests)
```

**This note is illustrative.** No memory system wrote it and no agent read it. [build_data.py](build_data.py) generates it mechanically from the recorded 2228 run: the directories listed, the files read and edited, the setup error and the command that followed it, the final diff, and the outcome. The note is 204 tokens.

## What it would have saved (ceiling)

| history available to the agent | exploration actions repeated (of 11) | cache-weighted tokens | share of this task's 112,421 | observation tokens, counted once |
|---|---:|---:|---:|---:|
| own tenant only (tenant-1) | 4 | 34,283 | 30.5% | 7,774 |
| pool of all 3 tenants | 5 | 46,777 | 41.6% | 10,923 |
| **cross-tenant increment (pool minus own)** | **1** | **12,494** | **11.1%** | **3,150** |

**Ceiling caveat.** These numbers assume that every repeated action could be skipped outright and that the rest of the run would be unchanged. A real memory system would have to retrieve the right note, the agent would have to trust it, and the note itself costs tokens. For example, 204 tokens injected at the start and cached for the remaining 36 calls would cost about 938 cache-weighted tokens. That figure is an estimate and is not subtracted above. Reading the listing may also have shaped later steps in ways a path match cannot see. Treat 11.1% as the most that sharing could have removed for this task, not as what it would remove.

**For context**, across the 1,179 tasks in the replay (18 repositories with 30 or more tasks each):

- The median cross-tenant increment is 1.06% of task tokens, and the 90th percentile is 10.31%.
- This task's increment is larger than that of 90.84% of tasks. It was picked as a clear example, not a typical one.
- 68.11% of tasks have any increment at all.
- Over all tokens, own history covers 14.8% and the pool covers 18.05%.

**Outside these numbers: the setup detour.** In this run, step 9's first test run fails with `No module named 'streamlink'` and step 10 runs `pip install -e .`. Together these cost 9,328 cache-weighted tokens (2,444 observation tokens). Test runs are not exploration, so the replay does not count them. The same detour shows up in:

- 12 of the 13 earliest streamlink tasks;
- all 6 earlier tasks in this task's pool;
- both of tenant-1's own earlier tasks.

So a note about it would have been available even without sharing, and it is not a cross-tenant effect.

## Staleness check

Was the shared memory still true when this task started?

- **Cross-tenant source (2228): fully fresh.** Both tasks start from the same base commit. The [compare view](https://github.com/streamlink/streamlink/compare/94a8a7301c45dfdee89dd7d4d14043438dda4b38...94a8a7301c45dfdee89dd7d4d14043438dda4b38) reports "identical", with 0 commits between them. The `tests/plugins` tree hash is `33216a3b7f` at both commits.
- **Own-history sources: mostly stale under a strict test.**
  - #2102 starts from [e29c8b7](https://github.com/streamlink/streamlink/compare/e29c8b75e664671216abc8c660f2dec21310cec9...94a8a7301c45dfdee89dd7d4d14043438dda4b38), which is 51 commits and 64 files behind. `README.md` is unchanged, but the tree hashes of the repo root and `src/streamlink` changed.
  - #886 starts from [d6a52a5](https://github.com/streamlink/streamlink/compare/d6a52a53a63ce2648781d529728f9fa9767d6522...94a8a7301c45dfdee89dd7d4d14043438dda4b38), which is 828 commits behind. The repo root and `README.md` both changed.

The test is strict: a directory counts as changed if anything below it changed, even if the listing the agent saw would look the same. "Fresh" is therefore a lower bound. `/workspace` is the benchmark's sandbox root, outside the repository, and was not checked.

## Caveats

- **Replay, not a system.** No memory system was run. All overlap is measured after the fact between recorded third-party runs.
- **Ordering.** The replay orders tasks by PR creation time, which puts 2228 5.6 minutes before 2229. The issues are in the opposite order: #2221 (this task) was filed 2018-12-31 at 11:01:28Z, about four hours before #2222 at 14:59:14Z. Under issue-date ordering, 2228 would come after this task and could not be a source, and it is the only source of the cross-tenant step here. Both issues were filed by the same reporter, and both PRs were opened by the same contributor, 5.6 minutes apart. We did not rerun the replay with that ordering, which would also reshuffle the tenants.
- **Synthetic tenants.** The three tenants are an artificial round-robin split of one repository's task history. They stand in for teams working on the same codebase.
- **One run per task.** The trajectory dataset has several runs per task. The replay uses one per task, the one with the lowest md5 of its trajectory id. A different run would explore differently. All 13 recorded runs of this task resolved; 12 of the 23 recorded runs of 2228 resolved.
- **Sparse history.** SWE-rebench has 22 streamlink tasks created before this one, but only 6 of them have recorded runs in the trajectory dataset, and the replay can only draw on those 6.
- **Noisy earlier task.** The benchmark's gold patch and test patch for 2228 touch 11 files, including an unrelated afreeca plugin test that is in its fail-to-pass list. Upstream PR #2228 touches only `filmon.py` and `test_filmon.py`. None of the 23 recorded runs of 2228 touches the afreeca plugin, yet 12 of them resolved, so the afreeca test is not what separates resolved from unresolved runs; the picked run's failure is explained by its filmon regex (above). None of this affects the `tests/plugins` overlap.
- **Approximate tokens.** Tokens are characters / 4. The 0.1 cache weight models prompt caching and is not any provider's bill.

## Files

- [data.json](data.json): every number above, with its provenance
- [gold.patch](gold.patch): the benchmark's reference fix
- [agent.patch](agent.patch): the recorded agent's fix (resolved)
- [trajectory-excerpt.md](trajectory-excerpt.md): all 37 steps of this run, with the replay class of each
- [earlier-trajectory-excerpt.md](earlier-trajectory-excerpt.md): all 47 steps of the earlier 2228 run
- [earlier-agent.patch](earlier-agent.patch): the 2228 run's patch (not resolved)
- [build_data.py](build_data.py): regenerates all of the above from the replay outputs of [../../scripts/](../../scripts/) and the public datasets: `SMEM_DATA=<data dir> uv run --with pyarrow --with pandas python build_data.py` (staleness and upstream facts use the GitHub API through `gh`)
- [LICENSE-streamlink.txt](LICENSE-streamlink.txt): streamlink's LICENSE file at base commit 94a8a73

## Attribution and licences

- The task data, including the issue text, base commit, gold patch and test lists, comes from [nebius/SWE-rebench](https://huggingface.co/datasets/nebius/SWE-rebench) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- The agent runs come from [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories) under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
- Changes we made to that data:
  - excerpted the runs;
  - shortened commands to their first line;
  - dropped the observations;
  - replaced the sandbox path with `<repo>`;
  - computed the token counts and the overlap.
- The code in the patches is from, or modifies, [streamlink](https://github.com/streamlink/streamlink), which is under the BSD 2-Clause licence. Copyright (c) 2011-2016 Christopher Rosell and (c) 2016-2018 Streamlink Team; see [LICENSE-streamlink.txt](LICENSE-streamlink.txt).
