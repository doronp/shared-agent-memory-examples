#!/usr/bin/env python3
"""Build data.json and the excerpt files for example 02 (streamlink__streamlink-2229).

This is a REPLAY of recorded third-party agent runs. No memory system was run. Everything here is read from the
public datasets (plus the replay outputs built from them) and written out with its provenance.

Inputs, all in $SMEM_DATA (default: ../../data):
  trajectories.parquet                       HF nebius/SWE-rebench-openhands-trajectories (raw trajectories)
  trajs.parquet, actions.parquet             extraction of the above (one row per trajectory / per tool call)
  rebench-test-0000{0,1}-of-00002.parquet    HF nebius/SWE-rebench, test split (task metadata, gold patch)
  per_task.parquet, per_task_attrib.json     output of ../../scripts/per_task_replay.py
  stale_<task>.json, stale_<task>_own.json   output of ../../scripts/staleness.py (GitHub API)
Outputs (next to this script): data.json, gold.patch, agent.patch, earlier-agent.patch,
  trajectory-excerpt.md, earlier-trajectory-excerpt.md

Usage: SMEM_DATA=path/to/data uv run --with pyarrow --with pandas python build_data.py
"""
import json, os, re
from collections import defaultdict

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.environ.get('SMEM_DATA', os.path.join(HERE, '..', '..', 'data'))
TASK = 'streamlink__streamlink-2229'
SRC = 'streamlink__streamlink-2228'
REPO = 'streamlink/streamlink'
EXPL = ('explore-read', 'explore-dir', 'explore-search', 'explore-git')
ROOT_RE = re.compile(r'/workspace/streamlink__streamlink__[0-9.]+')


def tok(x):
    return int(round(x / 4))


def load():
    fs = [f'{D}/rebench-test-00000-of-00002.parquet', f'{D}/rebench-test-00001-of-00002.parquet']
    meta = pd.concat([pd.read_parquet(f) for f in fs]).drop_duplicates('instance_id').set_index('instance_id')
    trajs = pd.read_parquet(f'{D}/trajs.parquet')
    acts = pd.read_parquet(f'{D}/actions.parquet')
    pt = pd.read_parquet(f'{D}/per_task.parquet')
    at = json.load(open(f'{D}/per_task_attrib.json'))
    return meta, trajs, acts, pt, at


def raw_trajectories(ids):
    """Full recorded trajectories (messages) for the given trajectory ids."""
    pf = pq.ParquetFile(f'{D}/trajectories.parquet')
    want, found = set(ids), {}
    for rg in range(pf.metadata.num_row_groups):
        t = pf.read_row_group(rg, columns=['trajectory_id'])
        mask = pc.is_in(t['trajectory_id'], value_set=pa.array(list(want)))
        if not pc.any(mask).as_py():
            continue
        tb = pf.read_row_group(rg, columns=['trajectory_id', 'instance_id', 'trajectory', 'model_patch', 'resolved',
                                            'exit_status']).filter(mask)
        for r in tb.to_pylist():
            found[r['trajectory_id']] = r
        if len(found) == len(want):
            break
    return found


def calls(raw):
    """(step, tool, args, observation) per tool call, in order; step = index of the LLM call (assistant message)."""
    T = raw['trajectory']
    obs = {m.get('tool_call_id'): (m.get('content') or '') for m in T if m['role'] == 'tool'}
    out, step = [], 0
    for m in T:
        if m['role'] != 'assistant':
            continue
        step += 1
        for tc in (m.get('tool_calls') or []):
            try:
                a = json.loads(tc['function'].get('arguments') or '{}')
            except Exception:
                a = {}
            out.append(dict(step=step, tool=tc['function']['name'], args=a, obs=obs.get(tc.get('id'), '')))
    return out


