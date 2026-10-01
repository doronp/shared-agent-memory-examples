# Shared agent memory: worked examples

Coding agents that work for different teams on the same codebase often redo the same exploration. They open the same files, run the same searches and find the same test command. A memory shared across those teams could hand over what was already found.

This repo makes that idea concrete with worked examples taken from real, recorded agent runs.

## Status

The first three worked examples are being extracted and checked. They will appear under [`examples/`](examples/). Each one shows:

- **The problem:** the real benchmark issue, with a link to the repo at the commit where the task starts.
- **The solution:** the real gold patch.
- **What the agent did:** the key steps of its recorded run, with token counts.
- **The shared memory:** the earlier task from *another* team that already covered part of this work, and what it found.
- **The saving:** tokens removable with the team's own history vs. with the pool shared by three teams.
- **Staleness:** whether those files changed between the two tasks.

## What this is and is not

- These are **replays of public, recorded agent runs**. Overlap was measured after the fact. No live memory system was run.
- Overlap is measured at the level of file paths and search queries, so every saving here is an **upper limit**.
- Savings are in **tokens, not dollars**.

## Setup

- **Tasks:** 1,179 tasks from 18 repositories in [SWE-rebench](https://huggingface.co/datasets/nebius/SWE-rebench).
- **Runs:** one recorded run per task from [SWE-rebench OpenHands trajectories](https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories): Qwen3-Coder-480B-A35B on OpenHands v0.54.
- **Teams:** each repository's tasks are split into three simulated teams ("tenants"), assigned round-robin in time order.
- **Memory:** a team's own memory is its earlier tasks in that repository. The shared pool is every team's earlier tasks.

## Headline numbers from the replay

| Measure | Own history | Shared pool (3 teams) |
|---|---|---|
| Exploration actions that repeat an earlier file path or search | 25.8% | 32.5% |
| Removable exploration, as a share of all tokens | 14.8% | 18.1% |

- Sharing adds about **+3.2 percentage points** of total tokens on top of a team's own history.
- **Sharing matters most for teams new to a codebase.** The extra saving from sharing, as a share of a task's tokens, depends on how many earlier tasks the team has. Over the same range, the team's own memory becomes worth more.

  | Earlier tasks by the team | Extra saving from sharing | Saving from own memory (upper limit) |
  |---|---|---|
  | 0–4 | 4.5% | 8.7% |
  | 5–19 | 3.6% | 14.5% |
  | 20 or more | 1.4% | 20.6% |
- **Gold-file reuse** was measured on a separate, larger set: SWE-rebench, 116 repositories, 8,636 tasks. An earlier task had already edited at least one of the files the fix touches in 68.6% of cases within the same team, and in 84.5% across all teams.

**Plain reading:** most repeated work is a team repeating itself. Sharing helps most when a team is new to a codebase.

## Credits and licences

- SWE-rebench and the SWE-rebench OpenHands trajectories are by Nebius, under CC BY 4.0. Excerpts are quoted with attribution; see [DATA-LICENSE.md](DATA-LICENSE.md).
- Each example states the licence of its upstream repository.
- Text and code written for this repo are under the MIT licence ([LICENSE](LICENSE)).

## Questions

Questions and corrections are welcome as GitHub issues.
