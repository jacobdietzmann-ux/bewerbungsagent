"""Tests für die Evaluations-Metriken (``eval/metrics.py``) und Labels."""

from __future__ import annotations

import pytest

from eval import labels as L
from eval import metrics as M


class TestConfusionMatrix:
    def test_perfect_prediction(self):
        c = M.confusion_matrix([True, False, True], [True, False, True])
        assert (c.tp, c.fp, c.fn, c.tn) == (2, 0, 0, 1)

    def test_all_wrong(self):
        c = M.confusion_matrix([True, True], [False, False])
        assert (c.tp, c.fp, c.fn, c.tn) == (0, 0, 2, 0)

    def test_all_positive_prediction(self):
        c = M.confusion_matrix([True, False], [True, True])
        assert (c.tp, c.fp, c.fn, c.tn) == (1, 1, 0, 0)

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            M.confusion_matrix([True], [True, False])

    def test_empty(self):
        c = M.confusion_matrix([], [])
        assert c.total == 0
        assert M.precision(c) == 0.0
        assert M.recall(c) == 0.0
        assert M.f1(c) == 0.0


class TestMetrics:
    def test_precision_recall_f1_known_case(self):
        # tp=3, fp=1, fn=2  -> P=0.75, R=0.60, F1=0.6667
        c = M.Counts(tp=3, fp=1, fn=2, tn=4)
        assert M.precision(c) == pytest.approx(0.75)
        assert M.recall(c) == pytest.approx(0.60)
        assert M.f1(c) == pytest.approx(24 / 36, abs=1e-6)

    def test_no_positive_predictions_does_not_crash(self):
        c = M.Counts(tp=0, fp=0, fn=5, tn=5)
        assert M.precision(c) == 0.0
        assert M.recall(c) == 0.0
        assert M.f1(c) == 0.0

    def test_accuracy_and_balanced_accuracy(self):
        # Imbalance-Beispiel: alles negativ vorhergesagt
        c = M.Counts(tp=0, fp=0, fn=2, tn=8)
        assert M.accuracy(c) == pytest.approx(0.8)
        assert M.recall(c) == 0.0
        assert M.specificity(c) == 1.0
        assert M.balanced_accuracy(c) == pytest.approx(0.5)

    def test_perfect_scores(self):
        c = M.Counts(tp=5, fp=0, fn=0, tn=5)
        assert M.precision(c) == 1.0
        assert M.recall(c) == 1.0
        assert M.f1(c) == 1.0
        assert M.accuracy(c) == 1.0
        assert M.balanced_accuracy(c) == 1.0


class TestEvaluationAtThreshold:
    def test_threshold_separates_correctly(self):
        labeled = [(90.0, True), (80.0, True), (30.0, False), (20.0, False)]
        c = M.evaluate_at(labeled, 60.0)
        assert (c.tp, c.fp, c.fn, c.tn) == (2, 0, 0, 2)

    def test_threshold_zero_predicts_all_positive(self):
        labeled = [(10.0, True), (0.0, False)]
        c = M.evaluate_at(labeled, 0.0)
        assert c.fn == 0
        assert c.fp == 1

    def test_threshold_above_all_predicts_all_negative(self):
        labeled = [(10.0, True), (99.0, False)]
        c = M.evaluate_at(labeled, 100.0)
        assert c.tp == 0
        assert c.fn == 1


class TestSweepAndBaseline:
    def test_best_by_f1_prefers_balanced_threshold(self):
        labeled = [(95.0, True), (85.0, True), (75.0, False), (65.0, False)]
        sweep = M.threshold_sweep(labeled, thresholds=[60.0, 90.0])
        best_t, best_c = M.best_by_f1(sweep)
        # Bei 90: tp=1, fn=1 -> F1=0.667 ; bei 60: tp=2, fp=2 -> F1=0.667
        assert best_t in (60.0, 90.0)
        assert M.f1(best_c) > 0

    def test_majority_baseline_predicts_majority_class(self):
        # 1 positiv, 3 negativ -> Baseline sagt immer negativ
        labeled = [(90.0, True), (10.0, False), (20.0, False), (30.0, False)]
        c = M.majority_baseline(labeled)
        assert c.tp == 0
        assert c.fn == 1
        assert c.tn == 3
        assert M.accuracy(c) == pytest.approx(0.75)

    def test_sweep_covers_range(self):
        labeled = [(50.0, True)]
        sweep = M.threshold_sweep(labeled)
        assert len(sweep) == 21  # 0..100 in 5er-Schritten
        assert sweep[0][0] == 0.0
        assert sweep[-1][0] == 100.0


class TestLabels:
    def _apps(self):
        return [
            {"firma": "A", "titel": "T1", "status": "sent", "score": 80, "beschreibung": "x"},
            {"firma": "B", "titel": "T2", "status": "interview", "score": 70},
            {"firma": "C", "titel": "T3", "status": "rejected", "score": 30},
            {"firma": "D", "titel": "T4", "status": "research", "score": 90},
            {"firma": "E", "titel": "T5", "status": "docs", "score": 60},
        ]

    def test_only_labeled_statuses_included(self):
        ds = L.build_dataset(self._apps())
        statuses = {e.status for e in ds}
        assert statuses == {"sent", "interview", "rejected"}

    def test_positive_and_negative_assignment(self):
        ds = L.build_dataset(self._apps())
        sent = next(e for e in ds if e.status == "sent")
        rejected = next(e for e in ds if e.status == "rejected")
        assert sent.label is True
        assert rejected.label is False

    def test_has_description_flag(self):
        ds = L.build_dataset(self._apps())
        assert next(e for e in ds if e.status == "sent").has_description is True
        assert next(e for e in ds if e.status == "interview").has_description is False

    def test_fit_value_prefers_fit_pct(self):
        assert L.fit_value({"fit_pct": 77, "score": 20}) == 77.0
        assert L.fit_value({"score": 55}) == 55.0
        assert L.fit_value({}) == 0.0

    def test_auto_deleted_excluded_by_default(self):
        apps = [{"firma": "X", "titel": "Y", "status": "rejected", "score": 10,
                 "deleted": True, "deleted_reason": "Fit unter 60 Prozent"}]
        assert L.build_dataset(apps) == []
        assert len(L.build_dataset(apps, include_auto_deleted=True)) == 1

    def test_diagnostics_keys(self):
        d = L.label_diagnostics(self._apps())
        assert d["labeled"] == 3
        assert d["labeled_positive"] == 2
        assert d["labeled_negative"] == 1
        assert d["labeled_with_description"] == 1
