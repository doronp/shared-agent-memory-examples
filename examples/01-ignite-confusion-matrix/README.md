# Example 1: a one-line `ConfusionMatrix` fix in pytorch/ignite (`pytorch__ignite-522`)

## What you are looking at

- **This is a replay, not a live product.** No memory system was run, and no agent was given any memory.
- We took runs that someone else had already recorded and asked a question after the fact. The runs are Qwen3-Coder-480B-A35B-Instruct working inside the OpenHands agent scaffold (v0.54.0), taken from the public dataset [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories). The question was: each time the agent opened a file, listed a directory or ran a search, had an earlier task in the same repository already opened, listed or searched exactly that?
- The tasks of each repository are sorted by date and dealt in turn to 3 simulated tenants. This task belongs to **tenant-1**. Three terms are used below:
  - **Own history**: tenant-1's own earlier tasks.
  - **Pool**: the earlier tasks of all three tenants.
  - **Cross-tenant increment**: what the pool adds on top of own history.
- A match means the same path or the same query. It does not mean the agent would have skipped the step if it had a memory. Every saving below is therefore a **ceiling**.
- Tokens are characters / 4. **Tokens are tokens, not dollars.** The default measure is cache-weighted. A message counts 1.0 the first time the model reads it and 0.1 on every later call that re-reads it as part of the context.
- This task was picked because it is easy to follow and the overlap is large. It is **not typical**: its cross-tenant increment is higher than that of 99.5% of the 1,179 replayed tasks. For the median task the increment is 1.1%.

Every number on this page is in [data.json](data.json), with the source of each one.

## The problem

