#!/usr/bin/env python3
"""Per-task offline replay: for every task in the 3-tenant set (18 repos with >=30 trajectory tasks, 1,179 tasks),
compute own-history vs 3-tenant-pool overlap of exploration, and attribute the cross-tenant part to the earlier
tasks that supplied it.

This is a REPLAY of recorded third-party agent runs. No memory system was run. "Removable" means: the exploration
action's path/query key had already been explored by an earlier task in the relevant history (a ceiling, at
path/query level, not content level).

Inputs (in $SMEM_DATA, default ./data):
  trajs.parquet, actions.parquet   -- produced by the extraction step from
                                      HF nebius/SWE-rebench-openhands-trajectories (trajectories.parquet)
  rebench-test-0000{0,1}-of-00002.parquet  -- HF nebius/SWE-rebench, test split
Output: $SMEM_DATA/per_task.parquet, $SMEM_DATA/per_task_attrib.json

Definitions follow the aggregate replay exactly:
  * one trajectory per instance: lowest md5(trajectory_id)  ("pickP")
  * repos with >=30 picked trajectories; tasks sorted by (created_at, instance_id); tenant = index % 3 (round-robin)
  * history = tasks with strictly earlier created_at; self = same tenant, pool = all 3 tenants
  * exploration = file views/reads (key F:path), directory listings (D:path), searches (S:normalized command),
    git log/show/blame (G:normalized command); first touch within a task only
  * tokens = chars/4; cache-weighted footprint = observation + issuing call, weight 1.0 first read, 0.1 later reads
"""
import json, os, re
from collections import defaultdict
import pandas as pd

D = os.environ.get('SMEM_DATA', 'data')
EXPL = ('explore-read', 'explore-dir', 'explore-search', 'explore-git')
NT = 3
CODE_EXT = ('.py', '.pyx', '.pxd', '.pyi', '.c', '.h', '.cc', '.cpp', '.hpp', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java',
            '.kt', '.rb', '.php', '.scala', '.cs', '.swift', '.m', '.jl', '.r', '.R', '.sql', '.lua', '.sh')


def gold_files(patch):
    return sorted(set(re.findall(r'^diff --git a/(\S+) b/', patch or '', flags=re.M)))


def code_only(files):
    return [f for f in files if f.endswith(CODE_EXT) and not re.match(r'^(docs?|doc_src|changelog\.d|changes|news)/', f)]


def patch_lines(patch):
    n = 0
    for l in (patch or '').splitlines():
        if (l.startswith('+') and not l.startswith('+++')) or (l.startswith('-') and not l.startswith('---')):
            n += 1
    return n


