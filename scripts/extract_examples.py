#!/usr/bin/env python3
"""Download the public data, rebuild the replay tables, regenerate examples/*/data.json, and self-check them.

THIS IS A REPLAY OF RECORDED THIRD-PARTY AGENT RUNS. No memory system was run and no agent was given a memory.
Overlap between a task and earlier tasks is measured after the fact, at the level of file paths and search queries,
so every saving it reports is a ceiling. Tokens are characters / 4. Tokens are not dollars.

Usage, from the repository root:

  python scripts/extract_examples.py download   # the two Hugging Face datasets (about 2.3 GB) into the data directory
  python scripts/extract_examples.py extract    # trajectories.parquet -> trajs.parquet + actions.parquet
  python scripts/extract_examples.py replay     # scripts/per_task_replay.py -> per_task.parquet + per_task_attrib.json
  python scripts/extract_examples.py dumps      # scripts/dump_trajectory.py -> traj_<task>.json (used by example 01)
  python scripts/extract_examples.py staleness  # scripts/staleness.py -> stale_<task>*.json (public GitHub API, `gh`)
  python scripts/extract_examples.py build      # the three example builders -> examples/*/data.json and other files
  python scripts/extract_examples.py check      # assert-based self-check on the local data (no network)
  python scripts/extract_examples.py all        # extract, replay, dumps, staleness, build, check (not download)

Data directory: --data DIR, else $SMEM_DATA, else ./data (git-ignored).

Dependencies: this file itself uses only the Python standard library and pyarrow. The replay, staleness and builder
scripts that it runs as subprocesses also import pandas, and the staleness and build steps call the public GitHub API
through the `gh` CLI. The simplest way to get both libraries:

  uv run --with pyarrow --with pandas python scripts/extract_examples.py all

Sources (both CC BY 4.0; see DATA-LICENSE.md):
  nebius/SWE-rebench, test split                  task records: repo, created_at, base_commit, patch, problem_statement
  nebius/SWE-rebench-openhands-trajectories       67,074 recorded runs of Qwen3-Coder-480B-A35B-Instruct on OpenHands
                                                  v0.54.0
The revisions below are pinned and every downloaded file is checked against its size and SHA-256.

The `extract` step is the extraction used by the replay, unchanged apart from taking the data directory as a parameter:
one trajectory per instance is picked as the lowest md5(trajectory_id) ("pickP", model-blind), plus a resolved-preferred
pick ("pickR") that the examples do not use. Every tool call becomes one row of actions.parquet with its category
(file read, directory listing, search, git lookup, edit, run, ...), its keys (repo-relative path, or the normalized
search command) and its token weights.
"""
import argparse
import hashlib
import json
import os
import re
import shlex
import statistics
import subprocess
import sys
import urllib.request
from collections import defaultdict
from multiprocessing import Pool

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# ----------------------------------------------------------------------------------------------------------------------
# Downloads (pinned revisions; sizes and SHA-256 from the Hugging Face API)
# ----------------------------------------------------------------------------------------------------------------------
REBENCH_REV = '89cdfbab4ab1bd8f5a658bb212d1b63624f4f881'
TRAJ_REV = '35455389ab51bf5e2306bfd436ef72d0f98bf882'
FILES = [
    # (dataset, revision, path in the dataset, local name, size in bytes, sha256)
    ('nebius/SWE-rebench', REBENCH_REV, 'data/test-00000-of-00002.parquet', 'rebench-test-00000-of-00002.parquet',
     101556119, '39d4791f12cf5ee2a2e56d47eeef559642a800534ff053e1ae3acab0a0c87067'),
    ('nebius/SWE-rebench', REBENCH_REV, 'data/test-00001-of-00002.parquet', 'rebench-test-00001-of-00002.parquet',
     109723276, 'c50af8bffbfe70fc3a89b2e47825f299bc04c1058318fe2263b7e4857f8193d7'),
    ('nebius/SWE-rebench-openhands-trajectories', TRAJ_REV, 'trajectories.parquet', 'trajectories.parquet',
     2079503354, '14048dd1fcd22ce094b6e85f8a38f223a9ef1327031aaaad052804870212efa1'),
]
REBENCH = ['rebench-test-00000-of-00002.parquet', 'rebench-test-00001-of-00002.parquet']


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


def download(D, verify=False):
    os.makedirs(D, exist_ok=True)
    for ds, rev, path, name, size, sha in FILES:
        dst = os.path.join(D, name)
        if os.path.exists(dst) and os.path.getsize(dst) == size:
            if verify:
                assert sha256_of(dst) == sha, f'{dst}: SHA-256 mismatch'
            print(f'present  {name} ({size:,} bytes){" sha256 ok" if verify else ""}')
            continue
        url = f'https://huggingface.co/datasets/{ds}/resolve/{rev}/{path}'
        print(f'download {url}\n      -> {dst} ({size:,} bytes)', flush=True)
        h, n, part = hashlib.sha256(), 0, dst + '.part'
        with urllib.request.urlopen(url) as r, open(part, 'wb') as f:
            for b in iter(lambda: r.read(1 << 20), b''):
                f.write(b)
                h.update(b)
                n += len(b)
        assert n == size, f'{name}: got {n} bytes, expected {size}'
        assert h.hexdigest() == sha, f'{name}: SHA-256 mismatch'
        os.replace(part, dst)
        print(f'ok       {name}')