def describe(c):
    a = c['args']
    if c['tool'] == 'str_replace_editor':
        p = ROOT_RE.sub('<repo>', a.get('path') or '')
        vr = f" lines {a['view_range'][0]}-{a['view_range'][1]}" if a.get('view_range') else ''
        return f"{a.get('command')} {p}{vr}"
    if c['tool'] == 'execute_bash':
        cmd = ROOT_RE.sub('<repo>', a.get('command') or '')
        cmd = re.sub(r'^cd <repo> && ', '', cmd)
        first = cmd.strip().splitlines()[0] if cmd.strip() else ''
        return first[:110] + (' ...' if len(first) > 110 or '\n' in cmd.strip() else '')
    if c['tool'] == 'think':
        return '(reasoning note)'
    if c['tool'] == 'finish':
        return '(submit)'
    return c['tool']


def error_line(obs, fallback):
    """First real error line of a failed observation (sandbox path replaced), else the replay's signature."""
    for l in obs.splitlines():
        l2 = l.strip()
        if re.search(r'(ModuleNotFoundError|AssertionError|NoPluginError)|^error:', l2):
            return ROOT_RE.sub('<repo>', re.sub(r'^E\s+', '', l2))[:120]
    return fallback


def setup_detour(raw):
    """Mechanical check: an execute_bash observation contains "No module named 'streamlink'" and a LATER step runs
    `pip install -e`. Returns (step of first error, step of first later pip install -e, error recurs after it) or None."""
    err = pip = None
    recurs = False
    for c in calls(raw):
        if c['tool'] != 'execute_bash':
            continue
        cmd = c['args'].get('command') or ''
        if err is None and "No module named 'streamlink'" in c['obs']:
            err = c['step']
        elif err is not None and pip is None and re.search(r'pip\s+install\s+-e', cmd):
            pip = c['step']
        elif pip is not None and "No module named 'streamlink'" in c['obs']:
            recurs = True
    return (err, pip, recurs) if err is not None and pip is not None else None


