"""Pure clustering math: embeddings -> (cluster labels, 2D display coords).

UMAP dim-reduction + HDBSCAN over cosine (L2-normalize → euclidean ≈ cosine). No DB/config imports;
the heavy deps (umap-learn, scikit-learn — the `analytics` extra) are imported lazily so the base
install/API stays lean and callers can guard on availability via `available()`."""

from __future__ import annotations

import numpy as np


def available() -> bool:
    try:
        import sklearn.cluster  # noqa: F401
        import umap  # noqa: F401
        return True
    except ImportError:
        return False


def cluster(
    vectors: list[list[float]], min_cluster_size: int = 8, seed: int = 42,
) -> tuple[list[int], list[tuple[float, float]]]:
    """Return (labels, coords). labels[i] is the cluster id for row i (-1 = noise); coords[i] is its
    2D point. Degrades gracefully for tiny inputs."""
    x = np.asarray(vectors, dtype="float32")
    n = x.shape[0]
    if n == 0:
        return [], []
    norms = np.linalg.norm(x, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    xn = x / norms
    coords = _project_2d(xn, seed)
    labels = _hdbscan(xn, min_cluster_size, seed) if n >= max(2, min_cluster_size) else [-1] * n
    return labels, [(float(a), float(b)) for a, b in coords]


def _project_2d(xn: np.ndarray, seed: int) -> np.ndarray:
    n, d = xn.shape
    if n < 4:  # too few for UMAP — just use the first 2 dims (padded)
        c = np.zeros((n, 2), dtype="float32")
        c[:, : min(2, d)] = xn[:, : min(2, d)]
        return c
    import umap
    return umap.UMAP(n_components=2, n_neighbors=min(15, n - 1),
                     metric="cosine", random_state=seed).fit_transform(xn)


def _hdbscan(xn: np.ndarray, min_cluster_size: int, seed: int) -> list[int]:
    z = xn
    if xn.shape[1] > 10 and xn.shape[0] >= 6:  # reduce high-dim before density clustering
        import umap
        z = umap.UMAP(n_components=min(10, xn.shape[0] - 2), n_neighbors=min(15, xn.shape[0] - 1),
                      metric="cosine", random_state=seed).fit_transform(xn)
    from sklearn.cluster import HDBSCAN
    return HDBSCAN(min_cluster_size=max(2, min_cluster_size),
                   metric="euclidean").fit_predict(z).tolist()