# ----------------------------------------------------------------------------------------------------------------------
# Extraction: trajectories.parquet -> trajs.parquet (one row per picked trajectory) + actions.parquet (one row per
# tool call). Same rules as the replay that produced the examples.
# ----------------------------------------------------------------------------------------------------------------------
READ = {'cat', 'head', 'tail', 'less', 'more', 'nl', 'wc', 'bat'}
SEARCH = {'grep', 'egrep', 'fgrep', 'rg', 'ag', 'find', 'fd', 'locate', 'ack'}
DIR = {'ls', 'tree'}
WRITE = {'rm', 'mv', 'cp', 'mkdir', 'touch', 'chmod', 'ln', 'patch', 'tee'}
RUN = {'python', 'python3', 'pytest', 'pip', 'pip3', 'tox', 'make', 'nox', 'uv', 'npm', 'node', 'bash', 'sh',
       'coverage', 'mypy', 'flake8', 'black', 'ruff', 'pre-commit', 'conda', 'cargo', 'go', 'java', 'mvn', 'gradle'}
GREP_VAL = {'-e', '-f', '-A', '-B', '-C', '-m', '--max-count', '--include', '--exclude', '--exclude-dir', '-g', '--glob', '-t',
            '--type'}
HT_VAL = {'-n', '-c'}
WS = re.compile(r'/workspace/[^/\s\'"]+')
EXIT = re.compile(r'\[The command completed with exit code (-?\d+)\.\]')
EXC = re.compile(r'^\s*(?:E\s+)?([A-Za-z_][\w\.]*(?:Error|Exception|Exit|Interrupt|Failure|Warning))\b(?::\s*(.*))?$')


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def norm_path(p, cwd, root):
    if not p:
        return None
    p = p.strip().strip('\'"')
    if p.startswith('~'):
        return 'EXT:~'
    if not p.startswith('/'):
        p = os.path.join(cwd, p)
    p = os.path.normpath(p)
    if root and (p == root or p.startswith(root + '/')):
        rel = os.path.relpath(p, root)
        return rel
    p = re.sub(r'python3\.\d+', 'python3.X', p)
    return 'EXT:' + p


def norm_cmd(c, root):
    c = c.replace(root, '<R>') if root else c
    c = WS.sub('<R>', c)
    c = re.sub(r'^\s*cd\s+\S+\s*&&\s*', '', c)
    return re.sub(r'\s+', ' ', c).strip()[:300]


SPEC = [None]


def err_sig(text, root):
    SPEC[0] = None
    t = (text or '').replace(root, '<R>') if root else (text or '')
    t = WS.sub('<R>', t)
    t = EXIT.sub('', t)
    lines = [re.sub(r'[=\-]{5,}', ' ', l).strip() for l in t.splitlines()]
    lines = [l for l in lines if l]
    # drop OpenHands trailer lines
    lines = [l for l in lines if not l.startswith('[Current working directory') and not l.startswith('[Python interpreter')
             and not l.startswith('[Command finished with exit code') and not l.startswith('[Below is the output')
             and len(re.sub(r'[=\-_*#~ .s]', '', l)) > 2]
    sig, cls = None, 'other'
    for l in reversed(lines[-80:]):
        m = EXC.match(l)
        if m:
            sig = m.group(1) + (': ' + m.group(2) if m.group(2) else '')
            break
    if sig is None:
        for l in reversed(lines[-80:]):
            ll = l.lower()
            if 'command not found' in ll or 'no such file or directory' in ll or ll.startswith('fatal:') or ll.startswith('error:') \
               or re.search(r'=+ .*\b(failed|error|errors)\b.* =+', ll) or ll.startswith('failed '):
                sig = l
                break
    if sig is None:
        sig = lines[-1] if lines else '<empty>'
    s = sig
    sp = re.sub(r'(?:<R>|\.{0,2})?/[\w\.\-/<>]+', '<P>', s)
    sp = re.sub(r'0x[0-9a-fA-F]+', '<H>', sp)
    sp = re.sub(r'\d+(\.\d+)?', '<N>', sp)
    SPEC[0] = re.sub(r'\s+', ' ', sp).strip()[:160]
    s = re.sub(r'\'[^\']*\'|"[^"]*"|`[^`]*`', '<S>', s)
    s = re.sub(r'(?:<R>|\.{0,2})?/[\w\.\-/<>]+', '<P>', s)
    s = re.sub(r'0x[0-9a-fA-F]+', '<H>', s)
    s = re.sub(r'\d+(\.\d+)?', '<N>', s)
    s = re.sub(r'\s+', ' ', s).strip()[:160]
    sl = s.lower()
    if re.search(r'\b(failed|passed)\b', sl) and re.search(r'=+', sig) or sl.startswith('failed') or sl.startswith('assertionerror'):
        cls = 'test-fail'
    elif any(k in sl for k in ('command not found', 'no such file', 'modulenotfounderror', 'importerror', 'no replacement was performed',
                              'invalid `path`', 'invalid `view_range`', 'invalid `new_str`', 'is not a directory', 'permission denied',
                              'timeout', 'fatal:', 'pip', 'did not match any file')):
        cls = 'env-tooling'
    elif re.match(r'^[a-z_\.]*(syntaxerror|nameerror|attributeerror|typeerror|valueerror|keyerror|indexerror|indentationerror|runtimeerror|zerodivisionerror|notimplementederror|recursionerror|unboundlocalerror)', sl):
        cls = 'code-error'
    return s, cls


def split_segments(cmd):
    # top-level split on && || ; | (ignores quoting subtleties; good enough for verbs)
    return [s.strip() for s in re.split(r'&&|\|\||;|\||\n', cmd) if s.strip()]


