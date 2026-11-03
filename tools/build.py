"""Convierte el corpus OpenScore Lieder (MuseScore, CC0) a PDF y escribe catalog.tsv para YomiScore.

Uso (lo lanza el flujo de GitHub Actions):
    python tools/build.py --lieder <clon de OpenScore/Lieder> --mscore <ejecutable de MuseScore 3> --out .

- Solo convierte lo que falta o cambió (compara el hash del .mscx con el guardado en state.tsv).
- Convierte en tandas: si MuseScore se cae en una obra, las demás de la tanda se reintentan una a una.
- catalog.tsv solo lista obras cuyo PDF existe de verdad (empieza por %PDF-).
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time

BATCH = 40
TIMEOUT_BATCH = 900
TIMEOUT_ONE = 180


def read_yaml(path):
    """Lector mínimo del YAML de OpenScore (StrictYAML de dos niveles: id → clave: valor)."""
    out, current = {}, None
    with open(path, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if not line.startswith(" "):
                key = line.split(":", 1)[0].strip().strip("'\"")
                current = out.setdefault(key, {})
            elif current is not None and ":" in line:
                k, v = line.strip().split(":", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                    v = v[1:-1]
                current[k.strip()] = v
    return out


def song_title(segment):
    """«01_Gute_Nacht» → «Gute Nacht»; «3a_Liebe» → «Liebe»."""
    s = re.sub(r"^\d+[a-z]?_", "", segment).replace("_", " ").strip()
    return s or segment.replace("_", " ")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_pdf(path):
    try:
        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"
    except OSError:
        return False


def run_job(mscore, pairs, timeout):
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as j:
        json.dump([{"in": i, "out": o} for i, o in pairs], j)
        job = j.name
    try:
        subprocess.run(shlex.split(mscore) + ["-j", job], timeout=timeout, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        print(f"  tanda agotada ({len(pairs)} obras)", flush=True)
    finally:
        os.unlink(job)


def probe(mscore, src, dst):
    """Convierte la primera a la vista: si MuseScore no funciona, lo dice (anotación pública) y se para ya."""
    try:
        r = subprocess.run(shlex.split(mscore) + ["-o", dst, src], timeout=TIMEOUT_ONE, capture_output=True, text=True)
        out = (r.stdout + "\n" + r.stderr).strip()
    except (subprocess.TimeoutExpired, OSError) as e:
        out = repr(e)
    if is_pdf(dst):
        print("MuseScore convierte bien", flush=True)
        return True
    tail = " | ".join(line.strip() for line in out.splitlines()[-12:] if line.strip())
    print(f"::error title=MuseScore no convierte::{tail[:3000] or 'sin salida'}", flush=True)
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lieder", required=True)
    ap.add_argument("--mscore", required=True)
    ap.add_argument("--out", default=".")
    ap.add_argument("--limit", type=int, default=0, help="solo las N primeras (pruebas)")
    a = ap.parse_args()

    data = os.path.join(a.lieder, "data")
    scores = read_yaml(os.path.join(data, "scores.yaml"))
    sets = read_yaml(os.path.join(data, "sets.yaml"))
    composers = read_yaml(os.path.join(data, "composers.yaml"))
    composers_by_path = {c.get("path"): c for c in composers.values()}

    state_path = os.path.join(a.out, "state.tsv")
    state = {}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as f:
            for line in f.read().splitlines()[1:]:
                parts = line.split("\t")
                if len(parts) == 2:
                    state[parts[0]] = parts[1]

    rows, todo = [], []
    for sid, s in scores.items():
        path = s.get("path", "")
        if not sid.isdigit() or path.count("/") != 2 or ".." in path:
            continue
        src = os.path.join(a.lieder, "scores", *path.split("/"), f"lc{sid}.mscx")
        if not os.path.exists(src):
            continue
        dst = os.path.join(a.out, "scores", *path.split("/"), f"lc{sid}.pdf")
        digest = sha(src)
        rows.append((sid, s, path, src, dst, digest))
        if state.get(sid) != digest or not is_pdf(dst):
            todo.append((src, dst))
        if a.limit and len(rows) >= a.limit:
            break

    print(f"{len(rows)} canciones · {len(todo)} por convertir", flush=True)
    for _, dst in todo:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
    if todo and not probe(a.mscore, *todo[0]):
        return 1
    start = time.time()
    for i in range(0, len(todo), BATCH):
        batch = todo[i:i + BATCH]
        run_job(a.mscore, batch, TIMEOUT_BATCH)
        missing = [(s, d) for s, d in batch if not is_pdf(d)]
        for pair in missing:  # una a una: la que tumba a MuseScore no se lleva a las demás
            run_job(a.mscore, [pair], TIMEOUT_ONE)
        print(f"  {min(i + BATCH, len(todo))}/{len(todo)} · {int(time.time() - start)} s", flush=True)

    cols = ["id", "path", "title", "set", "number", "composer", "born", "died", "lyricist", "language",
            "instruments", "link", "pdf"]
    ok = 0
    with open(os.path.join(a.out, "catalog.tsv"), "w", encoding="utf-8", newline="\n") as cat, \
            open(state_path, "w", encoding="utf-8", newline="\n") as st:
        cat.write("\t".join(cols) + "\n")
        st.write("id\tsha256\n")
        for sid, s, path, src, dst, digest in rows:
            if not is_pdf(dst):
                continue
            composer_path, set_seg, song_seg = path.split("/")
            the_set = sets.get(s.get("set_id", ""), {})
            set_name = "" if set_seg == "_" else the_set.get("name", set_seg.replace("_", " "))
            c = composers_by_path.get(composer_path, {})
            row = {
                "id": sid, "path": path, "title": song_title(song_seg), "set": set_name,
                "number": s.get("number", ""), "composer": c.get("name", composer_path.replace("_", " ")),
                "born": c.get("born", ""), "died": c.get("died", ""), "lyricist": s.get("lyricist", ""),
                "language": s.get("language", ""), "instruments": s.get("instruments", "Voice, Piano"),
                "link": f"https://musescore.com/openscore-lieder-corpus/scores/{sid}",
                "pdf": f"scores/{path}/lc{sid}.pdf",
            }
            cat.write("\t".join(str(row[k]).replace("\t", " ").replace("\n", " ") for k in cols) + "\n")
            st.write(f"{sid}\t{digest}\n")
            ok += 1
    print(f"catálogo: {ok} de {len(rows)} con PDF", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
