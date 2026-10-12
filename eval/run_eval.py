"""Offline-Evaluation des Fit-Scorings gegen die echten Bewerbungslabels.

Beantwortet die Frage: **Wie gut sagt der Profil-Fit tatsächlich voraus, ob
eine Stelle verfolgt wird?**

Nutzung:
    python -m eval.run_eval                         # Standard: 04_Agent/data/state.json
    python -m eval.run_eval --state PATH --out OUT  # explizit
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Erlaubt den Aufruf sowohl als Modul als auch direkt aus dem eval/-Ordner.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval import labels as L  # noqa: E402
from eval import metrics as M  # noqa: E402

DEFAULT_STATE = Path.home() / "GoogleDrive/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/state.json"
FIXED_THRESHOLDS = [50.0, 60.0, 65.0, 70.0, 80.0]


def _pct(x: float) -> str:
    return f"{x * 100:.1f} %"


def _row(name: str, c: M.Counts) -> str:
    return (f"| {name} | {c.tp} | {c.fp} | {c.fn} | {c.tn} | "
            f"{_pct(M.precision(c))} | {_pct(M.recall(c))} | "
            f"{_pct(M.f1(c))} | {_pct(M.accuracy(c))} |")


def evaluate(state_path: Path) -> dict:
    apps = L.load_state(state_path)
    diag = L.label_diagnostics(apps)
    dataset = L.build_dataset(apps)
    labeled = [(e.score, e.label) for e in dataset]

    fixed = {t: M.evaluate_at(labeled, t) for t in FIXED_THRESHOLDS}
    sweep = M.threshold_sweep(labeled)
    best_t, best_c = M.best_by_f1(sweep)
    baseline_c = M.majority_baseline(labeled)

    return {
        "diagnostics": diag,
        "dataset": dataset,
        "fixed": fixed,
        "sweep": sweep,
        "best_threshold": best_t,
        "best_counts": best_c,
        "baseline": baseline_c,
    }


def render_report(res: dict) -> str:
    d = res["diagnostics"]
    now = datetime.now().isoformat(timespec="seconds")
    b = res["baseline"]
    best_c = res["best_counts"]

    lines: list[str] = []
    lines.append("# Evaluation: Profil-Fit vs. echte Bewerbungsentscheidung\n")
    lines.append(f"_Erzeugt: {now}_\n")

    lines.append("## 1. Label-Diagnose\n")
    lines.append(f"- Einträge gesamt: **{d['total_apps']}**")
    lines.append(f"- Gelabelt: **{d['labeled']}** "
                 f"({d['labeled_positive']} positiv / {d['labeled_negative']} negativ)")
    lines.append(f"- Davon mit Beschreibungstext: {d['labeled_with_description']} "
                 f"({d['labeled_with_description_positive']} positiv)")
    lines.append(f"- Grobe Label-Rausch-Schätzung: "
                 f"{d['label_noise_estimate']['rejected_with_high_score']} verworfene Stellen "
                 f"mit Score ≥ 70 ({d['label_noise_estimate']['note']})")
    lines.append("")
    lines.append("Status-Verteilung:")
    lines.append("")
    lines.append("| Status | Anzahl |")
    lines.append("|---|---:|")
    for st, n in sorted(d["status_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {st} | {n} |")
    lines.append("")

    lines.append('> **Positiv** = `sent`/`followup`/`interview` (Bewerbung versendet).  ')
    lines.append('> **Negativ** = `rejected` (Abgelehnt/Abgelaufen = vom Nutzer verworfen '
                 'oder abgelaufen).  ')
    lines.append("> `research`/`docs`/`neu` sind **unlabeled** und ausgeschlossen.\n")

    lines.append("## 2. Ergebnisse bei festen Schwellenwerten\n")
    lines.append("| Schwelle | TP | FP | FN | TN | Precision | Recall | F1 | Accuracy |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for t in FIXED_THRESHOLDS:
        lines.append(_row(f"Score ≥ {t:.0f}", res["fixed"][t]))
    lines.append(_row("Majority-Baseline", b))
    lines.append("")

    lines.append("## 3. Beste Schwelle (F1-optimal)\n")
    lines.append(f"- **Score ≥ {res['best_threshold']:.0f}**")
    lines.append(f"- Precision {_pct(M.precision(best_c))} · "
                 f"Recall {_pct(M.recall(best_c))} · F1 {_pct(M.f1(best_c))} · "
                 f"Balanced Accuracy {_pct(M.balanced_accuracy(best_c))}")
    lines.append("")

    lines.append("## 4. Threshold-Sweep\n")
    lines.append("| Schwelle | TP | FP | FN | TN | Precision | Recall | F1 |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|")
    for t, c in res["sweep"]:
        lines.append(f"| {t:.0f} | {c.tp} | {c.fp} | {c.fn} | {c.tn} | "
                     f"{_pct(M.precision(c))} | {_pct(M.recall(c))} | {_pct(M.f1(c))} |")
    lines.append("")

    # --- Interpretation ---
    acc_gap = M.accuracy(b) - M.accuracy(res["fixed"][60.0])
    lines.append("## 5. Interpretation\n")
    lines.append(
        f"- Die **Majority-Baseline** erreicht {_pct(M.accuracy(b))} Accuracy bei "
        f"**Recall {_pct(M.recall(b))}** — sie sagt einfach immer 'nicht bewerben'. "
        f"Das zeigt: *Accuracy ist bei {_pct(d['labeled_negative'] / max(d['labeled'], 1))} "
        f"Negativ-Anteil irreführend.*"
    )
    lines.append(
        f"- Leitmetrik ist daher **F1** bzw. **Recall bei vertretbarer Precision**: "
        f"ein verpasster guter Job ist teurer als ein zusätzlich geprüfter."
    )
    lines.append(
        f"- Die Schwelle 60 % ist betrieblich gewählt ('ab hier Unterlagen erzeugen'). "
        f"Das F1-Optimum liegt bei {res['best_threshold']:.0f} % — "
        f"die Differenz ist die Kalibrierungslücke."
    )
    lines.append("")
    lines.append("### Grenzen dieser Evaluation")
    lines.append(
        f"1. **Kleine Stichprobe:** nur {d['labeled']} gelabelte Fälle "
        f"({d['labeled_positive']} positiv). Konfidenzintervalle sind weit."
    )
    lines.append(
        "2. **Label-Rauschen:** `rejected` mischt Nutzerentscheidungen und abgelaufene "
        "Anzeigen. Die erreichbare Precision ist dadurch gedeckelt."
    )
    lines.append(
        "3. **Selection Bias:** Der Score war *selbst* Grundlage der Entscheidung — "
        "das Modell wird teils gegen seine eigene Empfehlung gemessen (Zirkularität)."
    )
    lines.append(
        f"4. **Nur {d['labeled_with_description']} Fälle mit Beschreibungstext** — "
        "der Score basiert für den Rest nur auf Titel/Firma/Ort."
    )
    lines.append("")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Fit-Scoring offline evaluieren")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)

    if not args.state.exists():
        print(f"FEHLER: state.json nicht gefunden: {args.state}", file=sys.stderr)
        return 1

    res = evaluate(args.state)
    report = render_report(res)

    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"Report geschrieben: {args.out}")
    else:
        print(report)

    d = res["diagnostics"]
    print(f"\nKurzfassung: {d['labeled']} gelabelt "
          f"({d['labeled_positive']}+ / {d['labeled_negative']}-) · "
          f"beste Schwelle {res['best_threshold']:.0f} % · "
          f"F1 {_pct(M.f1(res['best_counts']))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
