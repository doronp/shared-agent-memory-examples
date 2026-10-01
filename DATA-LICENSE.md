# Data licences and attribution

The [LICENSE](LICENSE) file (MIT) covers only the code and prose written for this repository: the scripts, the READMEs and the computed numbers. The excerpts listed below are third-party material. They stay under their own licences and are reproduced here under those terms, with attribution and with the changes we made stated.

## Datasets (CC BY 4.0)

Both datasets are licensed under the [Creative Commons Attribution 4.0 International licence](https://creativecommons.org/licenses/by/4.0/). The licensors do not endorse this repository or its use of the data.

### nebius/SWE-rebench-openhands-trajectories

- Source: <https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories>, file `trajectories.parquet`, revision `35455389ab51bf5e2306bfd436ef72d0f98bf882`.
- Content: recorded runs of Qwen3-Coder-480B-A35B-Instruct in the OpenHands agent scaffold (v0.54.0) on SWE-rebench tasks.
- Used here in: `examples/*/trajectory-excerpt.md`, `examples/02-streamlink-powerapp/earlier-trajectory-excerpt.md`, `examples/*/agent.patch`, `examples/02-streamlink-powerapp/earlier-agent.patch`, the step lists and the command text inside `examples/*/data.json`, and the illustrative memory notes (`examples/*/memory-note-*.md` and the note in `examples/02-streamlink-powerapp/README.md`), which are generated from earlier recorded runs.
- Changes we made: selected one run per task (lowest md5 of the trajectory id); excerpted and trimmed the runs (cuts are marked `[...]`, long commands are shortened); replaced the sandbox directory with repository-relative paths; dropped the OpenHands command-status lines and shortened pytest padding and progress markers in outputs; removed trailing whitespace and emoji; classified each tool call and computed token counts and overlap; generated the illustrative memory notes mechanically from the recorded runs. Each excerpt file states its own changes. The agent patches (`examples/02-streamlink-powerapp/agent.patch`, `examples/02-streamlink-powerapp/earlier-agent.patch` and `examples/03-sqlglot-json-parse/agent.patch`) are reproduced unchanged, except that the example 03 file keeps only the hunk for `sqlglot/dialects/redshift.py`.
- Citation:

```bibtex
@article{trofimova2025openhandstrajs,
  title={OpenHands Trajectories with Qwen3-Coder-480B-A35B-Instruct},
  author={Trofimova, Maria and Shevtsov, Anton and Ibragim, Badertdinov and Pyaev, Konstantin and Karasik, Simon and Golubev, Alexander},
  year={2025},
  journal={Nebius blog},
  note={}
}
```

### nebius/SWE-rebench

- Source: <https://huggingface.co/datasets/nebius/SWE-rebench>, test split, files `data/test-00000-of-00002.parquet` and `data/test-00001-of-00002.parquet`, revision `89cdfbab4ab1bd8f5a658bb212d1b63624f4f881`.
- Used here in: the issue text quoted in each example README, `examples/*/gold.patch`, `examples/*/test.patch`, and the task metadata in `examples/*/data.json` (base commit, creation time, test lists, licence name).
- Changes we made: the issue text is quoted verbatim or trimmed (cuts marked `[...]`); the patches are unchanged.
- Each task record names the licence of its upstream repository in its `license_name` field. The issue text and patches in those records originate from the upstream repositories and issue trackers listed below.
- Citation:

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

## Upstream repositories

The gold patches, test patches, agent patches and quoted source lines contain code from, or changes to, these repositories. Each example directory carries the repository's licence text, taken at the task's base commit.

| Repository | Licence | Copyright notice | Licence text |
|---|---|---|---|
| [pytorch/ignite](https://github.com/pytorch/ignite) | BSD-3-Clause | Copyright (c) 2018, PyTorch team | [examples/01-ignite-confusion-matrix/LICENSE-ignite.txt](examples/01-ignite-confusion-matrix/LICENSE-ignite.txt) |
| [streamlink/streamlink](https://github.com/streamlink/streamlink) | BSD-2-Clause | Copyright (c) 2011-2016, Christopher Rosell; Copyright (c) 2016-2018, Streamlink Team | [examples/02-streamlink-powerapp/LICENSE-streamlink.txt](examples/02-streamlink-powerapp/LICENSE-streamlink.txt) |
| [tobymao/sqlglot](https://github.com/tobymao/sqlglot) | MIT | Copyright (c) 2023 Toby Mao | [examples/03-sqlglot-json-parse/LICENSE-sqlglot.txt](examples/03-sqlglot-json-parse/LICENSE-sqlglot.txt) |

## Model and agent scaffold

Neither is redistributed here; they are credited because they produced the recorded runs.

- Model: [Qwen/Qwen3-Coder-480B-A35B-Instruct](https://huggingface.co/Qwen/Qwen3-Coder-480B-A35B-Instruct), Apache-2.0.
- Agent scaffold: [OpenHands](https://github.com/OpenHands/OpenHands) v0.54.0, MIT.

## No endorsement, no warranty

None of the dataset, model, scaffold or repository owners has reviewed or endorsed this repository. The third-party material is provided as is, without warranty of any kind, as stated in its licences.
