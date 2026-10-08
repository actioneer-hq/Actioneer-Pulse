"""HDBSCAN degrade paths (tiny inputs) and a toy run."""

from __future__ import annotations

from voiceobs.clustering import algo


def test_too_few_rows_are_noise():
    assert algo.cluster([]) == []
    assert algo.cluster([[1.0, 0.0], [0.0, 1.0]], min_cluster_size=3) == [-1, -1]


def test_two_tight_groups():
    a = [[1.0, 0.0, 0.0], [0.99, 0.02, 0.0], [0.98, 0.0, 0.03]]
    b = [[0.0, 1.0, 0.0], [0.02, 0.99, 0.0], [0.0, 0.98, 0.03]]
    labels = algo.cluster(a + b, min_cluster_size=3)
    assert len(set(labels[:3])) == 1 and len(set(labels[3:])) == 1 and labels[0] != labels[3]
