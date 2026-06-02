"""
build_rankings.py — build pbr_rankings.pkl from PBR JSON exports.

A file is classified as 'national' if its name contains 'National',
otherwise it's treated as a state file. Keys are name (lowercased,
suffix-stripped) → {rank, name, class, state, commit}.

Usage:
    from build_rankings import build_from_files
    build_from_files(['/path/to/national.json', '/path/to/state.json', ...],
                     out_path='/path/to/pbr_rankings.pkl')
"""
import json, pickle, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db_loader import strip_suffix


def _entry(p):
    return {
        'rank':   p.get('rank'),
        'name':   p.get('name', ''),
        'class':  str(p.get('class', '')),
        'state':  p.get('state', ''),
        'commit': p.get('commitment', '') or p.get('commit', ''),
    }


def build_from_files(file_paths, out_path):
    national = {}
    state_rnks = {}
    n_files = 0
    n_state_files = 0

    for fp in file_paths:
        if not os.path.exists(fp):
            print(f"[BUILD] skip (not found): {fp}")
            continue
        with open(fp) as f:
            data = json.load(f)
        is_nat = 'National' in os.path.basename(fp)
        bucket = national if is_nat else state_rnks
        for p in data.get('players', []):
            name = p.get('name', '').strip()
            if not name:
                continue
            key = strip_suffix(name.lower())
            bucket[key] = _entry(p)
        n_files += 1
        if not is_nat:
            n_state_files += 1
        print(f"[BUILD] loaded {len(data.get('players',[]))} from "
              f"{'NATIONAL' if is_nat else 'STATE'}: {os.path.basename(fp)}")

    out = {'national': national, 'state_rnks': state_rnks}
    with open(out_path, 'wb') as f:
        pickle.dump(out, f)
    print(f"[BUILD] Done -> {out_path}")
    print(f"[BUILD] {len(national)} national + {len(state_rnks)} state rankings "
          f"({n_files} files, {n_state_files} state)")
    return out


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: build_rankings.py <out.pkl> <file1.json> [file2.json ...]")
        sys.exit(1)
    build_from_files(sys.argv[2:], sys.argv[1])