def toks(seg):
    try:
        return shlex.split(seg, posix=True)
    except Exception:
        return seg.split()


def parse_bash(cmd, cwd, root):
    """returns (category, verb, keys(list), path_keys(list), new_cwd)"""
    cat, verb, keys, pkeys = 'other', '', [], []
    primary = None
    for seg in split_segments(cmd):
        t = toks(seg)
        while t and (re.match(r'^[A-Za-z_][A-Za-z0-9_]*=', t[0]) or t[0] in ('timeout', 'sudo', 'env', 'time', 'xargs')):
            t = t[1:]
            if t and re.match(r'^-?\d+[sm]?$', t[0]):
                t = t[1:]
        if not t:
            continue
        v = os.path.basename(t[0])
        if v == 'cd':
            if len(t) > 1:
                np_ = norm_path(t[1], cwd, root)
                cwd = os.path.join(root, np_) if np_ and not np_.startswith('EXT:') else (t[1] if t[1].startswith('/') else cwd)
            continue
        if primary is None:
            primary = (v, t)
            if (v in ('cat',) and ('>' in seg or '<<' in seg)) or (v == 'sed' and '-i' in t) or v == 'echo' and '>' in seg:
                cat = 'write'
            elif v in READ or (v == 'sed' and '-n' in t) or v == 'awk':
                cat = 'explore-read'
            elif v in SEARCH or (v == 'git' and len(t) > 1 and t[1] == 'grep'):
                cat = 'explore-search'
            elif v in DIR:
                cat = 'explore-dir'
            elif v == 'git' and len(t) > 1 and t[1] in ('log', 'show', 'blame'):
                cat = 'explore-git'
            elif v == 'git':
                cat = 'git-other'
            elif v in WRITE:
                cat = 'write'
            elif v in RUN or v.startswith('python') or v.startswith('./'):
                cat = 'run'
            verb = v
        # path extraction for exploration verbs (primary + piped grep/xargs grep)
        if v in READ or (v == 'sed' and '-n' in t):
            args = t[1:]
            pos, skip = [], False
            for i, a in enumerate(args):
                if skip:
                    skip = False; continue
                if v in ('head', 'tail') and a in HT_VAL:
                    skip = True; continue
                if a.startswith('-'):
                    continue
                pos.append(a)
            if v == 'sed' and pos:
                pos = pos[1:]
            for a in pos:
                if a in ('>', '<', '2>&1') or a.startswith('>'):
                    break
                p = norm_path(a, cwd, root)
                if p and primary and primary[0] == v:
                    keys.append('F:' + p)
        elif v in DIR:
            pos = [a for a in t[1:] if not a.startswith('-')] or ['.']
            if primary and primary[0] == v:
                for a in pos:
                    p = norm_path(a, cwd, root)
                    if p:
                        keys.append('D:' + p)
        elif v in SEARCH or (v == 'git' and len(t) > 1 and t[1] == 'grep'):
            args = t[2:] if v == 'git' else t[1:]
            if v in ('find', 'fd'):
                pos = []
                for a in args:
                    if a.startswith('-') or a in ('(', '!', '\\('):
                        break
                    pos.append(a)
                pos = pos or ['.']
            else:
                pos, skip, has_e = [], False, False
                for a in args:
                    if skip:
                        skip = False; continue
                    if a in GREP_VAL:
                        skip = True
                        if a == '-e':
                            has_e = True
                        continue
                    if a.startswith('-'):
                        continue
                    if a in ('2>/dev/null',) or a.startswith('>'):
                        break
                    pos.append(a)
                if not has_e and pos:
                    pos = pos[1:]
                pos = pos or ['.']
            for a in pos:
                p = norm_path(a, cwd, root)
                if p:
                    pkeys.append('P:' + p)
    if cat == 'explore-search' or cat == 'explore-git':
        keys = [('S:' if cat == 'explore-search' else 'G:') + norm_cmd(cmd, root)]
    return cat, verb, keys, pkeys, cwd


