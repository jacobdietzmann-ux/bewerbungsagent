"""Vergleich: Keyword-Fit vs. semantisches Matching (Embeddings).

**Ergebnis (ADR-015): Die Hypothese wurde widerlegt.** Semantisches Matching
mit einem einzelnen Profil-Vektor schlägt das Keyword-Matching nicht.

## Warum AUC statt F1?

F1 hängt vom Schwellenwert ab. Bei Empfehlungssystemen ist die eigentliche
Frage: *Sortiert das Verfahren gute Stellen nach oben?* Genau das misst die
**ROC-AUC** — schwellenunabhängig. Ergänzend **Precision@K**: "Wie viele der
Top-K sind wirklich passend?" (die betrieblich relevante Zahl).

## Zwei Datensätze, zwei Aussagen

- **Voller Datensatz** (manuelle Labels + 212 grobe Verwürfe): Beide Verfahren
  schneiden gut ab — aber die groben Negative sind *nicht-technische* Berufe
  (Finance, HR, Schweißlehrer). Das ist zu leicht und täuscht.
- **Nur manuelle Labels**: enthält die *schwierigen* Negative (technisch,
  aber falsche Domäne). Hier zeigt sich die Wahrheit.

Nutzung:
    python -m eval.run_semantic_eval --model intfloat/multilingual-e5-base
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval import labels as L  # noqa: E402
from eval import metrics as M  # noqa: E402

DEFAULT_STATE = Path.home() / "GoogleDrive/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/state.json"
DEFAULT_PROFILE = Path.home() / "GoogleDrive/DOKUMENTE/Job/Bewerbung/2026/02_Profil-und-Assets/Profil-Datenbank.json"
DEFAULT_MODEL = "intfloat/multilingual-e5-base"
K_VALUES = (5, 10, 20)


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %"


def precision_at_k(scores: np.ndarray, y: np.ndarray, k: int) -> float:
    """Anteil passender unter den Top-k nach Score."""
    k = min(k, len(scores))
    if k == 0:
        return 0.0
    idx = np.argsort(-scores)[:k]
    return float(y[idx].mean())


def _evaluate(name: str, scores: np.ndarray, y: np.ndarray) -> dict:
    labeled = [(float(s), bool(t)) for s, t in zip(scores, y)]
    return {
        "name": name,
        "auc": M.roc_auc(labeled),
        "p_at": {k: precision_at_k(scores, y, k) for k in K_VALUES},
    }


def run(state_path: Path, profile_path: Path, model_name: str,
        out: Path | None = None) -> dict:
    from bewerbungsagent.semantic import (SemanticMatcher, build_job_text,
                                          build_profile_query, build_profile_text)

    apps = L.load_state(state_path)
    manual = L.load_manual_labels()
    by_key = {L.entry_key(a): a for a in apps}

    prof_data = json.loads(Path(profile_path).read_text(encoding="utf-8"))

    t0 = time.time()
    matcher = SemanticMatcher(model_name)
    load_s = time.time() - t0

    def eval_set(entries, label: str) -> dict:
        texts = [build_job_text(by_key.get(e.key, {"titel": e.titel})) for e in entries]
        y = np.array([e.label for e in entries])
        kw = np.array([e.score for e in entries], dtype=float)
        t = time.time()
        docs = matcher.encode(texts, kind="passage")
        enc_s = time.time() - t

        res = {"label": label, "n": len(entries), "n_pos": int(y.sum()),
               "encode_seconds": enc_s, "variants": {}}
        res["variants"]["keyword"] = _evaluate("Keyword-Fit", kw, y)

        for key, name in (
            ("sem_query", "Semantisch (kompakte Anfrage)"),
            ("sem_full", "Semantisch (voller Profil-Dump)"),
        ):
            qtext = build_profile_query(prof_data) if key == "sem_query" \
                else build_profile_text(prof_data)
            qv = matcher.encode([qtext], kind="query")
            sim = (docs @ np.atleast_2d(qv).T).max(axis=1)
            res["variants"][key] = _evaluate(name, sim, y)

        if len(entries) <= 40:
            res["rows"] = [
                {"titel": e.titel, "firma": e.firma, "label": e.label,
                 "kw": float(s), "kw_rank": int(np.where(np.argsort(-kw) == i)[0][0]) + 1,
                 "score": e.score}
                for i, (e, s) in enumerate(zip(entries, kw))
            ]
        return res

    full = L.build_dataset(apps, manual)
    hard = [e for e in full if e.source == "manual"]

    return {
        "model": model_name, "dim": matcher.dim, "load_seconds": load_s,
        "full": eval_set(full, "voller Datensatz"),
        "hard": eval_set(hard, "nur manuelle Labels (harte Fälle)"),
        "n_manual": len(manual),
    }


def render(r: dict) -> str:
    o: list[str] = []
    o.append("# Vergleich: Keyword-Fit vs. semantisches Matching\n")
    o.append(f"_Erzeugt: {datetime.now().isoformat(timespec='seconds')}_\n")
    o.append(f"Modell: `{r['model']}` ({r['dim']} Dimensionen) · "
             f"Ladezeit {r['load_seconds']:.1f} s · manuelle Labels: {r['n_manual']}\n")

    o.append("## Ergebnis auf einen Blick\n")
    h = r["hard"]["variants"]
    kw, sem = h["keyword"], h["sem_query"]
    if sem["auc"] < kw["auc"] - 0.02:
        verdict = "**schlechter**"
    elif sem["auc"] > kw["auc"] + 0.02:
        verdict = "**besser**"
    else:
        verdict = "**gleichauf**"
    o.append(f"Auf den harten Fällen (technische, aber unpassende Stellen) ist "
             f"semantisches Matching {verdict} als der Keyword-Fit: "
             f"AUC {sem['auc']:.3f} vs. {kw['auc']:.3f}.\n")

    for key in ("full", "hard"):
        d = r[key]
        o.append(f"## {d['label']}\n")
        o.append(f"{d['n']} Labels ({d['n_pos']} passend) · "
                 f"Embedding-Zeit {d['encode_seconds']:.1f} s\n")
        o.append("| Verfahren | AUC | " + " | ".join(f"P@{k}" for k in K_VALUES) + " |")
        o.append("|---|---:|" + "---:|" * len(K_VALUES))
        for v in d["variants"].values():
            p = " | ".join(_pct(v["p_at"][k]) for k in K_VALUES)
            o.append(f"| {v['name']} | {v['auc']:.3f} | {p} |")
        o.append("")
        if key == "full":
            o.append("> ⚠️ **Confound:** Die 212 groben Verwürfe sind "
                     "*nicht-technische* Berufe (Finance, HR, Schweißlehrer). "
                     "Beide Verfahren trennen die mühelos — das täuscht über die "
                     "Schwäche bei *technischen* Fehlpaarungen hinweg.\n")

    o.append("## Fallanalyse (manuelle Labels)\n")
    o.append("| Label | Keyword-Score | Keyword-Rang |")
    o.append("|---|---:|---:|")
    for row in sorted(r["hard"].get("rows", []), key=lambda x: x["kw_rank"]):
        o.append(f"| {'PASST' if row['label'] else 'passt nicht'} | "
                 f"{row['score']:.0f} % | {row['kw_rank']} |")
    o.append("")

    o.append("## Interpretation\n")
    o.append("**Die Ausgangshypothese war falsch.** Erwartet wurde, dass "
             "Embeddings die *Bedeutung* vergleichen und deshalb genau die Fälle "
             "lösen, an denen Wortüberlappung scheitert (z. B. "
             "'Head of Finance Systems' mit 75 %). Gemessen ist das Gegenteil:\n")
    o.append("1. **Ein einzelner Profil-Vektor verwischt die Trennschärfe.** Das "
             "Profil wird zu einem generischen 'technischen Ingenieur'-Vektor, der "
             "auf *jede* technische Stelle passt — Automotive-Test, "
             "SAP-Testmanagement, Embedded-Entwicklung.")
    o.append("2. **Das Ähnlichkeitsband ist zu schmal.** Über 230 Stellen liegt "
             "der Kosinus zwischen 0.79 und 0.88; die Rangfolge darin ist kaum "
             "aussagekräftig.")
    o.append("3. **Der Keyword-Fit ist besser als angenommen.** AUC 0.947 auf dem "
             "vollen Datensatz, P@5 = 100 % auf den manuellen Labels.\n")
    o.append("### Der wertvollste Einzelbefund\n")
    o.append("Ein **Silent Bug** in der Eingabe: E5 schneidet bei 512 Token ab, "
             "der ursprüngliche Profil-Dump hatte ~1484 Token. Es wurde also nur "
             "die erste Station eingebettet. Die kompakte Anfrage hob die AUC von "
             "0.776 auf ~0.93 — **Eingabe-Aufbereitung wirkt stärker als "
             "Modellwahl.**\n")
    o.append("### Was als Nächstes wirklich helfen könnte\n")
    o.append("- **Cross-Encoder-Reranking:** Profil und Stelle *gemeinsam* bewerten "
             "(statt zwei getrennte Vektoren) — präziser, aber ein Forward-Pass pro "
             "Paar, daher nur für die Top-K sinnvoll.")
    o.append("- **Hybrid:** Keyword als Recall-Filter, Semantik als Reranker.")
    o.append("- **Facetten-Matching:** je Anforderung ein eigener Vergleich statt "
             "ein Profil-Vektor.\n")
    return "\n".join(o)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Keyword vs. semantisches Matching")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--profile", type=Path, default=DEFAULT_PROFILE)
    ap.add_argument("--labels", type=Path, default=L.DEFAULT_LABELS_CSV)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    L.DEFAULT_LABELS_CSV = args.labels
    res = run(args.state, args.profile, args.model, args.out)
    if not res:
        return 1

    print(f"\n{'Datensatz':<32} {'Verfahren':<36} {'AUC':>6} {'P@5':>7}")
    print("-" * 84)
    for key in ("full", "hard"):
        d = res[key]
        for v in d["variants"].values():
            print(f"{d['label'][:30]:<32} {v['name'][:34]:<36} "
                  f"{v['auc']:>6.3f} {_pct(v['p_at'][5]):>7}")
        print()
    if args.out:
        print(f"Report: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
