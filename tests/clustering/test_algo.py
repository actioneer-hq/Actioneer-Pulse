"""Clustering algo — degrade paths (no heavy deps needed). The full UMAP/HDBSCAN path is exercised
manually / in the service integration, not here (numba JIT would slow the unit suite)."""

from __future__ import annotations

from voiceobs.clustering import algo


def test_empty():
    assert algo.cluster([]) == ([], [])


def test_tiny_input_is_noise_with_2d_coords():
    # n < min_cluster_size and n < 4 → all noise, coords are 2D (no umap import on this path)
    labels, coords = algo.cluster([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], min_cluster_size=8)
    assert labels == [-1, -1]
    assert len(coords) == 2 and all(len(c) == 2 for c in coords)
