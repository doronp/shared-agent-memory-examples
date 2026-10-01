#!/usr/bin/env python3
"""Staleness check for a (task, earlier task) pair: for every path the earlier task explored that overlaps the
cross-tenant increment of the later task (plus the later task's gold files), compare the git object id of that
path at the earlier task's base commit and at the later task's base commit (GitHub contents/trees API via `gh`).
Same id => the remembered content would still be byte-identical; different id => stale.

Usage: SMEM_DATA=data python staleness.py TASK_ID [EARLIER_TASK_ID ...]
(if no earlier ids are given, the top sources from per_task_attrib.json are used)
For an earlier task of the SAME tenant (own history) the overlap is taken over all first-touch exploration actions of
the later task instead of the cross-tenant increment.
"""
import json, os, subprocess, sys
import pandas as pd

D = os.environ.get('SMEM_DATA', 'data')


def gh(path):
    r = subprocess.run(['gh', 'api', path], capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


_cache = {}


def obj_id(repo, sha, path):
    """blob sha for a file, tree sha for a directory, None if absent."""
    k = (repo, sha, path)
    if k in _cache:
        return _cache[k]
    if path in ('.', ''):
        j = gh(f'repos/{repo}/commits/{sha}')
        v = ('tree', j['commit']['tree']['sha']) if j else None
    else:
        parent, _, name = path.rpartition('/')
        j = gh(f'repos/{repo}/contents/{parent}?ref={sha}') if parent else gh(f'repos/{repo}/contents?ref={sha}')
        v = None
        if isinstance(j, list):
            for e in j:
                if e['name'] == name:
                    v = (e['type'], e['sha'])
    _cache[k] = v
    return v


def n_commits(repo, path, since_sha, until_sha):
    j = gh(f'repos/{repo}/compare/{since_sha}...{until_sha}')
    if not j:
        return None, None
    files = {f['filename']: f for f in j.get('files', [])}
    f = files.get(path)
    return j.get('total_commits'), (f['additions'] + f['deletions'] if f else 0) if len(files) < 300 else None


def main():
    meta = pd.read_parquet(f'{D}/per_task.parquet').set_index('instance_id')
    at = json.load(open(f'{D}/per_task_attrib.json'))
    acts = pd.read_parquet(f'{D}/actions.parquet', columns=['trajectory_id', 'idx', 'cat', 'keys', 'obs', 'obs_cache', 'call_cache'])
    trajs = pd.read_parquet(f'{D}/trajs.parquet')
    tid = trajs[trajs.pickP].set_index('instance_id')['trajectory_id']
    tgt = sys.argv[1]
    srcs = sys.argv[2:] or [s['instance_id'] for s in at[tgt]['top_src'][:2]]
    r = meta.loc[tgt]
    repo = r.repo
    first, within = [], set()  # first-touch exploration actions of the later task (for own-history sources)
    for a in acts[(acts.trajectory_id == tid[tgt]) & acts.cat.str.startswith('explore')].sort_values('idx').itertuples():
        ks = list(a.keys)
        if ks and not all(k in within for k in ks):
            first.append(dict(cat=a.cat, keys=ks, fp_tok=round((a.obs_cache + a.call_cache) / 4), obs_tok=round(a.obs / 4)))
        within.update(ks)
    out = dict(task=tgt, repo=repo, base_commit=r.base_commit, sources=[])
    for s in srcs:
        rs = meta.loc[s]
        skeys = set(k for ks in acts[(acts.trajectory_id == tid[s]) & acts.cat.str.startswith('explore')]['keys'] for k in ks)
        pool = first if rs.tenant == r.tenant else at[tgt]['incr_actions']
        ov = [a for a in pool if all(k in skeys for k in a['keys'])]
        paths = []
        for a in ov:
            for k in a['keys']:
                if k[:2] in ('F:', 'D:') and not k[2:].startswith('EXT:'):
                    paths.append((k[2:], a['fp_tok'], a['obs_tok'], a['cat']))
        for g in r.gold_code:
            if g not in [p[0] for p in paths]:
                paths.append((g, 0, 0, 'gold-only'))
        cmp_ = gh(f'repos/{repo}/compare/{rs.base_commit}...{r.base_commit}')
        # GitHub reports 0/0 additions/deletions for a modified file when it truncates a large compare -> unknown (None)
        changed = {f['filename']: (f['additions'] + f['deletions']) or None for f in (cmp_ or {}).get('files', [])}
        res = []
        for p, fp, ob, cat in paths:
            a, b = obj_id(repo, rs.base_commit, p), obj_id(repo, r.base_commit, p)
            res.append(dict(path=p, cat=cat, fp_tok=fp, obs_tok=ob, same=(a == b and a is not None), at_earlier=a and a[1][:10],
                            at_later=b and b[1][:10], lines_changed=changed.get(p, 0) if len(changed) < 300 else None))
        out['sources'].append(dict(instance_id=s, tenant=rs.tenant, created_at=rs.created_at, base_commit=rs.base_commit,
                                   commits_between=(cmp_ or {}).get('total_commits'), files_changed_between=len(changed),
                                   compare_status=(cmp_ or {}).get('status'), paths=res))
    print(json.dumps(out, indent=1, default=str))


if __name__ == '__main__':
    main()
