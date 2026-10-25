"""Vergleich der mehrdimensionalen Bewertung gegen die Keyword-Baseline (P0a).

Misst auf den **harten Eignungs-Labels** (``eval/labels.csv`` + inhaltliche
Verwürfe), ob die sieben Dimensionen die Klassen besser trennen als der
bestehende Keyword-Fit (Baseline AUC 0,715). Solange das nicht der Fall ist,
bleiben die Dimensionen *berichtend* (ADR-031) — dieses Skript liefert die
Zahlen für diese Entscheidung, keine Meinung.

Nutzung:
    python -m eval.run_dimensions_eval --profile <Profil-Datenbank.json>
    python -m eval.run_dimensions_eval --profile ... --out eval/dimensions-report.md

``--state`` zeigt standardmäßig auf ``data/state.json`` (bzw.
``BEWERBUNGSAGENT_STATE``); ``--config`` liest die Gewichte/K.O.-Schwellen aus
der echten ``config.json``, sonst gelten die Defaults aus ``dimensions.py``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval import labels as L
from eval import metrics as M

from bewerbungsagent.dimensions import score_dimensions
from bewerbungsagent.matching import score_job
from bewerbungsagent.profile import Profile

DEFAULT_STATE = Path(os.environ.get(
    "BEWERBUNGSAGENT_STATE",
    Path(__file__).resolve().parent.parent / "data" / "state.json",
))
MIN_LABELS_WARN = 30

_DIM_LABELS = {
    "kompetenz": "Fachliche Kompetenz",
    "aufgaben": "Aufgaben/Tätigkeiten",
    "senioritaet": "Seniorität/Verantwortung",
    "technologie": "Technologie/Branche",
    "gehalt": "Gehalt",
    "arbeitsmodell": "Arbeitsmodell/Standort",
    "entwicklung": "Entwicklungspotenzial",
}


def _auc(pairs: list[tuple[float, bool]]) -> float:
    return M.roc_auc(pairs) if pairs and any(lab for _, lab in pairs) \
        and any(not lab for _, lab in pairs) else float("nan")


def _pct(x: float) -> str:
    return "—" if x != x else f"{x * 100:.1f} %"


def evaluate(state_path: Path, profile_path: Path, labels_path: Path,
             config_path: Path | None = None) -> dict:
    apps = L.load_state(state_path)
    profile = Profile.load(profile_path)
    manual = L.load_manual_labels(labels_path)
    dataset = L.build_dataset(apps, manual)
    by_key = {L.entry_key(a): a for a in apps}
    cfg = {}
    if config_path and config_path.exists():
        cfg = json.loads(config_path.read_text(encoding="utf-8"))

    rows = []
    missing = 0
    for entry in dataset:
        app = by_key.get(entry.key)
        if app is None:
            missing += 1
            continue
        dims = score_dimensions(profile, app, config=cfg)
        rows.append({
            "key": entry.key,
            "firma": entry.firma,
            "titel": entry.titel,
            "label": entry.label,
            "source": entry.source,
            "fit_stored": entry.score,
            "fit_fresh": score_job(profile, app)["score"],
            "dims": dims,
        })

    manual_rows = [r for r in rows if r["source"] == "manual"]
    app_keys = set(by_key)
    orphan_labels = sorted(k for k in manual if k not in app_keys)
    models = {
        "Keyword-Fit (gespeichert)": lambda r: r["fit_stored"],
        "Keyword-Fit (frisch)": lambda r: r["fit_fresh"],
        "Dimensionen gesamt": lambda r: r["dims"]["gesamt"],
    }
    for dim in _DIM_LABELS:
        models[f"Dimension: {_DIM_LABELS[dim]}"] = (lambda d: lambda r: r["dims"]["werte"].get(d, 0))(dim)

    def auc_table(subset: list[dict]) -> dict[str, float]:
        return {name: _auc([(fn(r), r["label"]) for r in subset])
                for name, fn in models.items()}

    return {
        "dataset_size": len(rows),
        "manual_count": len(manual_rows),
        "positives": sum(1 for r in rows if r["label"]),
        "negatives": sum(1 for r in rows if not r["label"]),
        "manual_positives": sum(1 for r in rows if r["label"] and r["source"] == "manual"),
        "manual_negatives": sum(1 for r in rows if not r["label"] and r["source"] == "manual"),
        "auc_manual": auc_table(manual_rows),
        "auc_all": auc_table(rows),
        "missing_apps": missing,
        "orphan_labels": orphan_labels,
        "ko_count": sum(1 for r in rows if r["dims"]["blockiert"]),
        "ko_in_manual": sum(1 for r in manual_rows if r["dims"]["blockiert"]),
        "ko_reasons": sorted({k.get("grund") for r in rows
                              for k in (r["dims"].get("ko") or []) if k.get("grund")}),
        "rows": rows,
    }


def render_report(res: dict, weights: dict) -> str:
    now = datetime.now().isoformat(timespec="seconds")
    out: list[str] = []
    out.append("# Mehrdimensionale Bewertung vs. Keyword-Baseline\n")
    out.append(f"_Erzeugt: {now}_\n")
    out.append("## 1. Datensatz\n")
    out.append(f"- Gelabelte Fälle: **{res['dataset_size']}** "
               f"({res['positives']} passend / {res['negatives']} nicht passend)")
    out.append(f"- Davon **manuelle Eignungsurteile**: {res['manual_count']} "
               f"({res['manual_positives']} / {res['manual_negatives']})")
    if res["missing_apps"]:
        out.append(f"- Labels ohne passenden Bestandseintrag: {res['missing_apps']}")
    if res.get("orphan_labels"):
        out.append(f"- **Verwaiste Labels** (Stelle nicht mehr im Bestand): "
                   f"{len(res['orphan_labels'])} von {res['manual_count'] + len(res['orphan_labels'])} "
                   f"manuellen Labels")
        out.append("  " + ", ".join(res["orphan_labels"][:5])
                   + (" …" if len(res["orphan_labels"]) > 5 else ""))
    out.append("")
    out.append("## 2. AUC je Modell\n")
    out.append("| Modell | AUC (nur manuelle Labels) | AUC (alle Labels) |")
    out.append("|---|---:|---:|")
    for name in res["auc_manual"]:
        out.append(f"| {name} | {_pct(res['auc_manual'][name])} | "
                   f"{_pct(res['auc_all'][name])} |")
    out.append("")
    out.append("## 3. Gewichte dieser Auswertung\n")
    out.append("| Dimension | Gewicht |")
    out.append("|---|---:|")
    for dim, weight in weights.items():
        out.append(f"| {_DIM_LABELS.get(dim, dim)} | {weight * 100:.0f} % |")
    out.append("")
    out.append("## 4. K.O.-Treffer\n")
    out.append(f"- Stellen mit K.O. im Datensatz: **{res['ko_count']}** "
               f"(davon {res['ko_in_manual']} mit manuellem Label)")
    if res["ko_reasons"]:
        out.append(f"- Gründe: {', '.join(res['ko_reasons'])}")
    out.append("")
    out.append("## 5. Interpretation\n")
    base = res["auc_manual"].get("Keyword-Fit (frisch)", float("nan"))
    comp = res["auc_manual"].get("Dimensionen gesamt", float("nan"))
    if res["manual_count"] < MIN_LABELS_WARN:
        out.append(f"> ⚠️ **Vorläufig:** nur {res['manual_count']} manuelle Labels "
                   f"(Empfehlung ≥ {MIN_LABELS_WARN}). Die Rangfolge der Modelle ist "
                   "ein Hinweis, keine Entscheidungsgrundlage.")
        out.append("")
    if comp != comp or base != base:
        out.append("- Für einen Vergleich fehlen Labels beider Klassen.")
    elif comp >= base + 0.02:
        out.append(f"- Die Dimensionen trennen **besser** als der Keyword-Fit "
                   f"({_pct(comp)} vs. {_pct(base)}). Vor einer Umstellung: Labels "
                   "auf ≥ 50 je Klasse erweitern und den Abstand bestätigen.")
    elif comp <= base - 0.02:
        out.append(f"- Die Dimensionen trennen **schlechter** als der Keyword-Fit "
                   f"({_pct(comp)} vs. {_pct(base)}). Sie bleiben berichtend.")
    else:
        out.append(f"- Kein belastbarer Unterschied ({_pct(comp)} vs. {_pct(base)}). "
                   "Die Dimensionen bleiben berichtend (ADR-031).")
    out.append("- Der Keyword-Fit bleibt der entscheidende Score, bis dieser "
               "Vergleich auf ausreichend Labels einen Vorsprung zeigt.")
    out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Mehrdimensionale Bewertung gegen die Keyword-Baseline messen")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--profile", type=Path, required=True,
                    help="Pfad zur Profil-Datenbank.json")
    ap.add_argument("--labels", type=Path, default=L.DEFAULT_LABELS_CSV)
    ap.add_argument("--config", type=Path, default=None,
                    help="config.json für Gewichte/K.O.-Schwellen (optional)")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    if not args.state.exists():
        print(f"FEHLER: state.json nicht gefunden: {args.state}", file=sys.stderr)
        return 1
    if not args.profile.exists():
        print(f"FEHLER: Profil nicht gefunden: {args.profile}", file=sys.stderr)
        return 1

    res = evaluate(args.state, args.profile, args.labels, args.config)
    from bewerbungsagent.dimensions import options
    cfg = json.loads(args.config.read_text(encoding="utf-8")) if args.config and args.config.exists() else {}
    report = render_report(res, options(cfg)["gewichte"])

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"Report geschrieben: {args.out}")
    else:
        print(report)
    print(f"{res['dataset_size']} gelabelt ({res['manual_count']} manuell) · "
          f"AUC manuell: Keyword {_pct(res['auc_manual'].get('Keyword-Fit (frisch)', float('nan')))} · "
          f"Dimensionen {_pct(res['auc_manual'].get('Dimensionen gesamt', float('nan')))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
