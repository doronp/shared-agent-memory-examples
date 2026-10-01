#!/usr/bin/env python3
"""Build data.json and the excerpt files for example 03 (tobymao__sqlglot-2443).

This is a REPLAY of recorded third-party agent runs. No memory system was run. Everything here is read from the
public datasets (plus the replay outputs built from them) or from the public GitHub API, and written out with its
provenance.

Inputs, all in $SMEM_DATA (default: ../../data):
  trajectories.parquet                       HF nebius/SWE-rebench-openhands-trajectories (raw trajectories)
  trajs.parquet, actions.parquet             extraction of the above (one row per trajectory / per tool call)
  rebench-test-0000{0,1}-of-00002.parquet    HF nebius/SWE-rebench, test split (task metadata, gold patch)
  per_task.parquet, per_task_attrib.json     output of ../../scripts/per_task_replay.py
  stale_tobymao__sqlglot-2443_own.json       ../../scripts/staleness.py tobymao__sqlglot-2443 tobymao__sqlglot-2412
  stale_tobymao__sqlglot-2443_own_1143.json  ../../scripts/staleness.py tobymao__sqlglot-2443 tobymao__sqlglot-1143
The freshness check of the most recent remembered copy and the file diffs between base commits call the public
GitHub API through `gh api`.

Outputs (next to this script): data.json, gold.patch, test.patch, agent.patch, trajectory-excerpt.md,
  memory-note-sqlglot-2412.md, memory-note-sqlglot-1143.md

Usage: SMEM_DATA=path/to/data uv run --with pyarrow --with pandas python build_data.py
"""
import difflib, json, os, re, subprocess, sys

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.environ.get('SMEM_DATA', os.path.join(HERE, '..', '..', 'data'))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'scripts'))
import staleness as S  # noqa: E402  (obj_id: blob/tree id of a path at a commit, via the GitHub API)

TASK = 'tobymao__sqlglot-2443'
SRCS = ['tobymao__sqlglot-2412', 'tobymao__sqlglot-1143']
REPO = 'tobymao/sqlglot'
GH = 'https://github.com/' + REPO
EXPL = ('explore-read', 'explore-dir', 'explore-search', 'explore-git')
ROOT_RE = re.compile(r'/workspace/tobymao__sqlglot__[0-9.]+')
NT = 3


def tok(x):
    return int(round(x / 4))


