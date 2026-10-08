"""Pure clustering math: embeddings -> cluster labels.

HDBSCAN over L2-normalized vectors (euclidean on unit vectors ~ cosine): finds clusters of different
tightness without a distance cut, and leaves what fits no pattern as noise (-1). scikit-learn (the
`analytics` extra) is imported lazily so the base install/API stays lean; guard with `available()`."""

from __future__ import annotations

import numpy as np


def available() -> bool:
    try:
        import sklearn.cluster  # noqa: F401
        return True
    except ImportError:
        return False


def cluster(vectors: list[list[float]], min_cluster_size: int = 5) -> list[int]:
    """labels[i] = the cluster of row i (-1 = noise). Too few rows for one cluster -> all noise."""
    x = np.asarray(vectors, dtype="float32")
    mcs = max(2, min_cluster_size)
    if x.shape[0] < mcs:
        return [-1] * x.shape[0]
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    from sklearn.cluster import HDBSCAN

    return HDBSCAN(min_cluster_size=mcs, metric="euclidean").fit_predict(x / norms).tolist()
