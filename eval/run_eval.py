"""Offline-Evaluation des Fit-Scorings gegen **manuelle Eignungs-Labels**.

Wichtig: Der ``status`` im Bestand ist ein *Prozess*-Signal und **kein**
Eignungsmaß (siehe ``docs/DECISIONS.md`` → ADR-012). Diese Evaluation nutzt
deshalb ausschließlich:

1. manuell gesetzte Labels (``eval/labels.csv``, via ``eval/label_tool.py``),
2. optional grobe Negative aus „Nicht passende Rolle"-Verwürfen.

Ohne manuelle Labels ist **kein** belastbares Ergebnis möglich — das Skript
sagt das dann deutlich.

Nutzung:
    python -m eval.label_tool                 # zuerst Labels setzen
    python -m eval.run_eval --out eval/report.md
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval import labels as L  # noqa: E402
from eval import metrics as M  # noqa: E402

DEFAULT_STATE = Path.home() / "GoogleDrive/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/state.json"
FIXED_THRESHOLDS = [50.0, 60.0, 65.0, 70.0, 80.0]
# Unter dieser Zahl wird das Ergebnis als *vorläufig* gekennzeichnet.
MIN_LABELS_WARN = 30
# Absolute Untergrenze: darunter ist nicht einmal eine Tendenz sinnvoll.
MIN_LABELS_HARD = 8


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %"


def _row(name: str, c: M.Counts) -> str:
    return (f"| {name} | {c.tp} | {c.fp} | {c.fn} | {c.tn} | "
            f"{_pct(M.precision(c))} | {_pct(M.recall(c))} | "
            f"{_pct(M.f1(c))} | {_pct(M.accuracy(c))} |")


def evaluate(state_path: Path, labels_path: Path) -> dict:
    apps = L.load_state(state_path)
    manual = L.load_manual_labels(labels_path)
    diag = L.diagnostics(apps, manual)
    dataset = L.build_dataset(apps, manual)
    labeled = [(e.score, e.label) for e in dataset]

    enough = (len(manual) >= MIN_LABELS_HARD and diag["dataset_positive"] > 0
              and diag["dataset_negative"] > 0)
    preliminary = enough and len(manual) < MIN_LABELS_WARN

    fixed = {t: M.evaluate_at(labeled, t) for t in FIXED_THRESHOLDS} if labeled else {}
    sweep = M.threshold_sweep(labeled) if labeled else []
    best_t, best_c = M.best_by_f1(sweep) if sweep else (0.0, M.Counts())
    baseline_c = M.majority_baseline(labeled) if labeled else M.Counts()

    return {
        "diagnostics": diag,
        "dataset": dataset,
        "fixed": fixed,
        "sweep": sweep,
        "best_threshold": best_t,
        "best_counts": best_c,
        "baseline": baseline_c,
        "enough_labels": enough,
        "preliminary": preliminary,
    }


def render_report(res: dict) -> str:
    d = res["diagnostics"]
    now = datetime.now().isoformat(timespec="seconds")
    out: list[str] = []
    out.append("# Evaluation: Keyword-Fit vs. manuelle Eignungs-Labels\n")
    out.append(f"_Erzeugt: {now}_\n")

    out.append("## 1. Label-Lage\n")
    out.append(f"- Einträge im Bestand: **{d['total_apps']}**")
    out.append(f"- **Manuelle Labels:** {d['manual_labels']}")
    out.append(f"- Grobe Negative (Nicht passende Rolle): {d['explicit_reject_negatives']}")
    out.append(f"- Ausgeschlossene zirkuläre Löschungen (Score-basiert): "
               f"{d['circular_deletes_excluded']}")
    out.append(f"- **Datensatz für die Evaluation:** {d['dataset_size']} "
               f"({d['dataset_positive']} passend / {d['dataset_negative']} nicht passend)")
    out.append("")

    if not res["enough_labels"]:
        out.append("## Kein belastbares Ergebnis\n")
        out.append("Es liegen zu wenige Labels vor. **Der Status ist kein "
                   "Eignungssignal** (ADR-012), daher lässt sich aus dem Bestand "
                   "allein keine Qualität ableiten.\n")
        out.append(f"Bitte zuerst Labels setzen (Empfehlung: >= {MIN_LABELS_WARN}, "
                   "besser >= 50 je Klasse):\n")
        out.append("```bash\npython -m eval.label_tool --limit 25\n```\n")
        out.append("### Was der Bestand *nicht* hergibt\n")
        out.append(f"- {d['applied_but_not_a_fit_label']} Einträge mit `sentAt` = "
                   "**beworben** — das ist ein Prozessschritt, kein Eignungsurteil.")
        out.append("- `sent`/`followup`/`interview`/`rejected` bedeuten alle "
                   "beworben; `rejected` = Absage **der Firma**.")
        out.append("- Score-basierte Löschungen sind zirkulär und ausgeschlossen.")
        out.append("")
        return "\n".join(out)

    if res.get("preliminary"):
        out.append(f"> ⚠️ **VORLÄUFIG:** nur {d['manual_labels']} manuelle Labels. "
                   f"Für belastbare Aussagen sind ≥ {MIN_LABELS_WARN} nötig "
                   "(besser ≥ 50 je Klasse). Die Tendenz ist erkennbar, die "
                   "Zahlen sind aber nicht stabil.\n")

    # Trennkraft des Scores — NUR auf manuellen Labels (die groben Negative
    # wären sonst ein Strohmann: sie liegen per Konstruktion niedrig).
    manual_entries = [e for e in res["dataset"] if e.source == "manual"]
    pos = [e.score for e in manual_entries if e.label]
    neg = [e.score for e in manual_entries if not e.label]
    if pos and neg:
        mp, mn = sum(pos) / len(pos), sum(neg) / len(neg)
        out.append("## 2. Trennkraft des Scores (nur manuelle Labels)\n")
        out.append(f"- Scores **passend** ({len(pos)}): {sorted(int(x) for x in pos)} "
                   f"→ Mittel {mp:.0f} %")
        out.append(f"- Scores **nicht passend** ({len(neg)}): {sorted(int(x) for x in neg)} "
                   f"→ Mittel {mn:.0f} %")
        out.append(f"- Differenz der Mittelwerte: **{mn - mp:+.0f} Punkte** "
                   "(positiv = unpassende Stellen scoren höher = Score ist blind)")
        if mn - mp >= -5:
            out.append("\n> ❌ **Der Score trennt die Klassen nicht.** Die Mittelwerte "
                       "liegen gleichauf oder unpassende Stellen scoren sogar höher. "
                       "Keyword-Überlappung misst *Vokabular*, nicht *Relevanz*.\n")
        else:
            out.append(f"\n> ✅ Der Score trennt die Klassen um {mp - mn:.0f} Punkte "
                       "(auf dieser kleinen Stichprobe).\n")
        if len(res["dataset"]) > len(manual_entries):
            out.append(f"_Hinweis: Der volle Datensatz enthält zusätzlich "
                       f"{len(res['dataset']) - len(manual_entries)} grobe Negative "
                       "('Nicht passende Rolle'), die per Konstruktion niedrig scoren "
                       "und hier bewusst ausgeklammert sind._\n")

    b = res["baseline"]
    best_c = res["best_counts"]
    out.append("## 3. Ergebnisse bei festen Schwellenwerten\n")
    out.append("| Schwelle | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |")
    out.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for t in FIXED_THRESHOLDS:
        out.append(_row(f"Score >= {t:.0f}", res["fixed"][t]))
    out.append(_row("Majority-Baseline", b))
    out.append("")

    out.append("## 4. Beste Schwelle (F1-optimal)\n")
    out.append(f"- **Score >= {res['best_threshold']:.0f}** · "
               f"Precision {_pct(M.precision(best_c))} · "
               f"Recall {_pct(M.recall(best_c))} · F1 {_pct(M.f1(best_c))} · "
               f"Balanced Accuracy {_pct(M.balanced_accuracy(best_c))}\n")

    out.append("## 5. Threshold-Sweep\n")
    out.append("| Schwelle | TP | FP | FN | TN | Precision | Recall | F1 |")
    out.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for t, c in res["sweep"]:
        out.append(f"| {t:.0f} | {c.tp} | {c.fp} | {c.fn} | {c.tn} | "
                   f"{_pct(M.precision(c))} | {_pct(M.recall(c))} | {_pct(M.f1(c))} |")
    out.append("")

    out.append("## 6. Interpretation\n")
    out.append(f"- Majority-Baseline: {_pct(M.accuracy(b))} Accuracy bei "
               f"Recall {_pct(M.recall(b))} -> Accuracy ist bei "
               f"{_pct(d['dataset_negative'] / max(d['dataset_size'], 1))} "
               "Negativ-Anteil irreführend.")
    out.append(f"- F1-Optimum bei {res['best_threshold']:.0f} %; betrieblich "
               "wird bei 60 % erzeugt -> Kalibrierungslücke.")
    out.append("")
    out.append("### Grenzen\n")
    out.append(f"1. Nur {d['manual_labels']} manuelle Labels -> weite Konfidenzintervalle.")
    out.append(f"2. Nur {d['dataset_with_description']} Fälle mit Beschreibungstext.")
    out.append("3. Die groben Negative (Nicht passende Rolle) sind überwiegend "
               "nicht-technische Berufe — sie testen nur die grobe Trennschärfe.")
    out.append("")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fit-Scoring gegen manuelle Labels evaluieren")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--labels", type=Path, default=L.DEFAULT_LABELS_CSV)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--dataset-csv", type=Path, default=None,
                    help="gelabelten Datensatz als CSV mitschreiben")
    args = ap.parse_args(argv)

    if not args.state.exists():
        print(f"FEHLER: state.json nicht gefunden: {args.state}", file=sys.stderr)
        return 1

    res = evaluate(args.state, args.labels)
    report = render_report(res)

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"Report geschrieben: {args.out}")
    else:
        print(report)

    if args.dataset_csv and res["dataset"]:
        L.write_dataset_csv(res["dataset"], args.dataset_csv)
        print(f"Datensatz geschrieben: {args.dataset_csv}")

    d = res["diagnostics"]
    if not res["enough_labels"]:
        print(f"\n{chr(9888)}  nur {d[chr(39)+chr(39)]}")
        print("   Labels setzen mit:  python -m eval.label_tool --limit 25")
    else:
        print(f"\n{d['dataset_size']} gelabelt ({d['dataset_positive']}+ / "
              f"{d['dataset_negative']}-) · beste Schwelle "
              f"{res['best_threshold']:.0f} % · F1 {_pct(M.f1(res['best_counts']))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