def process_traj(r):
    tr = r['trajectory']
    root = None
    m = re.search(r'<uploaded_files>\s*(/workspace/\S+?)\s*</uploaded_files>', ''.join((x.get('content') or '') for x in tr[:3]))
    if m:
        root = os.path.normpath(m.group(1))
    lens = []
    is_call = []
    for x in tr:
        c = len(x.get('content') or '')
        for tc in (x.get('tool_calls') or []):
            c += len(tc['function'].get('arguments') or '') + len(tc['function'].get('name') or '')
        lens.append(c)
        is_call.append(x['role'] == 'assistant')
    n = len(tr)
    later = [0] * n
    acc = 0
    for j in range(n - 1, -1, -1):
        later[j] = acc
        if is_call[j]:
            acc += 1
    total_flat = sum(lens)
    # uncached: each message is input to every later call; assistant messages are also output once
    total_unc = sum(lens[j] * later[j] + (lens[j] if is_call[j] else 0) for j in range(n))
    # cache-adjusted: first read at 1.0, later reads at 0.1
    total_cache = sum((lens[j] * (1 + 0.1 * (later[j] - 1)) if later[j] > 0 else 0) + (lens[j] if is_call[j] else 0) for j in range(n))
    # map tool_call_id -> obs index
    obs_by_id = {}
    for j, x in enumerate(tr):
        if x['role'] == 'tool' and x.get('tool_call_id'):
            obs_by_id[x['tool_call_id']] = j
    acts = []
    cwd = root or '/workspace'
    step = 0
    for j, x in enumerate(tr):
        if not is_call[j]:
            continue
        step += 1
        tcs = x.get('tool_calls') or []
        k = max(1, len(tcs))
        for tc in tcs:
            SPEC[0] = None
            f = tc['function']; name = f.get('name')
            try:
                a = json.loads(f.get('arguments') or '{}')
                if not isinstance(a, dict):
                    a = {}
            except Exception:
                a = {}
            oj = obs_by_id.get(tc.get('id'))
            obs = (tr[oj].get('content') or '') if oj is not None else ''
            olen = len(obs)
            ol = later[oj] if oj is not None else 0
            cat, verb, keys, pkeys = 'other', name or '', [], []
            failed, sig, scls = False, None, None
            if name == 'str_replace_editor':
                sub = a.get('command')
                verb = 'editor-' + str(sub)
                p = norm_path(a.get('path'), cwd, root) if a.get('path') else None
                if sub == 'view':
                    if obs.startswith("Here's the files and directories"):
                        cat = 'explore-dir'; keys = ['D:' + p] if p else []
                    else:
                        cat = 'explore-read'; keys = ['F:' + p] if p else []
                elif sub in ('create', 'str_replace', 'insert', 'undo_edit'):
                    cat = 'edit'; keys = ['E:' + p] if p else []
                if obs.startswith('ERROR'):
                    failed = True
                    l2 = (obs.splitlines()[1:2] or [''])[0]
                    l2 = re.split(r'(?<=parameter)|(?<=performed)|(?<=exist)', l2)[0]
                    sig, _ = err_sig(l2, root)
                    sig, scls = 'EDITOR: ' + sig[:80], 'env-tooling'
            elif name == 'execute_bash':
                cmd = a.get('command') or ''
                cat, verb, keys, pkeys, cwd = parse_bash(cmd, cwd, root)
                mc = re.search(r'\[Current working directory: (\S+)\]', obs)
                if mc:
                    cwd = os.path.normpath(mc.group(1))
                mm = EXIT.search(obs)
                code = int(mm.group(1)) if mm else None
                if code is None and a.get('is_input') not in ('true', True) and cmd and not cmd.startswith('C-'):
                    failed = True
                    sig, scls = 'NO-EXIT(timeout/interactive)', 'env-tooling'
                elif code not in (None, 0):
                    # grep/find returning 1 == "no match": record as failed-search
                    failed = True
                    if cat == 'explore-search' and len(EXIT.sub('', obs).strip()) < 300:
                        sig, scls = 'SEARCH-NO-MATCH', 'search-miss'
                    else:
                        sig, scls = err_sig(obs, root)
            elif name in ('think', 'task_tracker', 'finish'):
                cat = name
            call_len = lens[j] / k
            acts.append(dict(step=step, tool=name or '', verb=verb[:40], cat=cat, keys=keys, pkeys=pkeys,
                             obs=olen, obs_unc=olen * ol, obs_cache=(olen * (1 + 0.1 * (ol - 1)) if ol > 0 else 0),
                             call=call_len, call_unc=call_len * later[j] + call_len,
                             call_cache=(call_len * (1 + 0.1 * (later[j] - 1)) if later[j] > 0 else 0) + call_len,
                             failed=failed, sig=sig, scls=scls, sig_spec=(SPEC[0] if failed else None) or sig))
    return root, total_flat, total_unc, total_cache, step, acts


def pick_ids(src):
    t = pq.read_table(src, columns=['trajectory_id', 'instance_id', 'resolved']).to_pylist()
    by = {}
    for r in t:
        by.setdefault(r['instance_id'], []).append(r)
    P, R = set(), set()
    for iid, rs in by.items():
        rs.sort(key=lambda r: md5(r['trajectory_id']))
        P.add(rs[0]['trajectory_id'])
        res = [r for r in rs if r['resolved'] == 1]
        R.add((res[0] if res else rs[0])['trajectory_id'])
    return P, R


def work(args):
    src, rg, P, R = args
    pf = pq.ParquetFile(src)
    tb = pf.read_row_group(rg, columns=['trajectory_id', 'instance_id', 'repo', 'trajectory', 'resolved', 'model_patch'])
    trajs, acts = [], []
    for r in tb.to_pylist():
        tid = r['trajectory_id']
        if tid not in P and tid not in R:
            continue
        root, tf, tu, tcache, nsteps, A = process_traj(r)
        mp_files = sorted(set(re.findall(r'^diff --git a/(\S+) b/', r['model_patch'] or '', flags=re.M)))
        trajs.append(dict(trajectory_id=tid, instance_id=r['instance_id'], repo=r['repo'], resolved=r['resolved'],
                          pickP=tid in P, pickR=tid in R, root=root, tot_flat=tf, tot_unc=tu, tot_cache=tcache,
                          n_calls=nsteps, model_patch_files=mp_files))
        for i, a in enumerate(A):
            a['trajectory_id'] = tid; a['idx'] = i
            acts.append(a)
    return trajs, acts


def extract(D, procs=6):
    src = os.path.join(D, 'trajectories.parquet')
    P, R = pick_ids(src)
    print('picks', len(P), len(R), len(P & R), flush=True)
    nrg = pq.ParquetFile(src).metadata.num_row_groups
    T, A = [], []
    with Pool(procs) as pool:
        for trajs, acts in pool.imap_unordered(work, [(src, i, P, R) for i in range(nrg)]):
            T += trajs; A += acts
            print('row group done', len(T), len(A), flush=True)
    # imap_unordered finishes row groups in any order: sort so the output files do not depend on scheduling
    T.sort(key=lambda t: t['trajectory_id'])
    A.sort(key=lambda a: (a['trajectory_id'], a['idx']))
    pq.write_table(pa.Table.from_pylist(T), os.path.join(D, 'trajs.parquet'))
    pq.write_table(pa.Table.from_pylist(A), os.path.join(D, 'actions.parquet'))
    print('wrote', len(T), 'trajectories,', len(A), 'actions')


