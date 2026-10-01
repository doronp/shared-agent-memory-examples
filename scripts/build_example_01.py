#!/usr/bin/env python3
"""Build the machine-generated files of example 01 (pytorch__ignite-522) from the replay data.

This is a REPLAY of recorded third-party agent runs (HF nebius/SWE-rebench-openhands-trajectories). No memory system
was run. Every number written here is read from the data files listed below, or computed from them by the stated
formula. The "illustrative memory note" is built by fixed rules from the earlier trajectory; no system produced it
and no agent was given it.

Inputs (in $SMEM_DATA, default ./data):
  per_task.parquet, per_task_attrib.json        -- from scripts/per_task_replay.py
  trajs.parquet, actions.parquet                 -- extraction of HF nebius/SWE-rebench-openhands-trajectories
  rebench-test-0000{0,1}-of-00002.parquet        -- HF nebius/SWE-rebench, test split
  traj_pytorch__ignite-522.json, traj_pytorch__ignite-484.json  -- from scripts/dump_trajectory.py
Network: `gh api` (GitHub contents/compare API) for the staleness check.

Outputs (in examples/01-ignite-confusion-matrix/): data.json, gold.patch, test.patch, trajectory-excerpt.md,
memory-note-illustrative.md, LICENSE-ignite.txt (fetched from GitHub at the target base commit).
README.md in that directory is hand-written from data.json.
"""
import hashlib, json, os, re, subprocess
from datetime import datetime
import pandas as pd

D = os.environ.get('SMEM_DATA', 'data')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'examples', '01-ignite-confusion-matrix')
TASK, SRC, SRC2 = 'pytorch__ignite-522', 'pytorch__ignite-484', 'pytorch__ignite-281'
REPO = 'pytorch/ignite'
EXPL = ('explore-read', 'explore-dir', 'explore-search', 'explore-git')
EMOJI = re.compile('[\u2600-\u27bf\U0001F000-\U0001FFFF\ufe0f]')