def gh_raw(path, ref):
    r = subprocess.run(['gh', 'api', f'repos/{REPO}/contents/{path}?ref={ref}', '-H', 'Accept: application/vnd.github.raw'],
                       capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def gold_files(patch):
    return sorted(set(re.findall(r'^diff --git a/(\S+) b/', patch or '', flags=re.M)))


def patch_pm(patch):
    a = d = 0
    for l in (patch or '').splitlines():
        if l.startswith('+') and not l.startswith('+++'):
            a += 1
        elif l.startswith('-') and not l.startswith('---'):
            d += 1
    return a, d


def load():
    fs = ['rebench-test-00000-of-00002.parquet', 'rebench-test-00001-of-00002.parquet']
    parts = []
    for f in fs:
        m = pd.read_parquet(f'{D}/{f}', columns=['instance_id', 'repo', 'created_at', 'patch', 'test_patch', 'base_commit',
                                                  'problem_statement', 'license_name', 'version', 'FAIL_TO_PASS', 'PASS_TO_PASS'])
        m['src_file'] = f
        m['src_row'] = range(len(m))
        parts.append(m)
    meta = pd.concat(parts).drop_duplicates('instance_id')
    meta['created_at'] = pd.to_datetime(meta['created_at'], utc=True, format='mixed')
    trajs = pd.read_parquet(f'{D}/trajs.parquet')
    acts = pd.read_parquet(f'{D}/actions.parquet')
    pt = pd.read_parquet(f'{D}/per_task.parquet')
    at = json.load(open(f'{D}/per_task_attrib.json'))
    return meta, trajs, acts, pt, at


def raw_trajectories(tids):
    pf = pq.ParquetFile(f'{D}/trajectories.parquet')
    found = {}
    for rg in range(pf.metadata.num_row_groups):
        t = pf.read_row_group(rg, columns=['trajectory_id'])
        mask = pc.is_in(t['trajectory_id'], value_set=pa.array(list(tids)))
        if not pc.any(mask).as_py():
            continue
        tb = pf.read_row_group(rg, columns=['trajectory_id', 'instance_id', 'trajectory', 'model_patch', 'resolved',
                                            'exit_status']).filter(mask)
        for r in tb.to_pylist():
            found[r['trajectory_id']] = r
        if len(found) == len(tids):
            break
    return found


def calls_of(traj):
    """tool calls in order, with the matching observation text (same order as actions.parquet idx)."""
    obs = {m.get('tool_call_id'): (m.get('content') or '') for m in traj if m['role'] == 'tool'}
    out = []
    for m in traj:
        if m['role'] != 'assistant':
            continue
        for tc in (m.get('tool_calls') or []):
            f = tc['function']
            try:
                a = json.loads(f.get('arguments') or '{}')
            except Exception:
                a = {}
            out.append(dict(name=f['name'], args=a if isinstance(a, dict) else {}, obs=obs.get(tc.get('id'), ''),
                            content=m.get('content') or ''))
    return out


def rel(s, root):
    s = s.replace(root + '/', '').replace(root, '.')
    s = ROOT_RE.sub('.', s)
    return s.replace('/workspace', '(sandbox root)')


def describe(c, root):
    a, n = c['args'], c['name']
    if n == 'str_replace_editor':
        vr = a.get('view_range')
        return f"{a.get('command')} {rel(a.get('path') or '', root)}" + (f" {vr}" if vr else '')
    if n == 'execute_bash':
        cmd = re.sub(r'^\s*cd\s+\S+\s*&&\s*', '', a.get('command') or '')
        cmd = re.sub(r'\s+', ' ', rel(cmd, root)).strip()
        return cmd if len(cmd) <= 110 else cmd[:107] + '...'
    if n == 'think':
        return 'think (reasoning note to itself)'
    if n == 'finish':
        return 'finish (submit)'
    return n


def main():
    meta, trajs, acts, pt, at = load()
    M = meta.set_index('instance_id')
    tp = trajs[trajs.pickP].merge(meta[['instance_id', 'created_at', 'base_commit']], on='instance_id')
    g = tp[tp.repo == REPO].sort_values(['created_at', 'instance_id']).reset_index(drop=True)
    g['tenant'] = [f'tenant-{i % NT + 1}' for i in range(len(g))]
    G = g.set_index('instance_id')
    P = pt.set_index('instance_id')
    T = G.loc[TASK]
    assert P.loc[TASK, 'tenant'] == T.tenant  # same tenant assignment as the replay
    earlier = g[g.created_at < T.created_at]
    own_e, oth_e = earlier[earlier.tenant == T.tenant], earlier[earlier.tenant != T.tenant]

    A = acts[acts.trajectory_id.isin(set(g.trajectory_id))]
    keys_by = {tid: set(k for ks in x['keys'] for k in ks) for tid, x in A[A.cat.isin(EXPL)].groupby('trajectory_id')}

    raw = raw_trajectories([T.trajectory_id] + [G.loc[s, 'trajectory_id'] for s in SRCS])
    rt = raw[T.trajectory_id]
    calls = calls_of(rt['trajectory'])
    ta = A[A.trajectory_id == T.trajectory_id].sort_values('idx').reset_index(drop=True)
    assert len(calls) == len(ta)
    root = trajs.set_index('trajectory_id').loc[T.trajectory_id, 'root']

    # ---- step table of the target trajectory -------------------------------------------------------------------
    within, steps = set(), []
    for c, a in zip(calls, ta.itertuples()):
        ks = list(a.keys)
        row = dict(step=int(a.step), tool=a.tool, category=a.cat, action=describe(c, root), keys=[rel(k, root) for k in ks],
                   obs_tokens_flat=tok(a.obs), footprint_tokens_cache_weighted=tok(a.obs_cache + a.call_cache),
                   failed=bool(a.failed))
        if a.cat in EXPL and ks:
            first = not all(k in within for k in ks)
            within.update(ks)
            row['first_touch'] = first
            if first:
                own = [r.instance_id for r in own_e.itertuples() if all(k in keys_by.get(r.trajectory_id, ()) for k in ks)]
                oth = [r.instance_id for r in oth_e.itertuples() if all(k in keys_by.get(r.trajectory_id, ()) for k in ks)]
                row.update(seen_by_own_earlier_tasks=len(own), seen_by_other_tenant_earlier_tasks=len(oth),
                           latest_own_source=own[-1] if own else None, latest_other_tenant_source=oth[-1] if oth else None,
                           covered_by_2412=all(k in keys_by[G.loc['tobymao__sqlglot-2412', 'trajectory_id']] for k in ks),
                           covered_by_1143=all(k in keys_by[G.loc['tobymao__sqlglot-1143', 'trajectory_id']] for k in ks))
        steps.append(row)
    ft = [s for s in steps if s.get('first_touch')]
    rep_own = [s for s in ft if s['seen_by_own_earlier_tasks']]
    rep_pool = [s for s in ft if s['seen_by_own_earlier_tasks'] or s['seen_by_other_tenant_earlier_tasks']]
    removable_own = sum(s['footprint_tokens_cache_weighted'] for s in rep_own)
    removable_pool = sum(s['footprint_tokens_cache_weighted'] for s in rep_pool)
    tot_cache = int(P.loc[TASK, 'tot_tokens_cache'])
    # the replay rounds once per task (sum of chars, then /4); recompute that way to match per_task.parquet exactly
    chars = lambda ss: sum(ta.loc[ta.step == s['step'], 'obs_cache'].sum() + ta.loc[ta.step == s['step'], 'call_cache'].sum() for s in ss)
    assert tok(chars(rep_own)) == P.loc[TASK, 'removable_self_tok'] and tok(chars(rep_pool)) == P.loc[TASK, 'removable_pool_tok']
    removable_own, removable_pool = tok(chars(rep_own)), tok(chars(rep_pool))
    actions_cache = tok(ta.obs_cache.sum() + ta.call_cache.sum())
    expl_first = sum(s['footprint_tokens_cache_weighted'] for s in ft)
    expl_retouch = sum(s['footprint_tokens_cache_weighted'] for s in steps if s.get('first_touch') is False)

    # README read: weight explanation
    s4 = ta[ta.step == 4].iloc[0]
    readme_weight = round(s4.obs_cache / s4.obs, 2)

    # ---- earlier tasks ---------------------------------------------------------------------------------------------
    earlier_out, notes = [], {}
    for sid in SRCS:
        r, m = G.loc[sid], M.loc[sid]
        sa = A[A.trajectory_id == r.trajectory_id].sort_values('idx')
        sraw = raw[r.trajectory_id]
        sroot = trajs.set_index('trajectory_id').loc[r.trajectory_id, 'root']
        seen, viewed, listed, searched, edited, created = set(), [], [], [], [], []
        for a in sa.itertuples():
            for k in a.keys:
                if a.cat == 'edit':
                    p = k[2:]
                    if a.verb == 'editor-create':
                        created.append(p)
                    elif p not in created and p not in edited:
                        edited.append(p)
                    continue
                if a.cat not in EXPL or k in seen:
                    continue
                seen.add(k)
                item = dict(key=rel(k, sroot), step=int(a.step), obs_tokens_flat=tok(a.obs))
                {'F': viewed, 'D': listed, 'S': searched, 'G': searched}[k[0]].append(item)
        overlap = [s for s in ft if s['covered_by_' + sid.split('-')[-1]]]
        ov_keys = set(k for s in overlap for k in s['keys'])
        a_, d_ = patch_pm(m.patch)
        mp_files = gold_files(sraw['model_patch'])
        pr = S.gh(f'repos/{REPO}/pulls/{sid.split("-")[-1]}') or {}
        fixes = re.findall(r'(?i)\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#(\d+)', pr.get('body') or '')
        e = dict(instance_id=sid, tenant=r.tenant, created_at=str(r.created_at), base_commit=r.base_commit,
                 days_before_target=round((T.created_at - r.created_at).total_seconds() / 86400, 2),
                 pull_request=f'{GH}/pull/{sid.split("-")[-1]}', pull_request_title=pr.get('title'),
                 issue=f'{GH}/issues/{fixes[0]}' if fixes else None,
                 issue_title=m.problem_statement.splitlines()[0].strip(),
                 gold_files=gold_files(m.patch), gold_lines_added=a_, gold_lines_removed=d_,
                 trajectory_id=r.trajectory_id, resolved=int(r.resolved), llm_calls=int(r.n_calls),
                 tokens_cache_weighted=tok(r.tot_cache), tokens_flat=tok(r.tot_flat),
                 agent_edited_existing_files=edited, agent_created_scratch_files=len(created),
                 model_patch_files_non_scratch=[f for f in mp_files if f not in created],
                 explored=dict(viewed=viewed, listed=listed, searched=searched),
                 overlap_with_target=dict(steps=[s['step'] for s in overlap], keys=sorted(ov_keys),
                                          tokens_cache_weighted=sum(s['footprint_tokens_cache_weighted'] for s in overlap),
                                          share_of_task=round(sum(s['footprint_tokens_cache_weighted'] for s in overlap) / tot_cache, 4),
                                          obs_tokens_flat=sum(s['obs_tokens_flat'] for s in overlap)),
                 provenance=dict(task=f"{m.src_file} row {m.src_row}", trajectory=f"trajectories.parquet / trajs.parquet / actions.parquet, trajectory_id={r.trajectory_id}",
                                 pull_request_title_and_issue='GitHub pulls API (title; issue number parsed from "Fixes #N" in the PR body); issue_title is the first line of the SWE-rebench problem_statement'))
        earlier_out.append(e)
        # illustrative memory note, mechanically from the recorded trajectory
        L = []
        L.append(f'<!-- generated by build_data.py from trajectory {r.trajectory_id}; do not edit by hand -->')
        L.append(f'# Illustrative memory note: {sid}')
        L.append('')
        L.append('> **ILLUSTRATIVE ONLY.** No memory system wrote, stored or served this note. It was generated')
        L.append('> mechanically (no LLM, no editing) by `build_data.py` from the *recorded* trajectory of')
        L.append(f'> `{sid}` in `nebius/SWE-rebench-openhands-trajectories` (CC BY 4.0) plus the task row in')
        L.append('> `nebius/SWE-rebench`. It shows what that earlier run had looked at. Paths are repo-relative.')
        L.append(f'> Entries marked `[overlap]` are ones that `{TASK}` later explored again (first touch).')
        L.append('')
        L.append('```text')
        L.append(f'repo        {REPO} @ {r.base_commit[:12]}  (task created {str(r.created_at)[:10]})')
        L.append(f'tenant      {r.tenant}')
        L.append(f'task        {sid}: "{e["issue_title"]}"')
        L.append(f'outcome     {"resolved" if r.resolved else "not resolved"} (hidden tests); {int(r.n_calls)} LLM calls')
        L.append(f'agent edit  {", ".join(edited) or "-"}  (+{len(created)} scratch files it created)')
        L.append(f'gold fix    {", ".join(e["gold_files"])}  (+{a_}/-{d_} lines, from the upstream PR)')
        for lab, items in (('listed', listed), ('read', viewed), ('searched', searched)):
            for i, it in enumerate(items):
                mark = '  [overlap]' if it['key'] in ov_keys else ''
                shown = it['key'][2:].replace('<R>', '.').replace('EXT:(sandbox root)', '(sandbox root, outside the repo)')
                if len(shown) > 90:
                    shown = shown[:87] + '...'
                L.append(f'{lab if i == 0 else "":12s}{shown}  ({it["obs_tokens_flat"]:,} tok){mark}')
        L.append('```')
        L.append('')
        L.append(f'Token sizes are the observation size the first time that run touched the path (characters/4).')
        notes[sid] = '\n'.join(L) + '\n'

    # ---- staleness ---------------------------------------------------------------------------------------------------
    stale = {}
    for sid, fn in (('tobymao__sqlglot-2412', 'stale_tobymao__sqlglot-2443_own.json'),
                    ('tobymao__sqlglot-1143', 'stale_tobymao__sqlglot-2443_own_1143.json')):
        j = json.load(open(f'{D}/{fn}'))
        src = [s for s in j['sources'] if s['instance_id'] == sid][0]
        tot = sum(p['fp_tok'] for p in src['paths'])
        fresh = sum(p['fp_tok'] for p in src['paths'] if p['same'])
        src_meta = G.loc[sid]
        diffs = {}
        for path in ('sqlglot/dialects/redshift.py', 'tests/dialects/test_redshift.py'):
            a_txt, b_txt = gh_raw(path, src_meta.base_commit), gh_raw(path, T.base_commit)
            if a_txt is None or b_txt is None:
                continue
            dl = list(difflib.unified_diff(a_txt.splitlines(), b_txt.splitlines(), lineterm='', n=0))
            add = [l for l in dl if l.startswith('+') and not l.startswith('+++')]
            rem = [l for l in dl if l.startswith('-') and not l.startswith('---')]
            diffs[path] = dict(lines_at_earlier=len(a_txt.splitlines()), lines_at_target=len(b_txt.splitlines()),
                               lines_added=len(add), lines_removed=len(rem),
                               changed_lines_mentioning_json=sum(1 for l in add + rem if 'json' in l.lower()),
                               added_lines=[l[1:].strip() for l in add] if len(add) <= 4 else None)
        stale[sid] = dict(commits_between=src['commits_between'], files_changed_between=src['files_changed_between'],
                          compare_status=src['compare_status'],
                          compare_url=f"{GH}/compare/{src['base_commit']}...{T.base_commit}",
                          paths=src['paths'], overlap_tokens=tot, overlap_tokens_note='repo paths only; the sandbox-root listing is outside the repo and not checkable', fresh_tokens=fresh, fresh_share=round(fresh / tot, 4),
                          file_diffs_between_base_commits=diffs,
                          file_diffs_method=('Python difflib.unified_diff with n=0 on the two file versions; for large rewrites its '
                                             '+/- split can differ from git diff (same net line change)'),
                          provenance=f"{fn} (scripts/staleness.py; GitHub contents + compare API); file diffs: GitHub contents API at both base commits, difflib")

    # ---- freshest remembered copy per overlapping path: own history vs pool --------------------------------------------
    fresh_rows = []
    for s in rep_pool:
        k = s['keys'][0]
        row = dict(step=s['step'], key=k, footprint_tokens_cache_weighted=s['footprint_tokens_cache_weighted'])
        for lab, sid in (('own', s['latest_own_source']), ('other_tenant', s['latest_other_tenant_source'])):
            row[f'latest_{lab}'] = sid
            if sid:
                row[f'latest_{lab}_tenant'] = G.loc[sid, 'tenant']
                row[f'latest_{lab}_created_at'] = str(G.loc[sid, 'created_at'])
                if k.startswith(('F:', 'D:')) and '(sandbox root)' not in k:
                    e_, l_ = S.obj_id(REPO, G.loc[sid, 'base_commit'], k[2:]), S.obj_id(REPO, T.base_commit, k[2:])
                    row[f'latest_{lab}_byte_identical'] = bool(e_ == l_ and e_ is not None)
                else:
                    row[f'latest_{lab}_byte_identical'] = None
        cands = [(row.get('latest_own_created_at'), 'own'), (row.get('latest_other_tenant_created_at'), 'other_tenant')]
        newest = max((c for c in cands if c[0]), key=lambda c: c[0])[1]
        row['freshest_in_pool_is'] = newest
        row['freshest_in_pool_byte_identical'] = row[f'latest_{newest}_byte_identical']
        fresh_rows.append(row)
    srcs_used = sorted({r[k] for r in fresh_rows for k in ('latest_own', 'latest_other_tenant') if r.get(k)})
    fresh_sources = {}
    for sid in srcs_used:
        j = S.gh(f'repos/{REPO}/compare/{G.loc[sid, "base_commit"]}...{T.base_commit}') or {}
        fresh_sources[sid] = dict(tenant=G.loc[sid, 'tenant'], created_at=str(G.loc[sid, 'created_at']),
                                  hours_before_target=round((T.created_at - G.loc[sid, 'created_at']).total_seconds() / 3600, 1),
                                  base_commit=G.loc[sid, 'base_commit'], commits_behind_target=j.get('total_commits'),
                                  compare_status=j.get('status'))
    own_fresh = sum(r['footprint_tokens_cache_weighted'] for r in fresh_rows if r.get('latest_own_byte_identical'))
    pool_fresh = sum(r['footprint_tokens_cache_weighted'] for r in fresh_rows if r.get('freshest_in_pool_byte_identical'))
    unknown = sum(r['footprint_tokens_cache_weighted'] for r in fresh_rows if r.get('latest_own_byte_identical') is None)

    # ---- gold-file history -----------------------------------------------------------------------------------------
    gh_hist = []
    for lab, d in (('own', at[TASK]['gold_edited_by_self']), ('other_tenant', at[TASK]['gold_edited_by_other'])):
        for f, ids in d.items():
            for sid in ids:
                gh_hist.append(dict(file=f, instance_id=sid, tenant=G.loc[sid, 'tenant'], created_at=str(G.loc[sid, 'created_at']),
                                    history=lab, trajectory_viewed_file=sid in at[TASK][f'gold_viewed_by_{"self" if lab == "own" else "other"}_traj'][f]))

    # ---- context: how typical is this task ------------------------------------------------------------------------------
    rank_self = int((pt.self_share > P.loc[TASK, 'self_share']).sum()) + 1
    w20 = pt[pt.own_hist >= 20]
    sq = pt[pt.repo == REPO]

    m = M.loc[TASK]
    ga, gd = patch_pm(m.patch)
    trow = trajs.set_index('trajectory_id').loc[T.trajectory_id]
    # files the agent created (editor create) vs untracked files that were already in the sandbox before its first action
    t_created = [k[2:] for a in ta.itertuples() if a.verb == 'editor-create' for k in a.keys]
    first_listing = next((c['obs'] for c in calls if c['name'] == 'str_replace_editor' and c['args'].get('command') == 'view'
                          and c['obs'].startswith("Here's the files and directories")), '')
    preexisting = [f for f in trow.model_patch_files if f not in t_created and f not in gold_files(m.patch)
                   and f'{root}/{f}' in first_listing.splitlines()]
    agent_src_patch = ''.join(re.findall(r'(^diff --git a/sqlglot/dialects/redshift\.py.*?)(?=^diff --git|\Z)', rt['model_patch'],
                                         flags=re.M | re.S))
    data = dict(
        _what=('Replay of recorded third-party agent runs; no memory system was run. Overlap is measured after the fact at '
               'path/query level (a ceiling). Tokens = characters/4; not dollars.'),
        _sources=dict(
            tasks='HF nebius/SWE-rebench, test split (CC BY 4.0), files rebench-test-0000{0,1}-of-00002.parquet',
            trajectories=('HF nebius/SWE-rebench-openhands-trajectories (CC BY 4.0), file trajectories.parquet; model '
                          'Qwen3-Coder-480B-A35B-Instruct, OpenHands v0.54.0'),
            replay='per_task.parquet / per_task_attrib.json from scripts/per_task_replay.py; trajs.parquet / actions.parquet from the extraction step',
            github=f'public GitHub API for {REPO} (licence MIT, Copyright (c) 2023 Toby Mao)'),
        definitions=dict(
            tenants='per repo, tasks sorted by created_at and dealt round-robin to tenant-1..3; a task may use only tasks with strictly earlier created_at',
            own_history='earlier tasks of the same tenant', pool='earlier tasks of all 3 tenants',
            cross_tenant_increment='pool minus own history',
            exploration='file views/reads (F:path), directory listings (D:path), searches (S:exact normalized command), git log/show/blame (G:command); first touch within the task only',
            repeated='every key of the action was explored by at least one task in the relevant history',
            tokens='characters / 4',
            footprint_cache_weighted=('observation + issuing call; each counts 1.0 on the first LLM call that reads it and 0.1 on '
                                      'each later LLM call that carries it in context; the issuing call is also counted once (1.0) '
                                      'as model output'),
            byte_identical='same git blob id (file) or tree id (directory) at the earlier task\'s base commit and at this task\'s base commit'),
        task=dict(instance_id=TASK, repo=REPO, tenant=T.tenant, created_at=str(T.created_at),
                  created_at_is='creation time of the upstream pull request', base_commit=T.base_commit,
                  repo_at_base_commit=f'{GH}/tree/{T.base_commit}', pull_request=f'{GH}/pull/2443', issue=f'{GH}/issues/2442',
                  version=m.version, licence=m.license_name, gold_files=gold_files(m.patch), gold_lines_added=ga, gold_lines_removed=gd,
                  fail_to_pass=list(m.FAIL_TO_PASS), pass_to_pass_count=len(m.PASS_TO_PASS),
                  issue_chars=len(m.problem_statement),
                  provenance=f'{m.src_file} row {m.src_row} (fields base_commit, created_at, patch, test_patch, problem_statement, license_name, FAIL_TO_PASS, PASS_TO_PASS)'),
        agent_run=dict(trajectory_id=T.trajectory_id, tenant=T.tenant, resolved=int(T.resolved), exit_status=rt['exit_status'],
                       llm_calls=int(trow.n_calls), tool_calls=len(calls), messages=len(rt['trajectory']),
                       task_tokens_flat=int(P.loc[TASK, 'tot_tokens_flat']), task_tokens_cache_weighted=tot_cache,
                       tool_call_footprints_cache_weighted=actions_cache,
                       prompts_cache_weighted=tot_cache - actions_cache,
                       model_patch_files=list(trow.model_patch_files),
                       agent_created_files=t_created,
                       model_patch_files_present_before_first_action=preexisting,
                       model_patch_files_note=('agent_created_files = targets of the agent\'s editor "create" calls; '
                                               'model_patch_files_present_before_first_action = untracked files already shown in the '
                                               'agent\'s first directory listing (step 2) and never created by it, so they appear in '
                                               'the submitted diff without being agent output'),
                       agent_source_change_equals_gold=agent_src_patch.strip() == m.patch.strip(),
                       exploration_first_touch_actions=len(ft), exploration_first_touch_tokens_cache_weighted=expl_first,
                       exploration_retouch_tokens_cache_weighted=expl_retouch,
                       readme_step4=dict(obs_tokens_flat=tok(s4.obs), weight=readme_weight,
                                         footprint_tokens_cache_weighted=tok(s4.obs_cache + s4.call_cache)),
                       provenance=f'trajs.parquet + actions.parquet (trajectory_id={T.trajectory_id}); per_task.parquet row {TASK} (tot_tokens_flat, tot_tokens_cache)'),
        steps=steps,
        history=dict(own_earlier_tasks=len(own_e), pool_earlier_tasks=len(earlier),
                     provenance='per_task.parquet fields own_hist, pool_hist; recomputed here from created_at'),
        replay=dict(first_touch_exploration_actions=len(ft), repeated_from_own_history_actions=len(rep_own),
                    repeated_from_pool_actions=len(rep_pool),
                    removable_own_history_tokens_cache_weighted=removable_own,
                    removable_pool_tokens_cache_weighted=removable_pool,
                    cross_tenant_increment_tokens_cache_weighted=removable_pool - removable_own,
                    own_share=round(removable_own / tot_cache, 4), pool_share=round(removable_pool / tot_cache, 4),
                    increment_share=round((removable_pool - removable_own) / tot_cache, 4),
                    removable_own_obs_tokens_flat=int(P.loc[TASK, 'removable_self_obs_flat_tok']),
                    removable_pool_obs_tokens_flat=int(P.loc[TASK, 'removable_pool_obs_flat_tok']),
                    actions_seen_by_other_tenants_but_not_own=sum(1 for s in ft if s['seen_by_other_tenant_earlier_tasks'] and not s['seen_by_own_earlier_tasks']),
                    searches_first_touch=sum(1 for s in ft if s['category'] == 'explore-search'),
                    searches_repeated_from_pool=sum(1 for s in rep_pool if s['category'] == 'explore-search'),
                    removable_own_from_2412_tokens_cache_weighted=sum(s['footprint_tokens_cache_weighted'] for s in rep_own if s['covered_by_2412']),
                    removable_own_not_from_2412_tokens_cache_weighted=sum(s['footprint_tokens_cache_weighted'] for s in rep_own if not s['covered_by_2412']),
                    provenance='per_task.parquet row tobymao__sqlglot-2443 (removable_self_tok, removable_pool_tok, incr_tok, self_share, pool_share, incr_share, removable_*_obs_flat_tok, n_first_expl, n_rep_self, n_rep_pool); per-step split recomputed here from actions.parquet and asserted equal'),
        earlier_tasks=earlier_out,
        gold_file_history=dict(entries=gh_hist, provenance='per_task_attrib.json[tobymao__sqlglot-2443] gold_edited_by_self / gold_edited_by_other / gold_viewed_by_*_traj'),
        staleness=stale,
        freshest_copy=dict(rows=fresh_rows, sources=fresh_sources, own_fresh_tokens=own_fresh, pool_fresh_tokens=pool_fresh,
                           content_level_increment_tokens=pool_fresh - own_fresh,
                           own_fresh_share=round(own_fresh / tot_cache, 4), pool_fresh_share=round(pool_fresh / tot_cache, 4),
                           content_level_increment_share=round((pool_fresh - own_fresh) / tot_cache, 4),
                           not_checkable_tokens=unknown,
                           note='for each repeated path, the most recent earlier copy in own history vs in the pool; byte_identical = same blob/tree id at that copy\'s base commit and at the target base commit; the sandbox-root listing is outside the repo and not checkable',
                           provenance='actions.parquet keys + created_at ordering; GitHub contents API (scripts/staleness.py obj_id); commits_behind_target from the GitHub compare API'),
        aggregate_context=dict(tasks=len(pt), own_share_rank_of_all_tasks=rank_self,
                               tasks_with_20plus_own=len(w20), tasks_with_20plus_own_and_zero_increment=int((w20.incr_tok == 0).sum()),
                               tasks_with_zero_increment=int((pt.incr_tok == 0).sum()),
                               sqlglot_tasks=len(sq), sqlglot_tasks_zero_increment=int((sq.incr_tok == 0).sum()),
                               sqlglot_median_own_share=round(float(sq.self_share.median()), 4),
                               sqlglot_median_increment_share=round(float(sq.incr_share.median()), 4),
                               provenance='per_task.parquet (all 1,179 rows; self_share, incr_tok, incr_share, own_hist, repo)'),
    )
    json.dump(data, open(os.path.join(HERE, 'data.json'), 'w'), indent=1, default=str)
    open(os.path.join(HERE, 'gold.patch'), 'w').write(m.patch)
    open(os.path.join(HERE, 'test.patch'), 'w').write(m.test_patch)
    open(os.path.join(HERE, 'agent.patch'), 'w').write(agent_src_patch)
    for sid, txt in notes.items():
        open(os.path.join(HERE, f'memory-note-{sid.split("__")[1]}.md'), 'w').write(txt)
    write_excerpt(steps, calls, root, T, data)
    print(json.dumps(data['replay'], indent=1))
    print(json.dumps({k: v for k, v in data['freshest_copy'].items() if k != 'rows'}, indent=1))


def clip(text, n_lines, root):
    lines = rel(text, root).splitlines()
    lines = [l for l in lines if not l.startswith(('[Current working directory', '[Python interpreter', '[Command finished'))]
    out = lines[:n_lines]
    if len(lines) > n_lines:
        out.append('[...]')
    return '\n'.join(out)


def write_excerpt(steps, calls, root, T, data):
    L = ['<!-- generated by build_data.py; do not edit by hand -->',
         f'# Trajectory excerpt: {TASK}', '',
         f'Recorded run `{T.trajectory_id}` from `nebius/SWE-rebench-openhands-trajectories` (CC BY 4.0,',
         'https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories). Model: Qwen3-Coder-480B-A35B-Instruct',
         'on OpenHands v0.54.0. **Changes made here:** absolute sandbox paths shortened to repo-relative paths; long',
         'commands and outputs truncated (marked `[...]`); whitespace in long commands collapsed in the table; OpenHands',
         '`[Current working directory ...]`, `[Python interpreter ...]` and `[Command finished ...]` status lines dropped',
         '(the `[The command completed with exit code N.]` line is kept). Nothing else was edited.', '',
         'No memory system was involved in this run. The "repeats earlier work" column is computed after the fact by the',
         'replay: the path or exact search was already explored by an earlier task of the same tenant (`own`) or of',
         'another tenant (`other`).', '',
         '## All 63 steps', '',
         '| Step | Action | Obs tokens | Footprint tokens (cache-weighted) | Exploration? | Repeats earlier work |',
         '|---:|---|---:|---:|---|---|']
    for s in steps:
        if s.get('first_touch') is None:
            ex = '-'
        elif s['first_touch']:
            ex = 'first touch'
        else:
            ex = 're-touch (same task)'
        rep = ''
        if s.get('first_touch'):
            o, x = s['seen_by_own_earlier_tasks'], s['seen_by_other_tenant_earlier_tasks']
            if o or x:
                rep = f"own: {o} task{'s' * (o != 1)} (latest {s['latest_own_source'].split('__')[1]}); other: {x}"
            else:
                rep = 'no'
        act = s['action'].replace('|', '\\|')
        L.append(f"| {s['step']} | `{act}`{' (failed)' if s['failed'] else ''} | {s['obs_tokens_flat']:,} | "
                 f"{s['footprint_tokens_cache_weighted']:,} | {ex} | {rep} |")
    L += ['', f"Totals: {data['agent_run']['task_tokens_cache_weighted']:,} cache-weighted tokens for the whole run, of which "
          f"{data['agent_run']['prompts_cache_weighted']:,} are the system and task prompts and "
          f"{data['agent_run']['tool_call_footprints_cache_weighted']:,} are the 63 steps above (column sums differ by rounding).", '']
    L += ['## Selected observations (verbatim, trimmed)', '']
    pick = {7: ('Reproduces the bug', 12), 11: ('First search: which files mention either name', 12),
            14: ('The pattern to copy: Presto already renames ParseJSON', 6), 22: ('Which dialects override ParseJSON', 12),
            33: ('The agent\'s own summary before writing a reproduction script (think tool)', 22),
            43: ('The fix (the line the edit adds)', 0), 47: ('Existing Redshift tests still pass', 16)}
    for st, (title, n) in pick.items():
        c = calls[st - 1]
        L.append(f'### Step {st}: {title}')
        L.append('')
        L.append('~~~text')
        if st == 33:
            L += [rel(l, root) for l in c['args'].get('thought', '').splitlines()[:n]] + ['[...]', '~~~', '']
            continue
        L.append('$ ' + describe(c, root))
        if st == 43:
            new = c['args'].get('new_str', '')
            old = c['args'].get('old_str', '')
            added = [l for l in new.splitlines() if l not in old.splitlines()]
            L.append('[...] new_str adds the line:')
            L += added
        else:
            L.append(clip(c['obs'], n, root))
        L.append('~~~')
        L.append('')
    open(os.path.join(HERE, 'trajectory-excerpt.md'), 'w').write('\n'.join(L))


if __name__ == '__main__':
    main()