# ----------------------------------------------------------------------------------------------------------------------
# Pipeline steps that run the existing scripts
# ----------------------------------------------------------------------------------------------------------------------
EXAMPLES = {
    '01-ignite-confusion-matrix': dict(task='pytorch__ignite-522', builder='scripts/build_example_01.py'),
    '02-streamlink-powerapp': dict(task='streamlink__streamlink-2229', builder='examples/02-streamlink-powerapp/build_data.py'),
    '03-sqlglot-json-parse': dict(task='tobymao__sqlglot-2443', builder='examples/03-sqlglot-json-parse/build_data.py'),
}
DUMPS = ['pytorch__ignite-522', 'pytorch__ignite-484']          # read by scripts/build_example_01.py
STALENESS = [                                                   # (output file, later task, earlier tasks)
    ('stale_streamlink__streamlink-2229.json', 'streamlink__streamlink-2229', ['streamlink__streamlink-2228']),
    ('stale_streamlink__streamlink-2229_own.json', 'streamlink__streamlink-2229',
     ['streamlink__streamlink-2102', 'streamlink__streamlink-886']),
    ('stale_tobymao__sqlglot-2443_own.json', 'tobymao__sqlglot-2443', ['tobymao__sqlglot-2412']),
    ('stale_tobymao__sqlglot-2443_own_1143.json', 'tobymao__sqlglot-2443', ['tobymao__sqlglot-1143']),
]


def run_script(D, script, *args, stdout=None):
    env = dict(os.environ, SMEM_DATA=os.path.abspath(D))
    print('run', script, *args, flush=True)
    subprocess.run([sys.executable, os.path.join(ROOT, script), *args], cwd=ROOT, env=env, check=True, stdout=stdout)


def need_pandas():
    try:
        import pandas  # noqa: F401
    except ImportError:
        sys.exit('this step runs scripts that need pandas: uv run --with pyarrow --with pandas python scripts/extract_examples.py ...')


def replay(D):
    need_pandas()
    run_script(D, 'scripts/per_task_replay.py')


def dumps(D):
    need_pandas()
    run_script(D, 'scripts/dump_trajectory.py', *DUMPS, stdout=subprocess.DEVNULL)


def staleness(D):
    need_pandas()
    for out, later, earlier in STALENESS:
        tmp = os.path.join(D, out + '.tmp')
        with open(tmp, 'w') as f:
            run_script(D, 'scripts/staleness.py', later, *earlier, stdout=f)
        os.replace(tmp, os.path.join(D, out))


def build(D):
    need_pandas()
    for ex in EXAMPLES.values():
        run_script(D, ex['builder'])


# ----------------------------------------------------------------------------------------------------------------------
# Self-check (standard library + pyarrow; no network)
# ----------------------------------------------------------------------------------------------------------------------
CODE_EXT = ('.py', '.pyx', '.pxd', '.pyi', '.c', '.h', '.cc', '.cpp', '.hpp', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java',
            '.kt', '.rb', '.php', '.scala', '.cs', '.swift', '.m', '.jl', '.r', '.R', '.sql', '.lua', '.sh')