- Repository: [pytorch/ignite at base commit `fc85e25`](https://github.com/pytorch/ignite/tree/fc85e25dc4f938d780b4c425acb2d40f6cac6f24) (BSD-3-Clause).
- Task: [issue #521](https://github.com/pytorch/ignite/issues/521), fixed by [PR #522](https://github.com/pytorch/ignite/pull/522). The task date used for ordering is the date the PR was opened: 2019-05-09 22:00 UTC.

The issue text exactly as the agent received it (from the SWE-rebench task record; the first line is the issue title, shown in bold here):

> **Bug in ConfusionMatrix**
>
> When passing in the groundtruth `y` with the format of `shape (batch_size, num_categories, ...) and contains ground-truth class indices`, flattened one-hot encoding tensor `y_ohe_t` will result in wrong order with respect to that of prediction. https://github.com/pytorch/ignite/blob/fc85e25dc4f938d780b4c425acb2d40f6cac6f24/ignite/metrics/confusion_matrix.py#L79-L80
>
> https://github.com/pytorch/ignite/blob/fc85e25dc4f938d780b4c425acb2d40f6cac6f24/ignite/metrics/confusion_matrix.py#L82-L83
> For example:
> ```python
> y_pred                                       # shape (B, C, H, W)
> indices = torch.argmax(y_pred, dim=1)        # shape (B, H, W)
> y_pred_ohe = to_onehot(indices.reshape(-1),  # shape (B*H*W)
>                        self.num_classes)     # shape (B*H*W, C)
>
> y                                      # shape (B, C, H, W), C: num of classes
> y_ohe_t = (y.transpose(1, -1)          # shape (B, W, H, C)
>             .reshape(y.shape[1], -1))  # reshape (B, W, H, C) into (C, B*W*H) and the value order is totally wrong
> ```
> Expected behavior:
> ```python
> y_ohe_t = y.transpose(0, 1).reshape(y.shape[1], -1)
> # (B, C, H, W) --> (C, B, H, W) --> (C, B*H*W)
> ```

The issue already names the fix, so this is an easy task. All 9 recorded runs of this task in the dataset resolved it.

How the fix is checked:
- These 3 tests must go from failing to passing: `test_multiclass_input_N`, `test_multiclass_input_NL` and `test_multiclass_input_NHW` in `tests/ignite/metrics/test_confusion_matrix.py`.
- 10 other tests must keep passing.
- The test changes made upstream are in [test.patch](test.patch).

## The real solution

The upstream fix ([gold.patch](gold.patch)):

```diff
diff --git a/ignite/metrics/confusion_matrix.py b/ignite/metrics/confusion_matrix.py
index 4325e3b8..3546796a 100644
--- a/ignite/metrics/confusion_matrix.py
+++ b/ignite/metrics/confusion_matrix.py
@@ -77,7 +77,7 @@ class ConfusionMatrix(Metric):
             y_ohe = to_onehot(y.reshape(-1), self.num_classes)
             y_ohe_t = y_ohe.transpose(0, 1).float()
         else:
-            y_ohe_t = y.transpose(1, -1).reshape(y.shape[1], -1).float()
+            y_ohe_t = y.transpose(0, 1).reshape(y.shape[1], -1).float()
 
         indices = torch.argmax(y_pred, dim=1)
         y_pred_ohe = to_onehot(indices.reshape(-1), self.num_classes)
```

In one line: swap the batch and class axes (`0, 1`) instead of the class axis and the last axis (`1, -1`), so that the flattened ground truth lines up element by element with the flattened predictions.

The recorded agent produced the same hunk, with the same `index` line. The only difference is that its diff lacks the trailing newline.

## What the agent did

The recorded run (`chatcmpl-076ccc1fb4d9bf92228216485d28f018`) was chosen as the lowest md5 of the trajectory id. It made 36 LLM calls and used 41,962 tokens counted flat (each message once), or 132,241 tokens cache-weighted. It **resolved** the task.

Key steps are below. All 36 steps are in [trajectory-excerpt.md](trajectory-excerpt.md), section 1.
- **Footprint** is the cache-weighted tokens of the tool output plus the call that issued it.
- **Seen earlier?** says whether an earlier task had explored the same path or query. It applies only to exploration steps (reads, listings, searches, git lookups), and only the first time a path is touched within the task.

| Step | Action | File / query | Footprint | Seen earlier? |
|---|---|---|---:|---|
| 2 | list directory | sandbox root (outside the repo) | 3,137 | own history (ignite-69, ignite-385) |
| 3 | list directory | `.` (repo root) | 2,813 | own history (ignite-69) |
| 4 | read file | `README.rst` | 4,873 | own history (ignite-69, ignite-385) |
| 5 | search | `find . -name "*test*" -type f \| head -10` | 1,121 | new |
| 6 | list directory | `ls tests/ignite/metrics/` | 640 | new |
| 8 | run tests | `pytest tests/ignite/metrics/test_confusion_matrix.py -v` (13 passed) | 14,510 | not counted: test run, not exploration. ignite-484 ran the same command, with the same 13 results, at its step 48 |
| 9 | list directory | `ignite/metrics` | 2,525 | **other tenant only** (ignite-484, ignite-281) |
| 10 | read file | `ignite/metrics/confusion_matrix.py` (whole file) | 9,051 | **other tenant only** (ignite-484) |
| 11 | read file | `tests/ignite/metrics/test_confusion_matrix.py` (whole file) | 17,324 | **other tenant only** (ignite-484) |
| 12 | search | `grep -n "transpose\|shape.*1.*-1" ignite/metrics/confusion_matrix.py` | 489 | new |
| 13 | search | `grep` in the test file (no match) | 469 | new |
| 15-16 | re-read | `confusion_matrix.py` lines 73-90, then 46-72 | 953 + 1,296 | re-touch within the task (not counted) |
| 18 | run | reproduction script that prints the current and the proposed reshape side by side | 1,283 | - |
| 19 | edit | `confusion_matrix.py`: `transpose(1, -1)` to `transpose(0, 1)` | 3,123 | - |
| 23 | run tests | same test file again: 13 passed | 8,860 | - |
| 28 | git | `git log --oneline -1` | 271 | new |

Totals:
- The run made **11 first-touch exploration actions**:
  - 3 had been done before in tenant-1's own history;
  - 3 more had been done only by another tenant;
  - 5 were new.
- Footprint by kind of step:

  | Kind of step | Footprint |
  |---|---:|
  | Running code and tests | 42,121 |
  | File reads | 33,497 |
  | Edits and scratch scripts | 17,481 |
  | Directory listings | 9,115 |
  | Reasoning notes | 7,994 |
  | Searches | 2,079 |
  | Git, cleanup and final message | 1,402 |
  | Fixed system prompt and task text | 18,554 |

## The shared memory

### The earlier task that matters: `pytorch__ignite-484` (tenant-3)

- **When:** 2019-04-08 23:53 UTC, 30.9 days before this task and 16 commits earlier.
- **What it was:** [issue #448](https://github.com/pytorch/ignite/issues/448), "[Metrics] add indexing synthetic sugar", fixed by [PR #484](https://github.com/pytorch/ignite/pull/484) "Metric sugar". This was a different task. It asked for indexing on `Metric` objects, and the example in that issue happens to use `ConfusionMatrix` and IoU:
  > ```
  > # A custom class ConfusionMatrix
  > cm = ConfusionMatrix(num_classes=3, output_transform=output_gt_predicted_classes_bg)
  > [...]
  > IoU = (cm.diag() / (cm.sum(dim=1) + cm.sum(dim=0) - cm.diag()))[1:]
  > mIoU = IoU.mean()
  > ```
- **Its recorded run:** resolved its own task in 62 LLM calls.
  - It edited `ignite/metrics/metric.py` (step 21), the file the upstream fix also changed.
  - Its patch also contained 10 scratch scripts that it left at the repository root.

What it explored that overlaps with this task:

| ignite-522 step | Path | ignite-484 step(s) | What ignite-484 actually saw | Same content? |
|---|---|---|---|---|
| 9 | `ignite/metrics` (listing) | 7 | the full listing | The same 15 `.py` files. ignite-522's listing has 16 extra `__pycache__` lines because it had already run the tests. |
| 10 | `ignite/metrics/confusion_matrix.py` | 11 (and lines 135-155 at step 42) | the whole file | **Identical**, 10,106 characters. |
| 11 | `tests/ignite/metrics/test_confusion_matrix.py` | 13-14 (greps, no match), 15 (lines 1-50), 16 (grep for `IoU\|MetricsLambda`), 48 (`pytest -v`) | **Only part of the file**, plus the names and results of all 13 tests | The file is byte-identical at both base commits. ignite-484 never viewed it in full. |
| (8, not counted) | `pytest ... test_confusion_matrix.py -v` | 48 | the same 13 PASSED lines | Identical except for the run time (3.54s vs 0.78s). |

ignite-484 also opened the sandbox root, `.` and `README.rst` (its steps 2-4). Those three were already in tenant-1's own history, so they do not count toward the cross-tenant increment.

The full side-by-side comparison is in [trajectory-excerpt.md](trajectory-excerpt.md), sections 3 and 4.

### Own history (tenant-1): `pytorch__ignite-69` and `pytorch__ignite-385`

- **[PR #69](https://github.com/pytorch/ignite/pull/69)**, 2018-02-09, task "Start current_epoch + current_iteration from 1 instead of 0". Its recorded run did not resolve the task. At steps 1-3 it opened the sandbox root, `.` and `README.rst`.
- **[PR #385](https://github.com/pytorch/ignite/pull/385)**, 2018-12-26, task "Improve MetricLambda implementation". Its recorded run resolved the task. It opened the sandbox root (step 2) and `README.rst` (step 4).
- Together they match steps 2-4 of this run, which is generic orientation. Neither task opened any file of the `ConfusionMatrix` code.

### A second other-tenant source: `pytorch__ignite-281` (tenant-2)

- **[PR #281](https://github.com/pytorch/ignite/pull/281)**, 2018-09-29, task "[Feature Request] More general metrics". Its recorded run did not resolve the task.
- It listed `ignite/metrics`, which ignite-484 also listed. It adds nothing beyond ignite-484. Its copy is 121 commits old, and the directory tree has changed since then.

### What a memory note from ignite-484 could look like (ILLUSTRATIVE)

> **ILLUSTRATIVE. No memory system produced this text and no agent was given it.**
>
> [scripts/build_example_01.py](../../scripts/build_example_01.py) built it mechanically from ignite-484's recorded trajectory, using fixed rules. The rules look only at ignite-484's run, never at this task:
> 1. List every file or directory inside the repository that ignite-484 opened, with its git object id at ignite-484's base commit. Scratch files it created itself are left out.
> 2. Give a class/def outline of each `.py` file among them that it viewed in full.
> 3. Give every directory listing of the repository as entry names.
> 4. For every test run that printed per-test results: the command and summary, then the test ids with results, de-duplicated across runs.
> 5. List its edits to files it did not create.
>
> The full note is [memory-note-illustrative.md](memory-note-illustrative.md), 1,937 tokens. Below is a trimmed excerpt with only the parts that bear on this task. None of the numbers on this page depend on the note.

```
Source task: pytorch__ignite-484 (issue: "[Metrics] add indexing synthetic sugar")
Source base commit: 6b8b16bac9; recorded run resolved its own task: True

| Path                                          | What it saw                 | Object id at source commit |
| ignite/metrics                                | directory listing (step 7)  | tree 3ae17e3855 |
| ignite/metrics/confusion_matrix.py            | whole file (step 11)        | blob 4325e3b869 |
| tests/ignite/metrics/test_confusion_matrix.py | lines 1-50 (step 15)        | blob e8a4f2a881 |
[...]
Outline of ignite/metrics/confusion_matrix.py (class/def lines as numbered in its step-11 view)
  10  class ConfusionMatrix(Metric):
  32      def __init__(self, num_classes, average=None, output_transform=lambda x: x):
  42      def reset(self):
  46      def _check_shape(self, output):
  73      def update(self, output):
  92      def compute(self):
 105  def IoU(cm, ignore_index=None):
[...]
Test runs with per-test outcomes
[...]
- step 48: python -m pytest tests/ignite/metrics/test_confusion_matrix.py -v; result: 13 passed in 0.78s
[...]
- tests/ignite/metrics/test_confusion_matrix.py: test_no_update PASSED, test_multiclass_wrong_inputs PASSED,
  test_multiclass_input_N PASSED, test_multiclass_input_NL PASSED, test_multiclass_input_NHW PASSED, [...]
  test_cm_with_average PASSED
```

The outline names `update()` at line 73, and the buggy line 80 is inside it. The test list has all 13 existing test names, including the 3 that the upstream test changes later make stricter. In their pre-fix form all 13 pass, both in ignite-484's run and at step 8 of this run.

## What it would have saved (a ceiling, not a measurement)

All figures are cache-weighted tokens, as a share of this task's 132,241.

| Memory available to tenant-1 | Exploration steps already done earlier | Removable tokens | Share |
|---|---:|---:|---:|
| Own history only | 3 of 11 | 10,823 | 8.2% |
| Pool of all 3 tenants | 6 of 11 | 39,723 | 30.0% |
| **Cross-tenant increment** (pool minus own) | 3 | **28,900** | **21.9%** |

- **Where the increment comes from:** 26,375 tokens of file reads (the gold file and its test file) and 2,525 tokens of a directory listing. Searches and git lookups contribute nothing. ignite-484 alone accounts for all 28,900.
- **Flat measure:** counting each tool output once, the increment is 8,074 tokens, 19.2% of the run's 41,962 flat tokens.

Why this is a ceiling, and stricter readings of it:
- **Partial views are credited as full reads.** The match is on paths. 17,324 of the 28,900 tokens are this run's full read of the test file, but ignite-484 saw only lines 1-50 of it, some grep output and the test names.
- **Gold file only.** Counting only `confusion_matrix.py` gives 9,051 tokens (6.8%). Adding the `ignite/metrics` listing gives 11,576 (8.8%).
- **The agent may read it anyway.** `confusion_matrix.py` is the file the agent had to edit, and agents usually read a file before editing it. This run re-read the relevant lines at steps 15-16 even after reading the whole file.
- **These figures are gross, not net.** Putting the illustrative note (1,937 tokens) into the context before the first call would cost about 8,715 cache-weighted tokens over 36 calls. At the path-level ceiling, that leaves 20,185 (15.3%) net.
- **This task is an outlier.** Across all 1,179 replayed tasks (18 repositories):
  - own history covers 14.80% of all tokens and the pool covers 18.05%, so the increment is 3.25 percentage points;
  - the median per-task increment is 1.1% and the 90th percentile is 10.3%;
  - 68.1% of tasks get any increment at all.

## Staleness check

Was what ignite-484 saw still true at this task's base commit? We compared the git object id of each overlapping path at the two base commits. Files use the blob id. Directories use the tree id, which is strict: any change anywhere below the directory counts as stale.

Compare view: [6b8b16b...fc85e25](https://github.com/pytorch/ignite/compare/6b8b16bac961f3d3af60befaa28ddd2f192fef16...fc85e25dc4f938d780b4c425acb2d40f6cac6f24). It contains 16 commits and 38 changed files, and the first commit is ignite-484's own fix, "Metric sugar (#484)". Under `ignite/metrics/` and `tests/ignite/metrics/`, these files changed:
- `ignite/metrics/loss.py` (+1/-1)
- `ignite/metrics/metric.py` (+4)
- `ignite/metrics/running_average.py` (+7/-3)
- `tests/ignite/metrics/test_metric.py` (+59/-2)
- `tests/ignite/metrics/test_running_average.py` (+67)

| Path | At ignite-484 base | At ignite-522 base | Fresh? |
|---|---|---|---|
| `ignite/metrics/confusion_matrix.py` | blob `4325e3b8` | blob `4325e3b8` | yes |
| `tests/ignite/metrics/test_confusion_matrix.py` | blob `e8a4f2a8` | blob `e8a4f2a8` | yes |
| `ignite/metrics` | tree `3ae17e38` | tree `ed65da02` | no, under the strict tree rule. The listed `.py` file names are the same, but three files inside changed. |

- **Fresh share of the increment:** 26,375 of 28,900 tokens (91.3%) come from paths that were byte-identical at this task's base commit. The blob ids match the `index` lines of [gold.patch](gold.patch) and [test.patch](test.patch).
- **Own history is stale.** By the same rule, none of the own-history overlap is fresh:
  - `README.rst` had a different blob at the ignite-69 base (`18da38e3`) and at the ignite-385 base (`5f0253bf`) than at this task's base (`62b95a73`);
  - the repository-root tree differs at every base;
  - the sandbox-root listing is not a git object, so its freshness is unknown.
- **The other tenant's copy was current.** ignite-484's copy of `README.rst` was byte-identical to this task's (`62b95a73`). In this case the more recent copy came from another tenant.

## Caveats

- **Replay, not a live system.** Nothing here shows that an agent given a memory would have skipped these steps, or that it would still have solved the task.
- **Matching is on path and query.** Partial views and full reads count the same, and test runs are not counted at all, even though step 8 repeated ignite-484's step 48 exactly.
- **Picked for clarity.** At the 99.5th percentile, this is not what a typical task looks like.
- **One recorded run per task, one model, one scaffold.** The dataset has 9 recorded runs of this task, and they differ from one another.
- **Rough token accounting.** Tokens are approximated as characters / 4. The 1.0 / 0.1 cache weighting is a simple model of prompt caching, not a bill. **Not dollars.**
- **Simulated tenants.** The tenants are one public repository's tasks dealt round-robin in order of PR creation time. Real tenants would work on different code, and sharing between them raises access-control questions that this replay does not address.
- **The memory note was never used.** It only shows what such a note could contain.

## Sources and licences

- **Agent runs:** [nebius/SWE-rebench-openhands-trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories), CC BY 4.0. Model: Qwen3-Coder-480B-A35B-Instruct; scaffold: OpenHands v0.54.0. Excerpts in [trajectory-excerpt.md](trajectory-excerpt.md) are trimmed (marked `[...]`; in the step tables, long commands are cut with `...` and their line breaks shown as spaces). Other changes: the sandbox directory name is replaced by repository-relative paths; pytest's `=` padding and `[NN%]` progress markers are shortened or dropped; the OpenHands command-status lines at the end of each output are dropped; trailing whitespace and emoji are removed.
  ```bibtex
  @article{trofimova2025openhandstrajs,
    title={OpenHands Trajectories with Qwen3-Coder-480B-A35B-Instruct},
    author={Trofimova, Maria and Shevtsov, Anton and Ibragim, Badertdinov and Pyaev, Konstantin and Karasik, Simon and Golubev, Alexander},
    year={2025},
    journal={Nebius blog},
    note={}
  }
  ```
- **Task records** (issue text, base commits, patches, test lists): [nebius/SWE-rebench](https://huggingface.co/datasets/nebius/SWE-rebench), test split, CC BY 4.0.
  ```bibtex
  @misc{badertdinov2025swerebenchautomatedpipelinetask,
    title={SWE-rebench: An Automated Pipeline for Task Collection and Decontaminated Evaluation of Software Engineering Agents},
    author={Ibragim Badertdinov and Alexander Golubev and Maksim Nekrashevich and Anton Shevtsov and Simon Karasik and Andrei Andriushchenko and Maria Trofimova and Daria Litvintseva and Boris Yangel},
    year={2025},
    eprint={2505.20411},
    archivePrefix={arXiv},
    primaryClass={cs.SE},
    url={https://arxiv.org/abs/2505.20411}
  }
  ```
- **Code:** [pytorch/ignite](https://github.com/pytorch/ignite), BSD-3-Clause, "Copyright (c) 2018, PyTorch team". [gold.patch](gold.patch), [test.patch](test.patch) and the quoted source lines come from it. The licence text, taken at the base commit, is in [LICENSE-ignite.txt](LICENSE-ignite.txt).
- **Regenerating the files:** [scripts/build_example_01.py](../../scripts/build_example_01.py) regenerates every file in this directory except this README. It also checks its step classification against the replay output. This README was written by hand from [data.json](data.json).
