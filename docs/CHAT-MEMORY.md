# Projekt-Gedächtnis (kuratiert)

Verdichtetes Wissen aus der Entwicklungssitzung. Ersetzt **nicht** das
Roh-Transkript (siehe `BACKUP.md`), sondern hält die Erkenntnisse fest, die
man später wirklich braucht.

## Was gebaut wurde

Ein lokaler Bewerbungsagent mit vier Stufen (Suche → Matching → Dokumente →
Dashboard) plus einem Weboberfläche-Server für Live-Statusänderungen.

## Gelernte Lektionen (aus echten Fehlern)

1. **Silent-Fail durch Fallback-Werte.** `_fmt_date` fiel auf „heute" zurück.
   Ergebnis: eine plausible, aber falsche Statistik. *Lehre:* Fallbacks
   sichtbar machen und mit Tests absichern.
2. **String-Normalisierung ist eine Falle.** `strip("()")` vor einem
   Regex-Split zerstörte das Muster. *Lehre:* Reihenfolge von
   Normalisierung/Split explizit testen.
3. **Kontext-spezifische Generika.** Das Wort „Analyse" entstand als
   eigenständiges Keyword, weil ein Skill-String Kommas enthielt.
   *Lehre:* Noise-Listen + Tests gegen generische Tokens.
4. **Sync vs. Arbeitsverzeichnis.** Ein Cloud-Sync (rclone-bisync) kann
   lokale Änderungen zurücksetzen. *Lehre:* Repos/VCS niemals auf
   Sync-Mounts betreiben.
5. **Caches brauchen Invalidierung.** Der Dashboard-Server cached HTML.
   Ohne Invalidierung bei Template-Änderung zeigt er Altstand.
   *Lehre:* Cache-Key = alle Eingaben (State *und* Code).
6. **Encoding-Realität.** PDF-Standardschriften sind Latin-1. Unicode-Pfeile
   wurden zu „■"-Boxen. *Lehre:* Sanitizing-Layer vor dem Rendern.
7. **Mehrsprachigkeit ist mehr als Überschriften.** Deutsche Skill-Labels
   blieben in englischen Dokumenten. *Lehre:* Alle Ausgabepfade prüfen, nicht
   nur die offensichtlichen.
8. **Verifizieren statt vertrauen.** Ein Mutationstest (Bug absichtlich
   wieder einbauen) beweist, dass Tests wirklich greifen.

## Wiederkehrende Arbeitsmuster

- **Backup vor destruktiven Schritten** (`state.backup.pre-*.json`).
- **History-Schutz**: versendete Bewerbungen nie überschreiben.
- **Kleine, verifizierte Schritte** statt großer Umbauten.
- **Headless-Browser** für JS-gerenderte Seiten (StepStone blockt `requests`).

## Offene Punkte / Ideen

- [ ] Metriken: Fit-Präzision gegen manuelle Bewertung messen (Evaluation).
- [ ] Suche um weitere Provider erweitern.
- [ ] Coverage-Report in CI (`pytest --cov`).
- [ ] Interessenkonflikte: Welche Skills fehlen im Profil, tauchen aber
      häufig in Top-Jobs auf? (Gap-Analyse)