# data.json field -> per_task.parquet column, per example (the three builders use different key names)
FIELDS = {
    '01-ignite-confusion-matrix': {
        'run.trajectory_id': None, 'run.resolved': 'resolved', 'run.llm_calls': 'n_calls',
        'run.tokens_flat': 'tot_tokens_flat', 'run.tokens_cache_weighted': 'tot_tokens_cache',
        'task.base_commit': 'base_commit', 'tenancy.tenant': 'tenant',
        'len:tenancy.own_earlier_tasks': 'own_hist', 'len:tenancy.all_earlier_tasks': 'pool_hist',
        'replay.first_touch_exploration_actions': 'n_first_expl', 'replay.repeated_own_history': 'n_rep_self',
        'replay.repeated_pool': 'n_rep_pool', 'replay.removable_own_history_tok': 'removable_self_tok',
        'replay.removable_pool_tok': 'removable_pool_tok', 'replay.cross_tenant_increment_tok': 'incr_tok',
        'replay.own_history_share': 'self_share', 'replay.pool_share': 'pool_share', 'replay.increment_share': 'incr_share',
        'replay.removable_own_history_obs_flat_tok': 'removable_self_obs_flat_tok',
        'replay.removable_pool_obs_flat_tok': 'removable_pool_obs_flat_tok',
        'replay.increment_by_kind_tok.file_reads': 'incr_read_tok', 'replay.increment_by_kind_tok.directory_listings': 'incr_dir_tok',
        'replay.increment_by_kind_tok.searches': 'incr_search_tok', 'replay.increment_by_kind_tok.git': 'incr_git_tok',
    },
    '02-streamlink-powerapp': {
        'agent_run.trajectory_id': None, 'agent_run.tenant': 'tenant', 'agent_run.resolved': 'resolved',
        'agent_run.llm_calls': 'n_calls', 'agent_run.task_tokens_flat': 'tot_tokens_flat',
        'agent_run.task_tokens_cache_weighted': 'tot_tokens_cache', 'task.base_commit': 'base_commit',
        'len:history.own': 'own_hist', 'len:history.pool': 'pool_hist',
        'replay.first_touch_exploration_actions': 'n_first_expl', 'replay.repeated_from_own_history_actions': 'n_rep_self',
        'replay.repeated_from_pool_actions': 'n_rep_pool',
        'replay.removable_own_history_tokens_cache_weighted': 'removable_self_tok',
        'replay.removable_pool_tokens_cache_weighted': 'removable_pool_tok',
        'replay.cross_tenant_increment_tokens_cache_weighted': 'incr_tok',
        'replay.own_share': 'self_share', 'replay.pool_share': 'pool_share', 'replay.increment_share': 'incr_share',
        'replay.removable_own_history_obs_tokens_flat': 'removable_self_obs_flat_tok',
        'replay.removable_pool_obs_tokens_flat': 'removable_pool_obs_flat_tok',
    },
    '03-sqlglot-json-parse': {
        'agent_run.trajectory_id': None, 'agent_run.tenant': 'tenant', 'agent_run.resolved': 'resolved',
        'agent_run.llm_calls': 'n_calls', 'agent_run.task_tokens_flat': 'tot_tokens_flat',
        'agent_run.task_tokens_cache_weighted': 'tot_tokens_cache', 'task.base_commit': 'base_commit', 'task.tenant': 'tenant',
        'history.own_earlier_tasks': 'own_hist', 'history.pool_earlier_tasks': 'pool_hist',
        'replay.first_touch_exploration_actions': 'n_first_expl', 'replay.repeated_from_own_history_actions': 'n_rep_self',
        'replay.repeated_from_pool_actions': 'n_rep_pool',
        'replay.removable_own_history_tokens_cache_weighted': 'removable_self_tok',
        'replay.removable_pool_tokens_cache_weighted': 'removable_pool_tok',
        'replay.cross_tenant_increment_tokens_cache_weighted': 'incr_tok',
        'replay.own_share': 'self_share', 'replay.pool_share': 'pool_share', 'replay.increment_share': 'incr_share',
        'replay.removable_own_obs_tokens_flat': 'removable_self_obs_flat_tok',
        'replay.removable_pool_obs_tokens_flat': 'removable_pool_obs_flat_tok',
    },
}


def get(d, dotted):
    ln = dotted.startswith('len:')
    for k in dotted[4 if ln else 0:].split('.'):
        d = d[k]
    return len(d) if ln else d