def gh(path):
    r = subprocess.run(['gh', 'api', path], capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 else None


def obj_id(sha, path):
    """(type, full sha) of a path at a commit: blob for files, tree for directories."""
    if path in ('.', ''):
        return ('tree', gh(f'repos/{REPO}/commits/{sha}')['commit']['tree']['sha'])
    parent, _, name = path.rpartition('/')
    j = gh(f'repos/{REPO}/contents/{parent}?ref={sha}' if parent else f'repos/{REPO}/contents?ref={sha}')
    for e in (j or []):
        if e['name'] == name:
            return ('blob' if e['type'] == 'file' else 'tree', e['sha'])
    return None


def tok(chars):
    return round(chars / 4)


def load_traj(iid):
    r = json.load(open(f'{D}/traj_{iid}.json'))
    T = r['trajectory']
    obs = {m.get('tool_call_id'): (m.get('content') or '') for m in T if m['role'] == 'tool'}
    steps = []
    for m in T:
        if m['role'] != 'assistant':
            continue
        tcs = m.get('tool_calls') or []
        tc = tcs[0] if tcs else None
        args = {}
        if tc:
            try:
                args = json.loads(tc['function'].get('arguments') or '{}')
            except Exception:
                args = {}
        steps.append(dict(text=m.get('content') or '', tool=tc['function']['name'] if tc else None, args=args,
                          obs=obs.get(tc.get('id'), '') if tc else ''))
    return r, T, steps


def rel(s, root):
    return s.replace(root + '/', '').replace(root, '.')


def describe(st, root):
    a, t = st['args'], st['tool']
    if t == 'str_replace_editor':
        p = rel(a.get('path') or '', root)
        vr = a.get('view_range')
        return f"{a.get('command')} {p}" + (f" lines {vr[0]}-{vr[1]}" if vr else '')
    if t == 'execute_bash':
        c = rel(a.get('command') or '', root).replace('cd . && ', '').replace('\n', ' ')
        return c if len(c) <= 110 else c[:107] + '...'
    if t == 'think':
        return '(reasoning note, no tool output)'
    if t == 'finish':
        return '(final message)'
    return t or ''


def unpad(line):
    """pytest pads summary lines with '=' to the terminal width; keep the text only."""
    m = re.match(r'^=+ (.*?) =+$', line.strip())
    return f'=== {m.group(1)} ===' if m else line.rstrip()


def clean_obs(o, root):
    o = '\n'.join(unpad(l) for l in rel(o, root).splitlines())
    o = re.sub(r'\n\[The command completed with exit code \d+\.\]\n\[Current working directory: [^\]]*\]\n'
               r'\[Python interpreter: [^\]]*\]\n\[Command finished with exit code \d+\]\s*$', '', o)
    return EMOJI.sub('', o)


def main():
    pt = pd.read_parquet(f'{D}/per_task.parquet')
    at = json.load(open(f'{D}/per_task_attrib.json'))
    trajs = pd.read_parquet(f'{D}/trajs.parquet')
    acts = pd.read_parquet(f'{D}/actions.parquet', columns=['trajectory_id', 'idx', 'step', 'tool', 'cat', 'keys', 'obs',
                                                            'obs_cache', 'call_cache', 'failed'])
    fs = [f'{D}/rebench-test-00000-of-00002.parquet', f'{D}/rebench-test-00001-of-00002.parquet']
    meta = pd.concat([pd.read_parquet(f, columns=['instance_id', 'repo', 'created_at', 'base_commit', 'patch', 'test_patch',
                                                   'problem_statement', 'license_name', 'FAIL_TO_PASS', 'PASS_TO_PASS'])
                      for f in fs]).drop_duplicates('instance_id').set_index('instance_id')
    row = pt.set_index('instance_id').loc[TASK]
    tp = trajs[trajs.pickP].set_index('instance_id')
    tid = tp.loc[TASK, 'trajectory_id']
    root = tp.loc[TASK, 'root']

    # ---- history of this task (strictly earlier created_at in the same repo), tenants from the replay
    rp = pt[pt.repo == REPO].sort_values('idx')
    t_created = pd.Timestamp(row.created_at)
    earlier = rp[pd.to_datetime(rp.created_at) < t_created]
    own = earlier[earlier.tenant == row.tenant]
    keyset = {}
    for iid in earlier.instance_id:
        x = acts[(acts.trajectory_id == tp.loc[iid, 'trajectory_id']) & acts.cat.isin(EXPL)]
        keyset[iid] = set(k for ks in x['keys'] for k in ks)

    def first_steps(iid):
        x = acts[(acts.trajectory_id == tp.loc[iid, 'trajectory_id']) & acts.cat.isin(EXPL)].sort_values('idx')
        out = {}
        for st, ks in zip(x.step, x['keys']):
            for k in ks:
                out.setdefault(k, st)
        return out

    # ---- step table of the target run, recomputing the replay's classification
    r522, T522, S522 = load_traj(TASK)
    A = acts[acts.trajectory_id == tid].sort_values('idx')
    within, steps = set(), []
    sv_self = sv_pool = ob_self = ob_pool = 0.0
    cls_fp = {}  # unrounded footprint per replay class
    n_first = n_self = n_pool = 0
    for a in A.itertuples():
        st = S522[a.step - 1]
        keys = list(a.keys)
        fp = (a.obs_cache + a.call_cache)
        cls_fp[a.cat] = cls_fp.get(a.cat, 0.0) + fp
        status, srcs = 'not exploration (not counted)', []
        if a.cat in EXPL and keys:
            first = not all(k in within for k in keys)
            within.update(keys)
            if not first:
                status = 're-touch within this task (not counted)'
            else:
                n_first += 1
                in_self = [i for i in own.instance_id if all(k in keyset[i] for k in keys)]
                in_any = [i for i in earlier.instance_id if all(k in keyset[i] for k in keys)]
                # replay rule: an action is covered if every key is in the history (keys may come from different tasks)
                cov_self = all(any(k in keyset[i] for i in own.instance_id) for k in keys)
                cov_pool = all(any(k in keyset[i] for i in earlier.instance_id) for k in keys)
                if cov_self:
                    status, srcs = 'own history', in_self
                    sv_self += fp; ob_self += a.obs; n_self += 1
                if cov_pool:
                    sv_pool += fp; ob_pool += a.obs; n_pool += 1
                    if not cov_self:
                        status = 'other tenant only (cross-tenant increment)'
                        srcs = [i for i in in_any if i not in set(own.instance_id)]
                if not cov_pool:
                    status = 'new (no earlier task explored it)'
        steps.append(dict(step=int(a.step), tool=a.tool, replay_class=a.cat, keys=keys, action=describe(st, root),
                          obs_tok=tok(a.obs), footprint_cache_tok=tok(fp), failed=bool(a.failed), status=status,
                          earlier_tasks_with_same_key=srcs))
    # consistency with per_task.parquet (the replay)
    assert tok(sv_self) == row.removable_self_tok and tok(sv_pool) == row.removable_pool_tok, (tok(sv_self), tok(sv_pool))
    assert tok(ob_self) == row.removable_self_obs_flat_tok and tok(ob_pool) == row.removable_pool_obs_flat_tok
    assert (n_first, n_self, n_pool) == (row.n_first_expl, row.n_rep_self, row.n_rep_pool)

    # fixed prompt (system + task message) share of the cache-weighted total, same formula as the extraction step
    n_calls = int(row.n_calls)
    fixed_chars = len(T522[0].get('content') or '') + len(T522[1].get('content') or '')
    fixed_cache_tok = tok(fixed_chars * (1 + 0.1 * (n_calls - 1)))

    # ---- earlier run (tenant-3) step list and observations
    r484, T484, S484 = load_traj(SRC)
    root484 = tp.loc[SRC, 'root']
    A484 = acts[acts.trajectory_id == tp.loc[SRC, 'trajectory_id']].sort_values('idx')
    incr_keys = set(k for x in at[TASK]['incr_actions'] for k in x['keys'])
    steps484 = []
    for a in A484.itertuples():
        st = S484[a.step - 1]
        steps484.append(dict(step=int(a.step), tool=a.tool, replay_class=a.cat, keys=list(a.keys),
                             action=describe(st, root484), obs_tok=tok(a.obs),
                             key_in_target_increment=any(k in incr_keys for k in a.keys)))

    # ---- content-level comparison of overlapping observations (sandbox directory name stripped)
    def find(steps_, pred):
        return [i for i, s in enumerate(steps_) if pred(s)]
    cmp_ = []
    pairs = [('ignite/metrics/confusion_matrix.py (full view)',
              lambda s: s['tool'] == 'str_replace_editor' and (s['args'].get('path') or '').endswith('ignite/metrics/confusion_matrix.py') and not s['args'].get('view_range')),
             ('ignite/metrics (directory view)',
              lambda s: s['tool'] == 'str_replace_editor' and (s['args'].get('path') or '').endswith('/ignite/metrics')),
             ('README.rst (full view)',
              lambda s: s['tool'] == 'str_replace_editor' and (s['args'].get('path') or '').endswith('README.rst')),
             ('pytest tests/ignite/metrics/test_confusion_matrix.py -v (test run, not exploration)',
              lambda s: s['tool'] == 'execute_bash' and (s['args'].get('command') or '').endswith('pytest tests/ignite/metrics/test_confusion_matrix.py -v'))]
    for name, pred in pairs:
        i, j = find(S522, pred)[0], find(S484, pred)[0]
        a_, b_ = rel(S522[i]['obs'], root), rel(S484[j]['obs'], root484)
        la, lb = a_.splitlines(), b_.splitlines()
        la, lb = [unpad(l) for l in la], [unpad(l) for l in lb]
        only_a = [l for l in la if l not in set(lb)]
        only_b = [l for l in lb if l not in set(la)]
        cmp_.append(dict(what=name, target_step=i + 1, earlier_step=j + 1, target_chars=len(S522[i]['obs']),
                         earlier_chars=len(S484[j]['obs']), identical=a_ == b_,
                         lines_only_in_target=len(only_a), lines_only_in_earlier=len(only_b),
                         sample_lines_only_in_target=[l[:120] for l in only_a[:3]],
                         sample_lines_only_in_earlier=[l[:120] for l in only_b[:3]]))
    # what the earlier run saw of the test file
    tv = [s for s in steps484 if 'F:tests/ignite/metrics/test_confusion_matrix.py' in s['keys'] or
          ('test_confusion_matrix.py' in s['action'] and s['replay_class'] == 'explore-search')]

    # ---- staleness via GitHub API
    m_t, m_s, m_s2 = meta.loc[TASK], meta.loc[SRC], meta.loc[SRC2]
    paths = ['ignite/metrics/confusion_matrix.py', 'tests/ignite/metrics/test_confusion_matrix.py', 'ignite/metrics',
             'README.rst', '.', 'ignite/metrics/metric.py', 'ignite/metrics/metrics_lambda.py',
             'tests/ignite/metrics/test_metrics_lambda.py']
    commits = {'target': m_t.base_commit, SRC: m_s.base_commit, SRC2: m_s2.base_commit}
    for iid in own.instance_id:
        commits[iid] = meta.loc[iid, 'base_commit']
    ids = {}
    for label, sha in commits.items():
        ids[label] = {p: obj_id(sha, p) for p in paths}
    cmpj = gh(f'repos/{REPO}/compare/{m_s.base_commit}...{m_t.base_commit}')
    cmpj2 = gh(f'repos/{REPO}/compare/{m_s2.base_commit}...{m_t.base_commit}')
    changed_metrics = [dict(file=f['filename'], status=f['status'], additions=f['additions'], deletions=f['deletions'])
                       for f in cmpj['files'] if f['filename'].startswith(('ignite/metrics/', 'tests/ignite/metrics/'))]

    incr = {x['keys'][0]: x for x in at[TASK]['incr_actions']}
    fresh_tok = sum(incr[k]['fp_tok'] for k in incr if k.startswith('F:') and
                    ids[SRC][k[2:]] == ids['target'][k[2:]])
    gap_days = (pd.Timestamp(row.created_at) - pd.Timestamp(m_s.created_at + '+00:00')).total_seconds() / 86400

    # ---- illustrative memory note, built by fixed rules from the earlier trajectory
    note = build_note(S484, root484, m_s, ids[SRC], r484)
    note_chars = len(note)
    note_tok = tok(note_chars)

    # ---- patches
    os.makedirs(OUT, exist_ok=True)
    open(f'{OUT}/gold.patch', 'w').write(m_t.patch)
    open(f'{OUT}/test.patch', 'w').write(m_t.test_patch)
    open(f'{OUT}/memory-note-illustrative.md', 'w').write(note)
    lic = gh(f'repos/{REPO}/contents/LICENSE?ref={m_t.base_commit}')  # BSD-3-Clause: keep the notice next to quoted code
    open(f'{OUT}/LICENSE-ignite.txt', 'wb').write(__import__('base64').b64decode(lic['content']))
    sha = lambda s: hashlib.sha256(s.encode()).hexdigest()

    all_t = pd.read_parquet(f'{D}/trajectories.parquet', columns=['instance_id', 'resolved']) if os.path.exists(f'{D}/trajectories.parquet') else None
    n_rec = n_res = None
    if all_t is not None:
        x = all_t[all_t.instance_id == TASK]
        n_rec, n_res = int(len(x)), int(x.resolved.sum())

    P = lambda f: f'per_task.parquet, row instance_id={TASK}, field {f}'
    tot = int(row.tot_tokens_cache)
    data = dict(
        example='01-ignite-confusion-matrix',
        what_this_is=('Replay of recorded third-party agent runs. No memory system was run. Overlap is measured after the '
                      'fact at path/query level and is a ceiling. Tokens = characters / 4; not dollars.'),
        token_definitions=dict(
            flat='every message counted once (characters / 4)',
            cache_weighted=('each message weighted 1.0 the first time it is read and 0.1 on every later LLM call that '
                            're-reads it; assistant messages also count once as output'),
            footprint='cache-weighted tokens of an observation plus the assistant call that issued it'),
        sources=dict(
            trajectories=dict(dataset='nebius/SWE-rebench-openhands-trajectories', license='cc-by-4.0',
                              url='https://huggingface.co/datasets/nebius/SWE-rebench-openhands-trajectories',
                              model='Qwen/Qwen3-Coder-480B-A35B-Instruct', scaffold='OpenHands v0.54.0'),
            tasks=dict(dataset='nebius/SWE-rebench', split='test', license='cc-by-4.0',
                       url='https://huggingface.co/datasets/nebius/SWE-rebench'),
            upstream_repo=dict(repo=REPO, license='BSD-3-Clause', license_source='GitHub licence API and LICENSE at both base commits',
                               url=f'https://github.com/{REPO}')),
        task=dict(instance_id=TASK, issue='https://github.com/pytorch/ignite/issues/521',
                  fix_pr='https://github.com/pytorch/ignite/pull/522', base_commit=m_t.base_commit,
                  base_tree_url=f'https://github.com/{REPO}/tree/{m_t.base_commit}', created_at=m_t.created_at + '+00:00',
                  license_name=m_t.license_name, gold_files=list(row.gold_code), gold_patch_changed_lines=int(row.patch_lines),
                  fail_to_pass=list(m_t.FAIL_TO_PASS), pass_to_pass_count=len(m_t.PASS_TO_PASS),
                  recorded_trajectories_in_dataset=n_rec, recorded_trajectories_resolved=n_res,
                  provenance='rebench-test-*.parquet row instance_id; recorded counts from trajectories.parquet columns instance_id, resolved'),
        run=dict(trajectory_id=tid, picked_by='lowest md5(trajectory_id) among this instance\'s trajectories (model-blind)',
                 resolved=int(row.resolved), llm_calls=n_calls, tokens_flat=int(row.tot_tokens_flat),
                 tokens_cache_weighted=tot,
                 fixed_prompt_cache_weighted_tok=fixed_cache_tok,
                 fixed_prompt_note='system prompt + task message, chars/4 x (1 + 0.1 x (calls - 1)); part of tokens_cache_weighted',
                 agent_patch_sha256=sha(r522['model_patch']), gold_patch_sha256=sha(m_t.patch),
                 agent_patch_identical_to_gold_ignoring_final_newline=r522['model_patch'].rstrip('\n') == m_t.patch.rstrip('\n'),
                 agent_patch_note='same hunk and same index line (post-image blob 3546796a); the recorded agent diff lacks only the final newline',
                 provenance=('trajs.parquet (tot_flat, tot_cache, n_calls, resolved) via ' + P('tot_tokens_flat/tot_tokens_cache/n_calls/resolved') +
                             '; model_patch from trajectories.parquet row trajectory_id')),
        tenancy=dict(tenant=row.tenant, scheme='per repo, tasks sorted by created_at and dealt round-robin to 3 tenants',
                     own_earlier_tasks=[dict(instance_id=i, created_at=c) for i, c in zip(own.instance_id, own.created_at)],
                     all_earlier_tasks=[dict(instance_id=i, tenant=t, created_at=c,
                                             pr=f'https://github.com/{REPO}/pull/' + i.rsplit('-', 1)[1],
                                             issue_title=meta.loc[i, 'problem_statement'].splitlines()[0],
                                             recorded_run_resolved=int(tp.loc[i, 'resolved']),
                                             # first step (1-based) at which its picked run explored a path this task also explored first-touch
                                             overlap_first_steps={k: int(st) for k, st in first_steps(i).items()
                                                                  if any(k in x['keys'] for x in steps if x['status'] != 're-touch within this task (not counted)')})
                                        for i, t, c in zip(earlier.instance_id, earlier.tenant, earlier.created_at)],
                     provenance=P('own_hist/pool_hist') + '; tenants from per_task.parquet field tenant'),
        replay=dict(
            first_touch_exploration_actions=int(row.n_first_expl), repeated_own_history=int(row.n_rep_self),
            repeated_pool=int(row.n_rep_pool),
            removable_own_history_tok=int(row.removable_self_tok), removable_pool_tok=int(row.removable_pool_tok),
            cross_tenant_increment_tok=int(row.incr_tok),
            own_history_share=float(row.self_share), pool_share=float(row.pool_share), increment_share=float(row.incr_share),
            removable_own_history_obs_flat_tok=int(row.removable_self_obs_flat_tok),
            removable_pool_obs_flat_tok=int(row.removable_pool_obs_flat_tok),
            increment_by_kind_tok=dict(file_reads=int(row.incr_read_tok), directory_listings=int(row.incr_dir_tok),
                                       searches=int(row.incr_search_tok), git=int(row.incr_git_tok)),
            increment_obs_flat_tok=int(row.removable_pool_obs_flat_tok - row.removable_self_obs_flat_tok),
            increment_obs_flat_share_of_tokens_flat=round(float(row.removable_pool_obs_flat_tok - row.removable_self_obs_flat_tok) / int(row.tot_tokens_flat), 4),
            footprint_by_replay_class_tok={c: tok(v) for c, v in cls_fp.items()},
            footprint_by_replay_class_note='unrounded per-step footprints summed per class, then rounded; the rest of tokens_cache_weighted is the fixed prompt (plus rounding of a few tokens)',
            increment_actions=at[TASK]['incr_actions'],
            increment_sources=at[TASK]['top_src'],
            percentile_of_increment_share_among_1179_tasks=round(100 * float((pt.incr_share < row.incr_share).mean()), 1),
            all_tasks_median_increment_share=float(pt.incr_share.median()),
            all_tasks_share_with_any_increment=round(float((pt.incr_share > 0).mean()), 3),
            all_tasks_p90_increment_share=round(float(pt.incr_share.quantile(0.9)), 4),
            all_tasks_aggregate_own_share=round(float(pt.removable_self_tok.sum() / pt.tot_tokens_cache.sum()), 4),
            all_tasks_aggregate_pool_share=round(float(pt.removable_pool_tok.sum() / pt.tot_tokens_cache.sum()), 4),
            all_tasks_aggregate_increment_share=round(float(pt.incr_tok.sum() / pt.tot_tokens_cache.sum()), 4),
            all_tasks_count=int(len(pt)),
            provenance=P('n_first_expl, n_rep_self, n_rep_pool, removable_self_tok, removable_pool_tok, incr_tok, self_share, '
                         'pool_share, incr_share, removable_self_obs_flat_tok, removable_pool_obs_flat_tok, incr_*_tok') +
            f'; per_task_attrib.json key {TASK}; recomputed from actions.parquet in this script and asserted equal'),
        target_steps=steps,
        target_steps_provenance=f'actions.parquet rows trajectory_id={tid} (obs, obs_cache, call_cache, cat, keys); command text from the trajectory',
        earlier_run=dict(instance_id=SRC, tenant='tenant-3', created_at=m_s.created_at + '+00:00',
                         issue='https://github.com/pytorch/ignite/issues/448', fix_pr='https://github.com/pytorch/ignite/pull/484',
                         base_commit=m_s.base_commit, resolved=int(tp.loc[SRC, 'resolved']),
                         llm_calls=int(tp.loc[SRC, 'n_calls']),
                         gold_files=re.findall(r'^diff --git a/(\S+) b/', m_s.patch, flags=re.M),
                         agent_patch_files=list(tp.loc[SRC, 'model_patch_files']),
                         gap_days=round(gap_days, 1), steps=steps484,
                         test_file_contact=[dict(step=s['step'], action=s['action'], obs_tok=s['obs_tok']) for s in tv],
                         provenance='rebench-test-*.parquet row instance_id; trajs.parquet; actions.parquet rows of its picked trajectory'),
        secondary_source=dict(instance_id=SRC2, tenant='tenant-2', created_at=m_s2.created_at + '+00:00',
                              covers='directory listing ignite/metrics only (2,525 footprint tokens), also covered by ' + SRC,
                              commits_between=cmpj2.get('total_commits')),
        content_comparison=cmp_,
        staleness=dict(
            compare_url=f'https://github.com/{REPO}/compare/{m_s.base_commit}...{m_t.base_commit}',
            commits_between=cmpj.get('total_commits'), files_changed_between=len(cmpj.get('files', [])),
            first_commit_between=cmpj['commits'][0]['commit']['message'].split('\n')[0],
            changed_under_metrics=changed_metrics,
            own_history_fresh_tok=0,
            own_history_fresh_note=('README.rst blob differs at both own-history base commits (ignite-69, ignite-385) from the target; '
                                    'the repo-root tree differs at all bases; the sandbox-root listing (/workspace) is not a git object, unknown'),
            object_ids=ids, fresh_increment_tok=fresh_tok, fresh_increment_share=round(fresh_tok / row.incr_tok, 3),
            provenance='GitHub contents API (blob/tree sha of each path at each base commit) and compare API'),
        stricter_readings=dict(
            gold_file_only_tok=incr['F:ignite/metrics/confusion_matrix.py']['fp_tok'],
            gold_file_only_share=round(incr['F:ignite/metrics/confusion_matrix.py']['fp_tok'] / tot, 4),
            gold_file_plus_dir_tok=incr['F:ignite/metrics/confusion_matrix.py']['fp_tok'] + incr['D:ignite/metrics']['fp_tok'],
            gold_file_plus_dir_share=round((incr['F:ignite/metrics/confusion_matrix.py']['fp_tok'] + incr['D:ignite/metrics']['fp_tok']) / tot, 4),
            test_file_full_read_tok=incr['F:tests/ignite/metrics/test_confusion_matrix.py']['fp_tok'],
            note=('the earlier run viewed only lines 1-50 of the test file plus a grep, so the path-level match credits a full '
                  'read it never made; the gold file is the file the agent edited, which agents normally read before editing')),
        illustrative_note=dict(file='memory-note-illustrative.md', chars=note_chars, tokens=note_tok,
                               cost_if_injected_before_call_1_cache_weighted_tok=tok(note_chars * (1 + 0.1 * (n_calls - 1))),
                               formula='tokens x (1 + 0.1 x (llm_calls - 1)), same weighting as the replay',
                               increment_net_of_note_tok=int(row.incr_tok) - tok(note_chars * (1 + 0.1 * (n_calls - 1))),
                               increment_net_of_note_share=round((int(row.incr_tok) - tok(note_chars * (1 + 0.1 * (n_calls - 1)))) / tot, 4)),
    )
    json.dump(data, open(f'{OUT}/data.json', 'w'), indent=1, default=str)
    write_excerpt(steps, steps484, S522, S484, root, root484, cmp_)
    print(json.dumps({k: data[k] for k in ('replay', 'stricter_readings', 'illustrative_note')}, indent=1, default=str)[:4000])


def build_note(S, root, m, ids_src, r):
    """Fixed, target-blind rules applied to every step of the earlier run: (1) every file/directory inside the repository
    it opened (files it created itself excluded), with the git object id at its base commit; (2) the class/def outline
    of every .py file among them that it viewed in full; (3) every directory listing of the repository, as entry names
    relative to the listed directory; (4) every pytest run that printed per-test outcomes: command and summary, then the
    test node ids with outcomes, de-duplicated across runs; (5) str_replace/insert edits on files it did not create.
    Nothing is written by hand and nothing depends on the later task."""
    created = set()
    for s in S:
        a = s['args']
        if s['tool'] == 'str_replace_editor' and a.get('command') == 'create':
            created.add(rel(a.get('path') or '', root))
    L = []
    L.append('# ILLUSTRATIVE memory note (not produced by any system)\n')
    L.append('Built by `scripts/build_example_01.py` with fixed rules from the recorded trajectory of '
             f'`{m.name}` (tenant-3). No memory system produced this text and no agent was given it. It shows what a '
             'distilled note *could* contain if it were made only from what that earlier run actually saw. The rules '
             'look only at the earlier run, never at the later task: (1) every file/directory inside the repository it '
             'opened (files it created itself are left out), with the git object id at its base commit; (2) the class/def '
             'outline of every .py file it viewed in full; (3) every directory listing of the repository, as entry names; '
             '(4) every test run that printed per-test outcomes: command, summary, and the test ids with outcomes, '
             'de-duplicated across runs; (5) edits it made to files it did not create. The token numbers in the README '
             'do not depend on this note.\n')
    L.append(f'- Source task: `{m.name}` (issue: "{m.problem_statement.splitlines()[0]}")')
    L.append(f'- Source base commit: `{m.base_commit[:10]}`; recorded run resolved its own task: {bool(r["resolved"])}\n')
    seen = []
    for i, s in enumerate(S, 1):
        a = s['args']
        if s['tool'] == 'str_replace_editor' and a.get('command') == 'view':
            p = rel(a.get('path') or '', root)
            if p.startswith('/') or p in created:  # outside the repository, or a scratch file of its own
                continue
            seen.append((i, p, a.get('view_range'), s['obs']))
    L.append('## Files and directories it opened (first view of each)\n')
    L.append('| Path | What it saw | Object id at source commit |')
    L.append('|---|---|---|')
    done = set()
    for i, p, vr, o in seen:
        if p in done:
            continue
        done.add(p)
        kind = 'directory listing' if o.startswith("Here's the files and directories") else (
            f'lines {vr[0]}-{vr[1]}' if vr else 'whole file')
        oid = ids_src.get(p)
        L.append(f'| `{p}` | {kind} (step {i}) | {oid[0] + " " + oid[1][:10] if oid else "not checked"} |')
    L.append('')
    done = set()
    for i, p, vr, o in seen:
        if (p, vr is None) in done:
            continue
        if o.startswith("Here's the files and directories"):
            done.add((p, True))
            pre = '' if p == '.' else p + '/'
            names = [x[len(pre):] for x in (rel(l.strip(), root) for l in o.splitlines()[1:] if l.strip().startswith(root + '/'))
                     if x.startswith(pre) and x != pre]  # entry lines only; the tool's trailer text is dropped
            L.append(f'## Listing of `{p}` (step {i}, entry names relative to it)\n')
            L.append(', '.join(f'`{n}`' for n in names) + '\n')
        elif p.endswith('.py') and not vr:
            done.add((p, True))
            L.append(f'## Outline of `{p}` (class/def lines as numbered in its step-{i} view)\n')
            L.append('```')
            for l in o.splitlines():
                mm = re.match(r'^\s*(\d+)\t(\s*(?:class|def) .*)$', l)
                if mm:
                    L.append(f'{mm.group(1):>4}  {mm.group(2).rstrip()}')
            L.append('```\n')
    runs, outcome = [], {}
    for i, s in enumerate(S, 1):
        c = s['args'].get('command') or ''
        if s['tool'] != 'execute_bash' or 'pytest' not in c:
            continue
        tests = re.findall(r'^(\S+::\S+) (PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)', s['obs'], flags=re.M)
        if not tests:
            continue
        summ = re.findall(r'=+ (\d+ (?:passed|failed|error)[^=]*?) =+', s['obs'])
        runs.append(f'- step {i}: `' + rel(c, root).replace('cd . && ', '') + '`; result: ' + (summ[-1].strip() if summ else 'no summary line')
                    + ('; output truncated in the recording, ' + str(len(tests)) + ' per-test lines visible' if 'Observation truncated' in s['obs'] else ''))
        for t, o in tests:
            outcome.setdefault(t, set()).add(o)
    if runs:
        L.append('## Test runs with per-test outcomes\n')
        L.extend(runs)
        L.append('')
        files = list(dict.fromkeys(t.split('::', 1)[0] for t in outcome))
        L.append(f'Test ids seen across these runs ({len(outcome)} unique):\n')
        for f in files:
            L.append(f'- `{f}`: ' + ', '.join(f'`{t.split("::", 1)[1]}` {"/".join(sorted(outcome[t]))}' for t in outcome if t.startswith(f + '::')))
        L.append('')
    L.append('## Edits to files it did not create (str_replace / insert)\n')
    for i, s in enumerate(S, 1):
        a = s['args']
        if s['tool'] == 'str_replace_editor' and a.get('command') in ('str_replace', 'insert'):
            p = rel(a.get('path') or '', root)
            if p not in created:
                L.append(f'- step {i}: `{p}` ({a.get("command")})')
    L.append('')
    return '\n'.join(L)


def table(steps, cols):
    out = ['| ' + ' | '.join(h for h, _ in cols) + ' |', '|' + '---|' * len(cols)]
    for s in steps:
        out.append('| ' + ' | '.join(str(f(s)).replace('|', '\\|') for _, f in cols) + ' |')
    return '\n'.join(out)


def write_excerpt(steps, steps484, S522, S484, root, root484, cmp_):
    short = {'own history': 'own history', 'other tenant only (cross-tenant increment)': 'other tenant',
             'new (no earlier task explored it)': 'new', 're-touch within this task (not counted)': 're-touch (not counted)',
             'not exploration (not counted)': '-'}
    L = ['# Trajectory excerpt: pytorch__ignite-522 (and the earlier pytorch__ignite-484)\n',
         'Generated by `scripts/build_example_01.py`. Source: HF `nebius/SWE-rebench-openhands-trajectories` (cc-by-4.0), '
         'recorded runs of Qwen3-Coder-480B-A35B-Instruct on OpenHands v0.54.0. Paths are shown relative to the repo root '
         '(the sandbox checkout directory is stripped). In quoted outputs, pytest\'s `=` padding and `[NN%]` progress markers are '
         'shortened or dropped, the OpenHands command-status lines at the end are dropped, trailing whitespace and emoji are '
         'removed, and lines are cut at 160 characters; in the tables, long commands are cut with `...`. Tokens = characters / 4; '
         'they are not dollars. No memory system was run: this is a recorded run, and any overlap marked here was '
         'computed after the fact at path/query level (a ceiling).\n',
         '- **obs** = tokens of the tool output, counted once.',
         '- **footprint** = cache-weighted tokens of the output plus the call that issued it (1.0 first read, 0.1 on each later call).',
         '- **seen earlier?** = the replay\'s verdict for exploration actions (first touch only): `own history` = a tenant-1 '
         'task had explored the same path/query; `other tenant` = only another tenant had; `new` = nobody had.\n',
         '## 1. Every step of the pytorch__ignite-522 run (tenant-1, resolved)\n']
    L.append(table(steps, [('step', lambda s: s['step']), ('tool', lambda s: s['tool']), ('action', lambda s: '`' + s['action'] + '`'),
                           ('replay class', lambda s: s['replay_class']), ('obs', lambda s: f"{s['obs_tok']:,}"),
                           ('footprint', lambda s: f"{s['footprint_cache_tok']:,}"), ('seen earlier?', lambda s: short[s['status']] if s['status'] != 'other tenant only (cross-tenant increment)' else
                            '**other tenant (' + ', '.join(i.rsplit('__', 1)[-1] for i in s['earlier_tasks_with_same_key']) + ')**')]))
    L.append('')
    L.append('## 2. Key moments, verbatim (tool output trimmed with [...])\n')

    def obs_block(i, n_lines=None, grep=None):
        o = clean_obs(S522[i - 1]['obs'], root)
        ls = o.splitlines()
        if grep:
            ls = [l for l in ls if re.search(grep, l)]
        if n_lines and len(ls) > n_lines:
            ls = ls[:n_lines] + ['[...]']
        return '```\n' + '\n'.join(re.sub(r'\s+\[\s*\d+%\]$', '', l)[:160].rstrip() for l in ls) + '\n```\n'
    L.append('**Step 8**: before reading any code, the agent runs the existing tests (the same command and the same 13 '
             'results as step 48 of the earlier ignite-484 run; test runs are not counted as exploration by the replay).\n')
    L.append(obs_block(8, grep=r'PASSED|FAILED|passed|failed'))
    L.append('**Step 15**: the lines named in the issue, re-viewed after the full-file read in step 10.\n')
    L.append(obs_block(15))
    a19 = S522[18]['args']
    L.append('**Step 19**: the edit (str_replace arguments).\n')
    L.append('```diff\n' + '\n'.join('- ' + l for l in a19['old_str'].splitlines()) + '\n' +
             '\n'.join('+ ' + l for l in a19['new_str'].splitlines()) + '\n```\n')
    L.append('**Step 23**: the existing test file still passes after the edit.\n')
    L.append(obs_block(23, grep=r'passed|failed'))
    L.append('## 3. The earlier run: pytorch__ignite-484 (tenant-3, resolved): exploration steps, edits to existing repository files, and its run of the confusion-matrix tests\n')
    L.append('`in 522 increment?` marks steps whose path is one of the three paths that make up the cross-tenant increment of ignite-522.\n')
    keep = [s for s in steps484 if s['replay_class'].startswith('explore') or
            (s['replay_class'] == 'edit' and '/' in s['action'].split(' ', 1)[-1]) or 'test_confusion_matrix.py -v' in s['action']]
    L.append(table(keep, [('step', lambda s: s['step']), ('action', lambda s: '`' + s['action'] + '`'),
                          ('replay class', lambda s: s['replay_class']), ('obs', lambda s: f"{s['obs_tok']:,}"),
                          ('in 522 increment?', lambda s: 'yes' if s['key_in_target_increment'] else '')]))
    L.append('')
    L.append('## 4. Same path, same content? (outputs compared line by line, sandbox directory name stripped)\n')
    L.append(table(cmp_, [('what', lambda s: s['what']), ('522 step', lambda s: s['target_step']),
                          ('484 step', lambda s: s['earlier_step']), ('identical', lambda s: 'yes' if s['identical'] else 'no'),
                          ('lines only in 522', lambda s: s['lines_only_in_target']),
                          ('lines only in 484', lambda s: s['lines_only_in_earlier']),
                          ('example differing line (522 / 484)', lambda s: ' / '.join('`' + x[0][:60] + '`' for x in (s['sample_lines_only_in_target'], s['sample_lines_only_in_earlier']) if x) or '-')]))
    L.append('')
    open(f'{OUT}/trajectory-excerpt.md', 'w').write('\n'.join(L))


if __name__ == '__main__':
    main()