def earlier_fix_check(base_commit, model_patch):
    """Apply the earlier run's added url_re alternative to filmon.py at the base commit (fetched with `gh`) and test
    the URL from the earlier task's hidden test test_regex_live_stream_tv_with_channel_in_name, which expects the
    groups [None, 'channel-4', None]. Returns None if `gh` is unavailable."""
    import base64, subprocess
    r = subprocess.run(['gh', 'api', f'repos/{REPO}/contents/src/streamlink/plugins/filmon.py?ref={base_commit}',
                        '--jq', '.content'], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    src = base64.b64decode(r.stdout).decode()
    pat = re.search(r'url_re = re\.compile\(r"""(.*?)"""', src, re.S).group(1)
    blk = next(b for b in re.split(r'(?m)^(?=diff --git )', model_patch) if b.startswith('diff --git a/src/streamlink/plugins/filmon.py'))
    added = [l[1:] for l in blk.splitlines() if l.startswith('+') and not l.startswith('+++') and l[1:].strip() not in ('|', '')]
    assert added == ['            tv/channel-(?!channel)'], added
    agent = pat.replace('            tv/(?!channel)\n', '            tv/channel-(?!channel)\n            |\n            tv/(?!channel)\n', 1)
    url = 'https://www.filmon.com/tv/channel-4'
    g = lambda p: (lambda m: list(m.groups()) if m else None)(re.compile(p).match(url))
    return dict(url=url, expected_groups=[None, 'channel-4', None], groups_at_base=g(pat), groups_with_earlier_patch=g(agent),
                provenance='filmon.py at base commit via GitHub contents API; expectation from the SWE-rebench test_patch')


def gh_json(path):
    import subprocess
    r = subprocess.run(['gh', 'api', path], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def upstream_check(smeta):
    """Facts from GitHub that the README relies on: issue dates (ordering caveat) and the earlier task's upstream PR
    files versus the files in its SWE-rebench patch + test_patch. Returns None if `gh` is unavailable."""
    issues = {n: gh_json(f'repos/{REPO}/issues/{n}') for n in (2221, 2222)}
    prs = {n: gh_json(f'repos/{REPO}/pulls/{n}') for n in (2228, 2229)}
    files = gh_json(f'repos/{REPO}/pulls/2228/files')
    if None in (*issues.values(), *prs.values(), files):
        return None
    same_issue_user = issues[2221]['user']['login'] == issues[2222]['user']['login']
    issues = {n: v['created_at'] for n, v in issues.items()}
    files = [f['filename'] for f in files]
    reb = sorted(set(re.findall(r'(?m)^diff --git a/(\S+)', smeta.patch + smeta.test_patch)))
    return dict(issue_created_at={'2221 (powerapp, this task)': issues[2221], '2222 (filmon, earlier task)': issues[2222]},
                pr_created_at={'2228': prs[2228]['created_at'], '2229': prs[2229]['created_at']},
                pr_titles={'2228': prs[2228]['title'], '2229': prs[2229]['title']},
                prs_opened_by_same_github_user=prs[2228]['user']['login'] == prs[2229]['user']['login'],
                issues_opened_by_same_github_user=same_issue_user,
                earlier_task_upstream_pr_files=files, earlier_task_swe_rebench_patch_files=reb,
                provenance='GitHub issues/pulls API via gh; SWE-rebench patch + test_patch for streamlink__streamlink-2228')


def main():
    meta, trajs, acts, pt, at = load()
    tid = trajs[trajs.pickP].set_index('instance_id')['trajectory_id']
    tinfo = trajs[trajs.pickP].set_index('instance_id')
    P = pt.set_index('instance_id')
    repo_tasks = P[P.repo == REPO].sort_values('idx')
    me = P.loc[TASK]
    earlier = repo_tasks[repo_tasks.idx < me.idx]
    early13 = repo_tasks.head(13)

    raws = raw_trajectories([tid[i] for i in early13.index])
    raw_by_iid = {r['instance_id']: r for r in raws.values()}

    # exploration keys per earlier task (same extraction as the replay)
    keys_by_task = {}
    for iid in earlier.index:
        x = acts[(acts.trajectory_id == tid[iid]) & acts.cat.isin(EXPL)]
        keys_by_task[iid] = set(k for ks in x['keys'] for k in ks)

    # ---- per-step table for the target task, classified exactly like per_task_replay.py
    A = acts[acts.trajectory_id == tid[TASK]].sort_values('idx')
    C = calls(raw_by_iid[TASK])
    assert len(C) == len(A), (len(C), len(A))
    steps, within = [], set()
    for a, c in zip(A.to_dict('records'), C):
        assert a['step'] == c['step']
        keys = list(a['keys'])
        row = dict(step=int(a['step']), tool=a['tool'], action=describe(c), category=a['cat'], keys=keys,
                   obs_tokens=tok(a['obs']), footprint_tokens_cache_weighted=tok(a['obs_cache'] + a['call_cache']),
                   failed=bool(a['failed']), error_signature=error_line(c['obs'], a['sig_spec']) if a['failed'] else None)
        if a['cat'] in EXPL and keys:
            first = not all(k in within for k in keys)
            within.update(keys)
            if not first:
                row['replay_class'] = 'within-task re-read (not counted)'
            else:
                own = sorted(i for i in earlier.index if P.loc[i, 'tenant'] == me.tenant and all(k in keys_by_task[i] for k in keys))
                oth = sorted(i for i in earlier.index if P.loc[i, 'tenant'] != me.tenant and all(k in keys_by_task[i] for k in keys))
                row['earlier_same_tenant'] = own
                row['earlier_other_tenants'] = oth
                row['replay_class'] = ('repeat of own history' if own else
                                       'repeat of another tenant only (cross-tenant increment)' if oth else 'new')
        else:
            row['replay_class'] = 'not exploration'
        steps.append(row)
    first_touch = [s for s in steps if s['replay_class'] not in ('not exploration', 'within-task re-read (not counted)')]
    own_rows = [s for s in first_touch if s['replay_class'] == 'repeat of own history']
    inc_rows = [s for s in first_touch if s['replay_class'].startswith('repeat of another')]
    # consistency with the replay's per-task row
    assert sum(s['footprint_tokens_cache_weighted'] for s in own_rows) == me.removable_self_tok
    assert sum(s['footprint_tokens_cache_weighted'] for s in inc_rows) == me.incr_tok
    assert len(first_touch) == me.n_first_expl and len(own_rows) == me.n_rep_self

    # tests/plugins listing content
    lst = next(c for c in C if c['tool'] == 'str_replace_editor' and (c['args'].get('path') or '').endswith('/tests/plugins'))
    entries = [l for l in lst['obs'].splitlines() if '/tests/plugins/' in l and not l.rstrip().endswith('/tests/plugins/')]
    test_files = [l for l in entries if re.search(r'/tests/plugins/test_\w+\.py$', l.strip())]

    # ---- the earlier, other-tenant task (2228)
    SA = acts[acts.trajectory_id == tid[SRC]].sort_values('idx')
    SC = calls(raw_by_iid[SRC])
    assert len(SC) == len(SA)
    src_steps = []
    for a, c in zip(SA.to_dict('records'), SC):
        src_steps.append(dict(step=int(a['step']), tool=a['tool'], action=describe(c), category=a['cat'], keys=list(a['keys']),
                              obs_tokens=tok(a['obs']), footprint_tokens_cache_weighted=tok(a['obs_cache'] + a['call_cache']),
                              failed=bool(a['failed']), error_signature=error_line(c['obs'], a['sig_spec']) if a['failed'] else None))
    src_listed = sorted(set(k[2:] for s in src_steps if s['category'] == 'explore-dir' for k in s['keys']))
    src_read = sorted(set(k[2:] for s in src_steps if s['category'] == 'explore-read' for k in s['keys']))
    src_search = sorted(set(k[2:] for s in src_steps if s['category'] == 'explore-search' for k in s['keys']))
    created = set(k[2:] for a in SA.to_dict('records') if a['verb'] == 'editor-create' for k in a['keys'])
    src_edit = sorted(set(k[2:] for s in src_steps if s['category'] == 'edit' for k in s['keys']) - created)
    src_scratch = sorted(created)
    slst = next(c for c in SC if c['tool'] == 'str_replace_editor' and (c['args'].get('path') or '').endswith('/tests/plugins'))
    s_test_files = [l for l in slst['obs'].splitlines() if re.search(r'/tests/plugins/test_\w+\.py$', l.strip())]
    s_patch = raw_by_iid[SRC]['model_patch'] or ''
    s_patch_files = []
    for blk in re.split(r'(?m)^(?=diff --git )', s_patch):
        m = re.match(r'diff --git a/(\S+) b/', blk)
        if m:
            add = sum(1 for l in blk.splitlines() if l.startswith('+') and not l.startswith('+++'))
            dele = sum(1 for l in blk.splitlines() if l.startswith('-') and not l.startswith('---'))
            s_patch_files.append(dict(path=m.group(1), added=add, removed=dele))
    sdet = setup_detour(raw_by_iid[SRC])
    srow = P.loc[SRC]
    smeta = meta.loc[SRC]

    # ---- illustrative memory note, generated mechanically from the 2228 trajectory (template + extracted fields)
    sfirst_test = next(s for s in src_steps if s['step'] == sdet[0])
    note = '\n'.join([
        f'# ILLUSTRATIVE memory note (generated from the recorded run of {SRC}, {srow.tenant}, base {smeta.base_commit[:7]})',
        f'directories listed: ' + ', '.join(p for p in src_listed if not p.startswith('EXT:')),
        f'tests/plugins listing (step {slst["step"]}): {len(s_test_files)} files named tests/plugins/test_<plugin>.py',
        f'files read: ' + ', '.join(src_read),
        f'setup: step {sdet[0]} `{sfirst_test["action"]}` failed with ModuleNotFoundError: '
        f"No module named 'streamlink'; step {sdet[1]} ran `pip install -e .`; "
        + ('the error recurs later' if sdet[2] else 'the error does not recur afterwards'),
        f'repo files edited: ' + ', '.join(src_edit),
        f'final diff: ' + ', '.join(f"{x['path']} +{x['added']}/-{x['removed']}" for x in s_patch_files),
        f'outcome: resolved={int(srow.resolved)} (the recorded run did not pass the hidden tests)',
    ])

    # ---- setup detour across the earliest 13 tasks of the repo
    detour = []
    for iid in early13.index:
        d = setup_detour(raw_by_iid[iid])
        detour.append(dict(instance_id=iid, tenant=P.loc[iid, 'tenant'], created_at=P.loc[iid, 'created_at'],
                           error_step=d[0] if d else None, pip_install_e_step=d[1] if d else None,
                           error_recurs_after=d[2] if d else None, detour=bool(d)))
    det_steps = [s for s in steps if detour[list(early13.index).index(TASK)]['error_step'] <= s['step'] <=
                 detour[list(early13.index).index(TASK)]['pip_install_e_step']]

    # ---- staleness (GitHub API, via ../../scripts/staleness.py)
    st_x = json.load(open(f'{D}/stale_{TASK}.json'))
    st_own = json.load(open(f'{D}/stale_{TASK}_own.json'))

    # ---- aggregate context for the whole replay
    T = pt.tot_tokens_cache.sum()
    agg = dict(tasks=int(len(pt)), repos=int(pt.repo.nunique()),
               own_history_share_of_all_tokens=round(pt.removable_self_tok.sum() / T, 4),
               pool_share_of_all_tokens=round(pt.removable_pool_tok.sum() / T, 4),
               share_of_tasks_with_any_increment=round(float((pt.incr_share > 0).mean()), 4),
               median_increment_share=float(pt.incr_share.median()),
               p90_increment_share=round(float(pt.incr_share.quantile(0.9)), 4),
               share_of_tasks_with_smaller_increment_than_this_one=round(float((pt.incr_share < me.incr_share).mean()), 4))

    tm = meta.loc[TASK]
    rawt = raw_by_iid[TASK]
    data = dict(
        _what='Replay of recorded third-party agent runs; no memory system was run. Overlap is measured after the fact '
              'at path/query level (a ceiling). Tokens = characters/4; not dollars.',
        _sources=dict(
            tasks='HF nebius/SWE-rebench, test split (CC BY 4.0), file rebench-test-0000{0,1}-of-00002.parquet',
            trajectories='HF nebius/SWE-rebench-openhands-trajectories (CC BY 4.0), file trajectories.parquet; '
                         'model Qwen3-Coder-480B-A35B-Instruct, OpenHands v0.54.0',
            replay='per_task.parquet / per_task_attrib.json from scripts/per_task_replay.py; trajs.parquet / '
                   'actions.parquet from the extraction step',
            staleness='GitHub contents + compare API via scripts/staleness.py',
            upstream_licence='streamlink/streamlink: BSD-2-Clause (GitHub licence API; LICENSE-streamlink.txt)'),
        definitions=dict(
            tenants='per repo, tasks sorted by created_at and dealt round-robin to tenant-1..3; a task may use only '
                    'tasks with strictly earlier created_at',
            own_history='earlier tasks of the same tenant', pool='earlier tasks of all 3 tenants',
            cross_tenant_increment='pool minus own history',
            exploration='file views/reads (path), directory listings (path), searches (exact normalized command), '
                        'git log/show/blame (command); first touch within the task only',
            obs_tokens='observation characters / 4, counted once',
            footprint_tokens_cache_weighted='(observation + the assistant message that issued it) / 4, weighted 1.0 the '
                                            'first time it is fed to the model and 0.1 on every later call; assistant '
                                            'text is also counted once as output',
            task_tokens_cache_weighted='the same weighting over every message of the trajectory'),
        task=dict(instance_id=TASK, repo=REPO, base_commit=tm.base_commit, created_at=str(P.loc[TASK, 'created_at']),
                  created_at_is='creation time of the upstream pull request',
                  pull_request=f'https://github.com/{REPO}/pull/2229', issue=f'https://github.com/{REPO}/issues/2221',
                  licence=tm.license_name, gold_files=sorted(set(re.findall(r'^diff --git a/(\S+) b/', tm.patch, re.M))),
                  gold_patch_changed_lines=int(me.patch_lines), fail_to_pass=list(tm.FAIL_TO_PASS),
                  pass_to_pass=list(tm.PASS_TO_PASS), provenance='rebench-test parquet, row instance_id=' + TASK),
        agent_run=dict(trajectory_id=tid[TASK], tenant=me.tenant, resolved=int(rawt['resolved']), exit_status=rawt['exit_status'],
                       llm_calls=int(me.n_calls), tool_calls=len(C), messages=len(rawt['trajectory']),
                       task_tokens_flat=int(me.tot_tokens_flat), task_tokens_cache_weighted=int(me.tot_tokens_cache),
                       model_patch_files=list(tinfo.loc[TASK, 'model_patch_files']),
                       provenance='trajectories.parquet row trajectory_id=' + tid[TASK] + '; totals from per_task.parquet '
                                  '(tot_tokens_flat, tot_tokens_cache, n_calls)',
                       steps=steps),
        history=dict(own=[dict(instance_id=i, tenant=P.loc[i, 'tenant'], created_at=P.loc[i, 'created_at'])
                          for i in earlier.index if P.loc[i, 'tenant'] == me.tenant],
                     pool=[dict(instance_id=i, tenant=P.loc[i, 'tenant'], created_at=P.loc[i, 'created_at'])
                           for i in earlier.index],
                     provenance='per_task.parquet own_hist / pool_hist and idx ordering'),
        replay=dict(first_touch_exploration_actions=int(me.n_first_expl),
                    repeated_from_own_history_actions=int(me.n_rep_self), repeated_from_pool_actions=int(me.n_rep_pool),
                    removable_own_history_tokens_cache_weighted=int(me.removable_self_tok),
                    removable_pool_tokens_cache_weighted=int(me.removable_pool_tok),
                    cross_tenant_increment_tokens_cache_weighted=int(me.incr_tok),
                    own_share=float(me.self_share), pool_share=float(me.pool_share), increment_share=float(me.incr_share),
                    removable_own_history_obs_tokens_flat=int(me.removable_self_obs_flat_tok),
                    removable_pool_obs_tokens_flat=int(me.removable_pool_obs_flat_tok),
                    increment_obs_tokens_flat_action=inc_rows[0]['obs_tokens'],
                    increment_actions=at[TASK]['incr_actions'], increment_sources=at[TASK]['top_src'],
                    gold_file_opened_or_edited_by_any_earlier_task=bool(me.gold_viewed_by_other_traj or me.gold_viewed_by_self_traj
                                                                        or me.gold_edited_by_other or me.gold_edited_by_self
                                                                        or me.gold_edited_by_other_traj),
                    gold_file_note='path level: no earlier run opened (file view/read) or edited the gold file and no '
                                   'earlier gold patch touched it; its file name does appear inside directory-listing '
                                   'observations of earlier runs (e.g. the src/streamlink listing of 2102 and 2160)',
                    note='flat obs increment by subtraction of rounded totals = '
                         f'{int(me.removable_pool_obs_flat_tok - me.removable_self_obs_flat_tok)}; the single action is '
                         f'{inc_rows[0]["obs_tokens"]} (rounding)',
                    provenance='per_task.parquet row ' + TASK + ' (removable_self_tok, removable_pool_tok, incr_tok, '
                               'self_share, pool_share, incr_share, removable_*_obs_flat_tok, n_first_expl, n_rep_*); '
                               'per_task_attrib.json[' + TASK + ']'),
        tests_plugins_listing=dict(step=lst['step'], entries=len(entries), test_files=len(test_files),
                                   provenance='observation of the str_replace_editor view of tests/plugins in the target trajectory'),
        earlier_task=dict(instance_id=SRC, tenant=srow.tenant, created_at=srow.created_at, base_commit=smeta.base_commit,
                          minutes_before_target=round((pd.Timestamp(me.created_at) - pd.Timestamp(srow.created_at)).total_seconds() / 60, 1),
                          pull_request=f'https://github.com/{REPO}/pull/2228', issue=f'https://github.com/{REPO}/issues/2222',
                          title=smeta.problem_statement.splitlines()[0].strip(), trajectory_id=tid[SRC],
                          resolved=int(srow.resolved), llm_calls=int(srow.n_calls),
                          task_tokens_cache_weighted=int(srow.tot_tokens_cache), task_tokens_flat=int(srow.tot_tokens_flat),
                          gold_code_files=list(srow.gold_code), fail_to_pass=list(smeta.FAIL_TO_PASS),
                          dirs_listed=src_listed, files_read=src_read, searches=src_search, files_edited=src_edit,
                          scratch_files_created=src_scratch, final_diff_files=s_patch_files,
                          tests_plugins_listing_test_files=len(s_test_files),
                          setup_detour_steps=list(sdet), steps=src_steps,
                          earlier_fix_check=earlier_fix_check(smeta.base_commit, raw_by_iid[SRC]['model_patch']),
                          illustrative_memory_note=note,
                          provenance='trajectories.parquet row trajectory_id=' + tid[SRC] + '; per_task.parquet row ' + SRC),
        setup_detour=dict(definition="an execute_bash observation contains \"No module named 'streamlink'\" and a later "
                                     "step runs `pip install -e`",
                          earliest_13_tasks=detour, count_in_13=sum(d['detour'] for d in detour),
                          count_in_target_pool=sum(d['detour'] for d in detour if d['instance_id'] in earlier.index),
                          target_pool_size=int(len(earlier)),
                          count_in_target_own_history=sum(d['detour'] for d in detour if d['instance_id'] in earlier.index
                                                          and d['tenant'] == me.tenant),
                          target_steps=[s['step'] for s in det_steps],
                          target_detour_tokens_cache_weighted=sum(s['footprint_tokens_cache_weighted'] for s in det_steps),
                          target_detour_obs_tokens_flat=sum(s['obs_tokens'] for s in det_steps),
                          note='outside the replay: runs are not exploration, so these tokens are not in the replay numbers',
                          provenance='trajectories.parquet, the 13 earliest streamlink tasks by created_at'),
        staleness=dict(cross_tenant=st_x, own_history=st_own,
                       compare_cross=f'https://github.com/{REPO}/compare/{smeta.base_commit}...{tm.base_commit}'),
        aggregate_context=dict(agg, provenance='per_task.parquet, all rows'),
        upstream=upstream_check(smeta),
    )
    # ---- extra facts used by the README caveats (added during verification)
    runs = pq.read_table(f'{D}/trajectories.parquet', columns=['instance_id', 'resolved', 'model_patch'],
                         filters=[('instance_id', 'in', [TASK, SRC])]).to_pylist()
    def run_stats(iid):
        rs = [r for r in runs if r['instance_id'] == iid]
        return dict(recorded_runs=len(rs), resolved_runs=sum(int(r['resolved'] or 0) for r in rs),
                    resolved_runs_touching_afreeca_py=sum(1 for r in rs if r['resolved'] and
                                                          'diff --git a/src/streamlink/plugins/afreeca.py' in (r['model_patch'] or '')))
    tgt_created = pd.Timestamp(P.loc[TASK, 'created_at'])
    mrepo = meta[meta.repo == REPO]
    m_created = pd.to_datetime(mrepo.created_at, utc=True, format='mixed')
    before = sorted(mrepo.index[m_created < tgt_created])
    data['extra_facts'] = dict(
        runs_per_task={TASK: run_stats(TASK), SRC: run_stats(SRC)},
        tests_plugins_listing_byte_identical=lst['obs'] == slst['obs'],
        tests_plugins_listing_chars=dict(target=len(lst['obs']), earlier=len(slst['obs'])),
        swe_rebench_repo_tasks_created_before_target=len(before),
        of_which_have_recorded_runs=sum(1 for i in before if i in P.index),
        provenance='trajectories.parquet (all runs of the two tasks); the tests/plugins observations of both picked runs; '
                   'rebench-test parquet rows for repo ' + REPO + ' with created_at earlier than the target')
    # Per earlier task: which of the target's first-touch exploration steps it had already explored (from the steps above).
    ov = defaultdict(list)
    for st in data['agent_run']['steps']:
        for iid in st.get('earlier_same_tenant', []) + st.get('earlier_other_tenants', []):
            ov[iid].append(dict(step=st['step'], action=st['action'], footprint_tokens_cache_weighted=st['footprint_tokens_cache_weighted']))
    data['overlap_by_earlier_task'] = [dict(h, pull_request=f"https://github.com/{REPO}/pull/{h['instance_id'].rsplit('-', 1)[1]}",
                                            same_tenant=h['tenant'] == me.tenant, target_steps_already_explored=ov[h['instance_id']])
                                       for h in data['history']['pool']]
    nt = tok(len(note))
    data['earlier_task']['illustrative_memory_note_tokens'] = nt
    data['earlier_task']['illustrative_memory_note_injection_estimate'] = dict(
        tokens_cache_weighted=round(nt * (1 + 0.1 * (data['agent_run']['llm_calls'] - 1))),
        formula='note tokens x (1 + 0.1 x (llm_calls - 1)): read once in full, then cached on every later call',
        status='ESTIMATE; not subtracted from any replay number')
    json.dump(data, open(os.path.join(HERE, 'data.json'), 'w'), indent=1, default=str)

    open(os.path.join(HERE, 'gold.patch'), 'w').write(tm.patch)
    open(os.path.join(HERE, 'agent.patch'), 'w').write(rawt['model_patch'])
    open(os.path.join(HERE, 'earlier-agent.patch'), 'w').write(raw_by_iid[SRC]['model_patch'])

    def table(rows, extra):
        out = ['| step | tool | action (repo root shown as `<repo>`) | obs tokens | footprint tokens (cache-weighted) | ' + extra + ' |',
               '|---:|---|---|---:|---:|---|']
        for s in rows:
            act = s['action'].replace('|', '\\|')
            if s.get('failed'):
                act += f" -> FAILED: {s['error_signature']}".replace('|', '\\|')
            ex = s.get('replay_class', s['category'])
            if s.get('earlier_same_tenant') or s.get('earlier_other_tenants'):
                ex += ' [own: ' + (', '.join(x.split('-')[-1] for x in s.get('earlier_same_tenant', [])) or '-') + \
                      '; other tenants: ' + (', '.join(x.split('-')[-1] for x in s.get('earlier_other_tenants', [])) or '-') + ']'
            out.append(f"| {s['step']} | {s['tool']} | `{act}` | {s['obs_tokens']:,} | {s['footprint_tokens_cache_weighted']:,} | {ex} |")
        return '\n'.join(out)

    hdr = ('Generated by `build_data.py` from the recorded trajectory in HF `nebius/SWE-rebench-openhands-trajectories` '
           '(CC BY 4.0; model Qwen3-Coder-480B-A35B-Instruct on OpenHands v0.54.0). Commands are shortened to their first '
           'line; observations are omitted; the sandbox path is replaced by `<repo>`. Tokens = characters / 4; they are '
           'not dollars. No memory system was run: this is a recorded run, and any overlap marked here was '
           'computed after the fact at path/query level (a ceiling).\n')
    open(os.path.join(HERE, 'trajectory-excerpt.md'), 'w').write(
        f'# Trajectory excerpt: {TASK} ({me.tenant})\n\n{hdr}\n'
        f'trajectory_id `{tid[TASK]}`, resolved = {int(rawt["resolved"])}, {int(me.n_calls)} LLM calls, '
        f'{int(me.tot_tokens_cache):,} cache-weighted tokens ({int(me.tot_tokens_flat):,} counted once).\n\n'
        '"Replay class" is how the offline replay classified each exploration action against the earlier tasks of '
        'the same repo (numbers in brackets are the earlier tasks\' PR numbers).\n\n'
        + table(steps, 'replay class') + '\n')
    open(os.path.join(HERE, 'earlier-trajectory-excerpt.md'), 'w').write(
        f'# Trajectory excerpt: {SRC} ({srow.tenant}), the earlier task\n\n{hdr}\n'
        f'trajectory_id `{tid[SRC]}`, resolved = {int(srow.resolved)}, {int(srow.n_calls)} LLM calls, '
        f'{int(srow.tot_tokens_cache):,} cache-weighted tokens ({int(srow.tot_tokens_flat):,} counted once).\n\n'
        + table(src_steps, 'category') + '\n')
    print(json.dumps(dict(replay=data['replay'], setup=data['setup_detour']['count_in_13'], note=note,
                          listing=data['tests_plugins_listing'], agg=agg), indent=1, default=str)[:6000])


if __name__ == '__main__':
    main()