def read_text(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def gold_files(patch):
    return sorted(set(re.findall(r'^diff --git a/(\S+) b/', patch or '', flags=re.M)))


def code_only(files):
    return [f for f in files if f.endswith(CODE_EXT) and not re.match(r'^(docs?|doc_src|changelog\.d|changes|news)/', f)]


def load_rebench(D, columns):
    seen, rows = set(), []
    for f in REBENCH:   # same order and de-duplication as the replay (first occurrence of an instance_id wins)
        for r in pq.read_table(os.path.join(D, f), columns=columns).to_pylist():
            if r['instance_id'] not in seen:
                seen.add(r['instance_id'])
                rows.append(r)
    return rows


def fmt_pair(tok, total):
    return f'{tok:,} ({100 * tok / total:.1f}%)'


def check_aggregates(D, pt, picked):
    """Headline numbers of the offline replay (1,179 tasks, 18 repositories, 3 round-robin tenants)."""
    assert len(pt) == 1179 and len({r['repo'] for r in pt.values()}) == 18
    total = sum(picked[i]['tot_cache'] for i in pt) / 4
    own = sum(r['removable_self_tok'] for r in pt.values()) / total
    pool = sum(r['removable_pool_tok'] for r in pt.values()) / total
    incr = sum(r['incr_tok'] for r in pt.values()) / total
    assert (round(100 * own, 2), round(100 * pool, 2), round(100 * incr, 2)) == (14.80, 18.05, 3.25), (own, pool, incr)
    print(f'ok  aggregate: own history {100 * own:.2f}% -> 3-tenant pool {100 * pool:.2f}% of all tokens '
          f'(cross-tenant increment {100 * incr:.2f} pp)')
    want = {(0, 4): (270, 8.7, 4.5), (5, 19): (601, 14.5, 3.6), (20, 10 ** 9): (308, 20.6, 1.4)}
    for (lo, hi), (n, self_pct, incr_pct) in want.items():
        x = [r for r in pt.values() if lo <= r['own_hist'] <= hi]
        tc = sum(r['tot_tokens_cache'] for r in x)
        got = (len(x), round(100 * sum(r['removable_self_tok'] for r in x) / tc, 1), round(100 * sum(r['incr_tok'] for r in x) / tc, 1))
        assert got == (n, self_pct, incr_pct), ((lo, hi), got)
        label = f'{lo}-{hi}' if hi < 10 ** 9 else f'{lo}+'
        print(f'ok  {label} own earlier tasks: n={got[0]}, own-history ceiling {got[1]}%, cross-tenant increment {got[2]}%')
    shares = [r['incr_share'] for r in pt.values()]
    med = statistics.median(shares)
    assert round(med, 4) == 0.0106 and round(sum(s > 0 for s in shares) / len(shares), 3) == 0.681, med
    print(f'ok  per-task increment: median {100 * med:.2f}%, {100 * sum(s > 0 for s in shares) / len(shares):.1f}% of tasks have any')


def check_gold_reuse(D):
    """Gold-file reuse from patches alone: SWE-rebench test split, repos with >= 30 tasks, code files, round-robin."""
    by = defaultdict(list)
    for r in load_rebench(D, ['instance_id', 'repo', 'created_at', 'patch']):
        by[r['repo']].append(r)
    rows, nrepo = [], 0
    for repo, g in by.items():
        if len(g) < 30:
            continue
        nrepo += 1
        g.sort(key=lambda r: (r['created_at'], r['instance_id']))   # created_at is uniformly 'YYYY-MM-DD HH:MM:SS'
        seen, pending = [set(), set(), set()], []
        for i, r in enumerate(g):
            while pending and g[pending[0]]['created_at'] < r['created_at']:   # history = strictly earlier tasks
                j = pending.pop(0)
                seen[j % 3].update(code_only(gold_files(g[j]['patch'])))
            G = set(code_only(gold_files(r['patch'])))
            if G:
                rows.append((bool(G & seen[i % 3]), bool(G & (seen[0] | seen[1] | seen[2]))))
            pending.append(i)
    own = sum(a for a, _ in rows) / len(rows)
    pool = sum(b for _, b in rows) / len(rows)
    assert (nrepo, len(rows), round(100 * own, 1), round(100 * pool, 1)) == (116, 8636, 68.6, 84.5), (nrepo, len(rows), own, pool)
    print(f'ok  gold-file reuse: {nrepo} repos, {len(rows):,} tasks; an earlier task edited a gold file: '
          f'own tenant {100 * own:.1f}%, any tenant {100 * pool:.1f}%')


def picked_model_patches(D, tids):
    """model_patch of the given trajectory ids, read from trajectories.parquet (None if the file is absent)."""
    src = os.path.join(D, 'trajectories.parquet')
    if not os.path.exists(src):
        return None
    pf, out = pq.ParquetFile(src), {}
    for rg in range(pf.metadata.num_row_groups):
        t = pf.read_row_group(rg, columns=['trajectory_id', 'model_patch'])
        t = t.filter(pc.is_in(t['trajectory_id'], value_set=pa.array(sorted(tids))))
        for r in t.to_pylist():
            out[r['trajectory_id']] = r['model_patch']
    return out


def check_examples(D, pt, picked, readme):
    rb = {r['instance_id']: r for r in load_rebench(D, ['instance_id', 'patch', 'test_patch'])}
    datas = {}
    for ex, spec in EXAMPLES.items():
        d = json.load(open(os.path.join(ROOT, 'examples', ex, 'data.json')))
        datas[ex] = d
        iid = spec['task']
        row = pt[iid]
        for path, col in FIELDS[ex].items():
            want = picked[iid]['trajectory_id'] if col is None else row[col]
            got = get(d, path)
            if isinstance(want, float):
                assert abs(got - want) < 5e-5, (ex, path, got, want)
            else:
                assert got == want, (ex, path, got, want)
        exdir = os.path.join(ROOT, 'examples', ex)
        assert read_text(os.path.join(exdir, 'gold.patch')) == rb[iid]['patch'], (ex, 'gold.patch')
        if os.path.exists(os.path.join(exdir, 'test.patch')):
            assert read_text(os.path.join(exdir, 'test.patch')) == rb[iid]['test_patch'], (ex, 'test.patch')
        # the overview table in the top-level README quotes these figures
        tot = row['tot_tokens_cache']
        for tok in (row['removable_self_tok'], row['removable_pool_tok'], row['incr_tok']):
            assert fmt_pair(tok, tot) in readme, (ex, fmt_pair(tok, tot))
        print(f'ok  {ex}: {len(FIELDS[ex])} data.json fields match per_task.parquet; gold/test patches match SWE-rebench; '
              f'README overview figures match')
    # the earlier task each example is built around
    assert pt['pytorch__ignite-484']['tenant'] == 'tenant-3' and datas['01-ignite-confusion-matrix']['earlier_run']['instance_id'] == 'pytorch__ignite-484'
    assert pt['streamlink__streamlink-2229']['top_src'][0] == datas['02-streamlink-powerapp']['earlier_task']['instance_id'] == 'streamlink__streamlink-2228'
    assert pt['tobymao__sqlglot-2443']['incr_tok'] == 0 and pt['tobymao__sqlglot-2443']['top_src'] == []
    # agent patches against the raw trajectories (needs trajectories.parquet)
    t01 = picked['pytorch__ignite-522']['trajectory_id']
    t02 = picked['streamlink__streamlink-2229']['trajectory_id']
    t02e = picked['streamlink__streamlink-2228']['trajectory_id']
    t03 = picked['tobymao__sqlglot-2443']['trajectory_id']
    mp = picked_model_patches(D, {t01, t02, t02e, t03})
    if mp is None:
        print('skip agent-patch check (trajectories.parquet not present)')
        return
    ex2 = os.path.join(ROOT, 'examples', '02-streamlink-powerapp')
    ex3 = os.path.join(ROOT, 'examples', '03-sqlglot-json-parse')
    assert hashlib.sha256(mp[t01].encode()).hexdigest() == datas['01-ignite-confusion-matrix']['run']['agent_patch_sha256']
    assert read_text(os.path.join(ex2, 'agent.patch')) == mp[t02]
    assert read_text(os.path.join(ex2, 'earlier-agent.patch')) == mp[t02e]
    a3 = read_text(os.path.join(ex3, 'agent.patch'))
    assert a3 and a3 in mp[t03] and a3.strip() == rb['tobymao__sqlglot-2443']['patch'].strip()
    print('ok  agent patches match the recorded trajectories (example 03: its redshift.py change equals the gold patch)')


def check_reextraction(D, pt, picked):
    """Re-run the extraction on every picked trajectory up to and including each example task, in its repository,
    and compare with actions.parquet / trajs.parquet."""
    src = os.path.join(D, 'trajectories.parquet')
    if not os.path.exists(src):
        print('skip re-extraction check (trajectories.parquet not present)')
        return
    want = set()
    for spec in EXAMPLES.values():
        tgt = pt[spec['task']]
        want |= {picked[i]['trajectory_id'] for i, r in pt.items() if r['repo'] == tgt['repo'] and r['idx'] <= tgt['idx']}
    acts = pq.read_table(os.path.join(D, 'actions.parquet'),
                         filters=[('trajectory_id', 'in', sorted(want))]).to_pylist()
    old = defaultdict(list)
    for a in acts:
        old[a['trajectory_id']].append(a)
    by_tid = {t['trajectory_id']: t for t in picked.values()}
    pf, n_traj, n_act = pq.ParquetFile(src), 0, 0
    for rg in range(pf.metadata.num_row_groups):
        t = pf.read_row_group(rg, columns=['trajectory_id'])
        mask = pc.is_in(t['trajectory_id'], value_set=pa.array(sorted(want)))
        if not pc.any(mask).as_py():
            continue
        tb = pf.read_row_group(rg, columns=['trajectory_id', 'trajectory']).filter(mask)
        for r in tb.to_pylist():
            root, tf, tu, tcache, nsteps, A = process_traj(r)
            tr = by_tid[r['trajectory_id']]
            assert (root, tf, tu, nsteps) == (tr['root'], tr['tot_flat'], tr['tot_unc'], tr['n_calls'])
            assert abs(tcache - tr['tot_cache']) < 1e-6
            O = sorted(old[r['trajectory_id']], key=lambda a: a['idx'])
            assert len(O) == len(A), (r['trajectory_id'], len(O), len(A))
            for i, (a, o) in enumerate(zip(A, O)):
                assert o['idx'] == i
                for k, v in a.items():
                    if isinstance(v, float):
                        assert abs(v - o[k]) < 1e-6, (r['trajectory_id'], i, k)
                    else:
                        assert v == o[k], (r['trajectory_id'], i, k, v, o[k])
            n_traj += 1
            n_act += len(A)
    assert n_traj == len(want), (n_traj, len(want))
    print(f'ok  re-extraction: {n_traj} trajectories, {n_act:,} tool calls identical to actions.parquet / trajs.parquet')


def check_hygiene():
    """No absolute local paths in the files of this repository."""
    bad = re.compile(r'/(?:Users|home)/[A-Za-z]|(?<![\w.])/' + r'tmp/|(?<![\w$])~' + r'/')   # split so this line does not match itself
    hits = []
    for dp, dns, fns in os.walk(ROOT):
        dns[:] = [x for x in dns if x not in ('.git', 'data', '__pycache__')]
        for fn in fns:
            p = os.path.join(dp, fn)
            try:
                txt = read_text(p)
            except UnicodeDecodeError:
                continue
            for n, line in enumerate(txt.splitlines(), 1):
                if bad.search(line):
                    hits.append(f'{os.path.relpath(p, ROOT)}:{n}')
    assert not hits, hits
    print('ok  no absolute local paths in the repository files')


def check(D):
    for f in REBENCH + ['trajs.parquet', 'actions.parquet', 'per_task.parquet']:
        assert os.path.exists(os.path.join(D, f)), f'missing {f} in {D}: run download / extract / replay first'
    pt = {}
    for r in pq.read_table(os.path.join(D, 'per_task.parquet')).to_pylist():
        pt[r['instance_id']] = r
    picked = {t['instance_id']: t for t in pq.read_table(os.path.join(D, 'trajs.parquet')).to_pylist() if t['pickP']}
    if os.path.exists(os.path.join(D, 'trajectories.parquet')):
        # pickP really is the lowest md5(trajectory_id) of each instance
        t = pq.read_table(os.path.join(D, 'trajectories.parquet'), columns=['trajectory_id', 'instance_id']).to_pylist()
        best = {}
        for r in t:
            if r['instance_id'] not in best or md5(r['trajectory_id']) < md5(best[r['instance_id']]):
                best[r['instance_id']] = r['trajectory_id']
        assert len(t) == 67074 and len(best) == 6306 == len(picked)
        assert all(best[i] == p['trajectory_id'] for i, p in picked.items())
        print(f'ok  pick: {len(picked):,} instances, each with its lowest-md5 trajectory (of {len(t):,})')
    readme = read_text(os.path.join(ROOT, 'README.md'))
    check_aggregates(D, pt, picked)
    check_gold_reuse(D)
    check_examples(D, pt, picked, readme)
    check_reextraction(D, pt, picked)
    check_hygiene()
    print('self-check passed')


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('step', choices=['download', 'extract', 'replay', 'dumps', 'staleness', 'build', 'check', 'all'])
    ap.add_argument('--data', default=os.environ.get('SMEM_DATA', os.path.join(ROOT, 'data')))
    ap.add_argument('--verify', action='store_true', help='download: also verify the SHA-256 of files already present')
    ap.add_argument('--procs', type=int, default=6, help='extract: worker processes')
    a = ap.parse_args()
    D = a.data
    if a.step == 'download':
        download(D, a.verify)
    elif a.step == 'extract':
        extract(D, a.procs)
    elif a.step == 'check':
        check(D)
    elif a.step == 'all':
        extract(D, a.procs)
        replay(D)
        dumps(D)
        staleness(D)
        build(D)
        check(D)
    else:
        globals()[a.step](D)


if __name__ == '__main__':
    main()