def main():
    fs = [f'{D}/rebench-test-00000-of-00002.parquet', f'{D}/rebench-test-00001-of-00002.parquet']
    cols = ['instance_id', 'repo', 'created_at', 'patch', 'base_commit', 'problem_statement', 'license_name']
    meta = pd.concat([pd.read_parquet(f, columns=cols) for f in fs]).drop_duplicates('instance_id')
    meta['created_at'] = pd.to_datetime(meta['created_at'], utc=True, format='mixed')
    meta['gold'] = meta['patch'].map(gold_files)
    meta['gold_code'] = meta['gold'].map(code_only)
    meta['patch_lines'] = meta['patch'].map(patch_lines)
    meta['ps_chars'] = meta['problem_statement'].fillna('').str.len()
    trajs = pd.read_parquet(f'{D}/trajs.parquet')
    acts = pd.read_parquet(f'{D}/actions.parquet')
    tp = trajs[trajs.pickP].merge(meta[['instance_id', 'created_at', 'gold', 'gold_code', 'patch_lines', 'ps_chars',
                                        'base_commit', 'license_name']], on='instance_id')
    vc = tp.repo.value_counts()
    repos = sorted(vc[vc >= 30].index)
    tp = tp[tp.repo.isin(repos)]
    A = acts[acts.trajectory_id.isin(set(tp.trajectory_id))].sort_values(['trajectory_id', 'idx'])
    abt = defaultdict(list)
    for a in A[['trajectory_id', 'cat', 'keys', 'obs', 'obs_cache', 'call_cache']].to_dict('records'):
        abt[a['trajectory_id']].append(a)
    edits = defaultdict(set)  # files edited by the agent in the trajectory (editor create/str_replace/insert)
    for r in acts[acts.trajectory_id.isin(set(tp.trajectory_id)) & (acts.cat == 'edit')][['trajectory_id', 'keys']].itertuples():
        for k in r.keys:
            edits[r.trajectory_id].add(k[2:])

    out, attrib = [], {}
    for repo in repos:
        g = tp[tp.repo == repo].sort_values(['created_at', 'instance_id']).reset_index(drop=True)
        ten = [i % NT for i in range(len(g))]
        times = g['created_at'].tolist()
        seen_t = [dict() for _ in range(NT)]   # key -> list of earlier task indices that explored it
        gold_by_t = [defaultdict(list) for _ in range(NT)]  # gold code file -> earlier task idx (gold patch edited it)
        viewed_by_t = [defaultdict(list) for _ in range(NT)]  # file -> earlier idx whose trajectory viewed it
        edited_by_t = [defaultdict(list) for _ in range(NT)]  # file -> earlier idx whose trajectory edited it
        pending, tk = [], []
        for i, t in enumerate(g.itertuples()):
            while pending and times[pending[0]] < times[i]:
                j = pending.pop(0)
                for k in tk[j]:
                    seen_t[ten[j]].setdefault(k, []).append(j)
                    if k.startswith('F:'):
                        viewed_by_t[ten[j]][k[2:]].append(j)
                for f in g.at[j, 'gold_code']:
                    gold_by_t[ten[j]][f].append(j)
                for f in edits[g.at[j, 'trajectory_id']]:
                    edited_by_t[ten[j]][f].append(j)
            me = ten[i]
            s = seen_t[me]
            within, own_keys = set(), set()
            sv_self = sv_pool = 0.0
            ob_self = ob_pool = 0.0
            n_first = n_self = n_pool = 0
            incr_by_cat = defaultdict(float)
            incr_src = defaultdict(float)   # earlier task idx (other tenant) -> fp tokens of increment it alone covers
            incr_actions = []
            for a in abt.get(t.trajectory_id, []):
                if a['cat'] not in EXPL:
                    continue
                keys = list(a['keys'])
                if not keys:
                    continue
                first = not all(k in within for k in keys)
                within.update(keys)
                own_keys.update(keys)
                if not first:
                    continue
                n_first += 1
                in_self = all(k in s for k in keys)
                in_pool = all(any(k in seen_t[x] for x in range(NT)) for k in keys)
                fp = a['obs_cache'] + a['call_cache']
                if in_self:
                    sv_self += fp; ob_self += a['obs']; n_self += 1
                if in_pool:
                    sv_pool += fp; ob_pool += a['obs']; n_pool += 1
                if in_pool and not in_self:
                    incr_by_cat[a['cat']] += fp
                    cands = None
                    for k in keys:
                        js = set(j for x in range(NT) if x != me for j in seen_t[x].get(k, []))
                        cands = js if cands is None else cands & js
                    for j in (cands or ()):
                        incr_src[j] += fp
                    incr_actions.append(dict(cat=a['cat'], keys=keys, fp_tok=round(fp / 4), obs_tok=round(a['obs'] / 4)))
            G = set(t.gold_code)
            gold_other = {f: sorted(set(j for x in range(NT) if x != me for j in gold_by_t[x].get(f, []))) for f in G}
            gold_self = {f: sorted(set(gold_by_t[me].get(f, []))) for f in G}
            gview_other = {f: sorted(set(j for x in range(NT) if x != me for j in viewed_by_t[x].get(f, []))) for f in G}
            gview_self = {f: sorted(set(viewed_by_t[me].get(f, []))) for f in G}
            gedit_other = {f: sorted(set(j for x in range(NT) if x != me for j in edited_by_t[x].get(f, []))) for f in G}
            own_hist = sum(1 for j in range(i) if ten[j] == me and times[j] < times[i])
            pool_hist = sum(1 for j in range(i) if times[j] < times[i])
            top = sorted(incr_src.items(), key=lambda kv: -kv[1])[:5]
            row = dict(instance_id=t.instance_id, repo=repo, tenant=f'tenant-{me + 1}', idx=i, created_at=str(t.created_at),
                       base_commit=t.base_commit, license=t.license_name, resolved=int(t.resolved), n_calls=int(t.n_calls),
                       own_hist=own_hist, pool_hist=pool_hist,
                       tot_tokens_flat=round(t.tot_flat / 4), tot_tokens_cache=round(t.tot_cache / 4),
                       removable_self_tok=round(sv_self / 4), removable_pool_tok=round(sv_pool / 4),
                       incr_tok=round((sv_pool - sv_self) / 4),
                       removable_self_obs_flat_tok=round(ob_self / 4), removable_pool_obs_flat_tok=round(ob_pool / 4),
                       self_share=round(sv_self / t.tot_cache, 4), pool_share=round(sv_pool / t.tot_cache, 4),
                       incr_share=round((sv_pool - sv_self) / t.tot_cache, 4),
                       n_first_expl=n_first, n_rep_self=n_self, n_rep_pool=n_pool,
                       incr_read_tok=round(incr_by_cat['explore-read'] / 4), incr_dir_tok=round(incr_by_cat['explore-dir'] / 4),
                       incr_search_tok=round(incr_by_cat['explore-search'] / 4), incr_git_tok=round(incr_by_cat['explore-git'] / 4),
                       gold_code=sorted(G), n_gold=len(G),
                       gold_edited_by_other=any(bool(v) for v in gold_other.values()),
                       gold_edited_by_self=any(bool(v) for v in gold_self.values()),
                       gold_viewed_by_other_traj=any(bool(v) for v in gview_other.values()),
                       gold_viewed_by_self_traj=any(bool(v) for v in gview_self.values()),
                       gold_edited_by_other_traj=any(bool(v) for v in gedit_other.values()),
                       patch_lines=int(t.patch_lines), ps_chars=int(t.ps_chars),
                       top_src=[g.at[j, 'instance_id'] for j, _ in top], top_src_tok=[round(v / 4) for _, v in top])
            out.append(row)
            attrib[t.instance_id] = dict(
                incr_actions=incr_actions,
                top_src=[dict(instance_id=g.at[j, 'instance_id'], tenant=f'tenant-{ten[j] + 1}', created_at=str(times[j]),
                              covers_incr_tok=round(v / 4)) for j, v in top],
                gold_edited_by_other={f: [g.at[j, 'instance_id'] for j in v] for f, v in gold_other.items()},
                gold_edited_by_self={f: [g.at[j, 'instance_id'] for j in v] for f, v in gold_self.items()},
                gold_viewed_by_other_traj={f: [g.at[j, 'instance_id'] for j in v] for f, v in gview_other.items()},
                gold_viewed_by_self_traj={f: [g.at[j, 'instance_id'] for j in v] for f, v in gview_self.items()},
                gold_edited_by_other_traj={f: [g.at[j, 'instance_id'] for j in v] for f, v in gedit_other.items()})
            tk.append(own_keys)
            pending.append(i)
    df = pd.DataFrame(out)
    df.to_parquet(f'{D}/per_task.parquet')
    json.dump(attrib, open(f'{D}/per_task_attrib.json', 'w'), indent=0)
    # consistency with the aggregate replay (Table 3 RR primary: 14.8 -> 18.1 of all tokens)
    T = tp.set_index('instance_id').loc[df.instance_id, 'tot_cache'].sum() / 4
    print('tasks', len(df), 'repos', df.repo.nunique())
    print('removable self %.1f%%  pool %.1f%%  incr %.1fpp' % (100 * df.removable_self_tok.sum() / T, 100 * df.removable_pool_tok.sum() / T,
                                                             100 * df.incr_tok.sum() / T))
    bk = pd.cut(df.own_hist, [-1, 4, 19, 10**6], labels=['0-4', '5-19', '20+'])
    for b, x in df.groupby(bk, observed=True):
        tc = x.tot_tokens_cache.sum()
        print(b, len(x), 'self %.1f%% incr %.1f%%' % (100 * x.removable_self_tok.sum() / tc, 100 * x.incr_tok.sum() / tc))


if __name__ == '__main__':
    main()
