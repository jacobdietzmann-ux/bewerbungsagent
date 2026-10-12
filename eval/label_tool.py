"""Interaktives Labeling-Werkzeug für Eignungs-Urteile.

Erzeugt die Ground Truth, die der Datensatz **nicht** enthält: ob eine Stelle
inhaltlich zu Jacobs Profil passt — unabhängig vom Bewerbungsprozess.

Nutzung:
    python -m eval.label_tool --state <state.json> --limit 30
    python -m eval.label_tool --state <state.json> --description-chars 900

Steuerung (eine Stelle je Runde):
    j / 1   = passt (Eignung gegeben)
    n / 0   = passt nicht
    s       = unsicher (wird übersprungen, nicht gespeichert)
    d       = volle Beschreibung anzeigen
    b       = eine Stelle zurück? (nur Anzeige, ändert kein Label)
    q       = beenden & speichern

Labels werden **sofort** angehängt (crash-sicher) → ``eval/labels.csv``.

Warum manuell? Der ``status`` im Bestand beschreibt den Bewerbungsprozess,
nicht die Eignung (ADR-012). Ohne manuelle Labels ist keine seriöse
Evaluation möglich.
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from eval import labels as L  # noqa: E402

DEFAULT_STATE = Path.home() / "GoogleDrive/DOKUMENTE/Job/Bewerbung/2026/04_Agent/data/state.json"


def candidates(apps: list[dict], skip_keys: set[str], require_description: bool = True) -> list[dict]:
    """Wählt labelbare Kandidaten aus.

    Ausgeschlossen werden:
    - bereits gelabelte Einträge (``skip_keys``),
    - Einträge ohne Beschreibungstext (zu wenig Information für ein Urteil),
    - ``Nicht passende Rolle``-Verwürfe (schon als negativ bekannt),
    - Duplikate.
    """
    out = []
    seen_titles: set[str] = set()
    for a in apps:
        key = L.entry_key(a)
        if key in skip_keys:
            continue
        if (a.get("deleted_reason") or "") == L.EXPLICIT_NEGATIVE_REASON:
            continue
        if (a.get("deleted_reason") or "").lower().startswith("duplikat"):
            continue
        if require_description and not (a.get("beschreibung") or "").strip():
            continue
        tkey = f"{(a.get('firma') or '').lower()}|{(a.get('titel') or '').lower()}"
        if tkey in seen_titles:
            continue
        seen_titles.add(tkey)
        out.append(a)
    return out


def stratify_by_fit(apps: list[dict], bands: int = 4) -> list[dict]:
    """Sortiert Kandidaten in Fit-Bändern durchmischt.

    Verhindert Label-Bias: Ohne Streuung würde man nur die Randfälle sehen
    (sehr hoher oder sehr niedriger Score) und die Mitte nie beurteilen.
    """
    buckets: list[list[dict]] = [[] for _ in range(bands)]
    for a in apps:
        s = L.fit_value(a)
        idx = min(bands - 1, int(s // (100 / bands)))
        buckets[idx].append(a)
    for b in buckets:
        random.shuffle(b)
    # Reißverschluss-Verfahren: abwechselnd aus den Bändern ziehen.
    out: list[dict] = []
    while any(buckets):
        for b in buckets:
            if b:
                out.append(b.pop())
    return out


def format_card(app: dict, desc_chars: int = 700) -> str:
    """Rendert eine Stelle als kompakte Karte für das Terminal."""
    firma = (app.get("firma") or "?").strip()
    titel = (app.get("titel") or "?").strip()
    ort = (app.get("ort") or "?").strip()[:40]
    fit = L.fit_value(app)
    desc = (app.get("beschreibung") or "").strip()
    excerpt = desc[:desc_chars].replace("\n", " ")
    if len(desc) > desc_chars:
        excerpt += " …"
    lines = [
        "",
        "─" * 78,
        f"  {titel}",
        f"  {firma}  ·  {ort}",
        f"  aktueller Keyword-Fit: {fit:.0f} %",
        "─" * 78,
        f"  {excerpt}",
        "",
    ]
    return "\n".join(lines)


_INTERPRET = {
    "j": (True, "passt"), "1": (True, "passt"), "passt": (True, "passt"),
    "n": (False, "passt nicht"), "0": (False, "passt nicht"),
    "passt nicht": (False, "passt nicht"),
}


def classify_input(raw: str) -> tuple[bool | None, str]:
    """Übersetzt Nutzereingabe in (Label, Aktion). ``None`` = überspringen."""
    key = raw.strip().lower()
    if key in _INTERPRET:
        return _INTERPRET[key]
    if key in ("s", "skip", "unsicher", ""):
        return None, "unsicher"
    if key in ("q", "quit", "ende"):
        return None, "quit"
    return None, "unbekannt"


def run_session(apps: list[dict], labels_path: Path, limit: int | None,
                desc_chars: int, input_fn=input, print_fn=print) -> dict:
    """Führt eine Labeling-Runde aus (testbar über injizierte IO-Funktionen)."""
    known = L.load_manual_labels(labels_path)
    todo = stratify_by_fit(candidates(apps, set(known.keys())))
    if limit:
        todo = todo[:limit]

    stats = {"labeled": 0, "positive": 0, "negative": 0, "skipped": 0}
    total = len(todo)
    print_fn(f"\n{total} Kandidaten zum Labeln. "
             f"Bereits vorhandene Labels: {len(known)}.")
    print_fn("j = passt · n = passt nicht · s = unsicher · d = Details · q = Ende\n")

    for i, app in enumerate(todo, 1):
        print_fn(format_card(app, desc_chars))
        print_fn(f"  [{i}/{total}]  Deine Bewertung?  (j/n/s/d/q)")
        while True:
            raw = input_fn("  > ")
            label, action = classify_input(raw)
            if action == "quit":
                print_fn("\n  Beendet.")
                return stats
            if action == "unbekannt":
                if raw.strip().lower() in ("d", "details"):
                    print_fn("\n" + (app.get("beschreibung") or "(keine Beschreibung)")[:6000])
                    print_fn("\n  Deine Bewertung?  (j/n/s/q)")
                    continue
                print_fn("  Bitte j, n, s, d oder q eingeben.")
                continue
            if label is None:  # unsicher
                stats["skipped"] += 1
                print_fn("  → übersprungen")
            else:
                L.append_manual_label(L.entry_key(app), label, labels_path)
                stats["labeled"] += 1
                stats["positive" if label else "negative"] += 1
                print_fn(f"  → gespeichert: {'passt' if label else 'passt nicht'}")
            break
    return stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Eignungs-Labels manuell setzen")
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--labels", type=Path, default=L.DEFAULT_LABELS_CSV)
    ap.add_argument("--limit", type=int, default=25, help="Anzahl Stellen in dieser Runde")
    ap.add_argument("--description-chars", type=int, default=700)
    ap.add_argument("--seed", type=int, default=42, help="Reproduzierbare Streuung")
    args = ap.parse_args(argv)

    random.seed(args.seed)

    if not args.state.exists():
        print(f"FEHLER: state.json nicht gefunden: {args.state}", file=sys.stderr)
        return 1

    apps = L.load_state(args.state)
    stats = run_session(apps, args.labels, args.limit, args.description_chars)

    total = L.load_manual_labels(args.labels)
    print(f"\nDiese Runde: {stats['labeled']} gelabelt "
          f"({stats['positive']} passend / {stats['negative']} nicht passend), "
          f"{stats['skipped']} übersprungen.")
    print(f"Labels insgesamt: {len(total)} → {args.labels}")

    if len(total) < 30:
        print("\nHinweis: Für belastbare Metriken sind mindestens ~50 Labels "
              "je Klasse empfehlenswert. Mehrere Runden nötig.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
