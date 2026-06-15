import json, sys, glob, os
from collections import Counter

UNIVERSE_SIZE = 766

def universe():
    """完整 766 狀態空間:(0,⊥) + occ 1..255 × {low,mid,high}。"""
    u = {(0, "⊥")}
    for o in range(1, 256):
        for l in ("low", "mid", "high"):
            u.add((o, l))
    return u

def load_visited(path):
    """從 records 或 dump 檔取出 (occ, L) 集合(自動去重)。"""
    d = json.load(open(path))
    recs = d["visited"] if isinstance(d, dict) and "visited" in d else d
    out = set()
    for r in recs:
        out.add((r[1], r[2]) if len(r) == 3 else (r[0], r[1]))  # [step,occ,L] 或 [occ,L]
    return out

def main(paths):
    sets = {os.path.basename(p): load_visited(p) for p in paths}
    if not sets:
        print("找不到輸入檔。"); return

    U = set().union(*sets.values())          # ← 核心:聯集去重
    cnt = Counter()
    for s in sets.values():
        cnt.update(s)
    hk = Counter(cnt.values())               # 每節點被幾個檔走到
    gap = universe() - U
    n = len(sets)
    total = sum(len(s) for s in sets.values())

    print("每個 seed 的 distinct:")
    for name, s in sets.items():
        print(f"  {name:<30} {len(s):>4}")
    print(f"  {'(相加,含重複)':<30} {total:>4}")
    print()
    print(f"UNION         = {len(U)} / {UNIVERSE_SIZE} = {len(U)/UNIVERSE_SIZE*100:.1f}%")
    print(f"gap (未覆蓋)   = {len(gap)}")
    print(f"重疊(相加−聯集) = {total - len(U)}")
    print(f"frontier(k=1)  = {hk[1]}      core(k={n})  = {hk[n]}")
    print(f"hit-by-k       = {dict(sorted(hk.items()))}")
    if gap:
        print(f"\n未覆蓋的 {len(gap)} 個節點 (occ, L):")
        for o, l in sorted(gap, key=lambda t: (bin(t[0]).count('1'), t[0])):
            print(f"  O={o:08b} ({o:>3})  L={l}")

if __name__ == "__main__":
    args = sys.argv[1:]
    if not args:
        args = sorted(glob.glob("docs/algo_validation/coverage_canonical/traj_records_*.json"))
    main(args)