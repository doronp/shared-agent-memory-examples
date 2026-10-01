#!/usr/bin/env python3
"""Dump the picked trajectory (lowest md5(trajectory_id)) of one or more instances as a compact step list:
step, tool, command/path, observation size in tokens (chars/4), and whether the replay classed it as exploration.

Usage: SMEM_DATA=data python dump_trajectory.py INSTANCE_ID [...]
Writes $SMEM_DATA/traj_<instance_id>.json (full messages of the picked trajectory) and prints the step list.
"""
import json, os, sys
import pyarrow.parquet as pq
import pyarrow.compute as pc
import pandas as pd

D = os.environ.get('SMEM_DATA', 'data')


def main():
    ids = sys.argv[1:]
    trajs = pd.read_parquet(f'{D}/trajs.parquet')
    tid = trajs[trajs.pickP & trajs.instance_id.isin(ids)].set_index('instance_id')['trajectory_id'].to_dict()
    want = set(tid.values())
    pf = pq.ParquetFile(f'{D}/trajectories.parquet')
    found = {}
    for rg in range(pf.metadata.num_row_groups):
        t = pf.read_row_group(rg, columns=['trajectory_id'])
        mask = pc.is_in(t['trajectory_id'], value_set=__import__('pyarrow').array(list(want)))
        if not pc.any(mask).as_py():
            continue
        tb = pf.read_row_group(rg, columns=['trajectory_id', 'instance_id', 'trajectory', 'model_patch', 'resolved', 'exit_status']).filter(mask)
        for r in tb.to_pylist():
            found[r['instance_id']] = r
        if len(found) == len(want):
            break
    for iid in ids:
        r = found[iid]
        json.dump(r, open(f'{D}/traj_{iid}.json', 'w'), indent=0)
        print('=' * 20, iid, r['trajectory_id'], 'resolved', r['resolved'], r['exit_status'])
        step = 0
        obs = {m.get('tool_call_id'): m for m in r['trajectory'] if m['role'] == 'tool'}
        for m in r['trajectory']:
            if m['role'] != 'assistant':
                continue
            step += 1
            for tc in (m.get('tool_calls') or []):
                f = tc['function']
                try:
                    a = json.loads(f.get('arguments') or '{}')
                except Exception:
                    a = {}
                o = obs.get(tc.get('id'), {}).get('content') or ''
                if f['name'] == 'str_replace_editor':
                    desc = f"{a.get('command')} {a.get('path')} {a.get('view_range') or ''}"
                elif f['name'] == 'execute_bash':
                    desc = (a.get('command') or '').replace('\n', ' ')[:160]
                else:
                    desc = (json.dumps(a)[:100])
                print(f'{step:3d} {f["name"][:18]:18s} {len(o) // 4:6d}t  {desc}')


if __name__ == '__main__':
    main()
