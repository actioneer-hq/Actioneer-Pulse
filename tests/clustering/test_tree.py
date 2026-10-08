"""Hierarchical clustering of unscripted moments (HDBSCAN inside HDBSCAN), with a fake algo."""

from __future__ import annotations

from types import SimpleNamespace as NS

from voiceobs.clustering import service


def _m(i, call, vec):
    return NS(id=f"m{i}", call_id=call, embedding=vec, cluster_key=None)


def test_tree_recurses_keeps_min_calls_and_marks_leaves(monkeypatch):
    # Top level: A (calls 1-6) vs B (calls 7-9). Inside A: A1 (1-3) and A2 (4-6). B doesn't split.
    vecs = {**{c: [1.0, 0.0, 0.1] for c in range(1, 4)}, **{c: [1.0, 0.0, -0.1] for c in range(4, 7)},
            **{c: [0.0, 1.0, 0.0] for c in range(7, 10)}}
    ms = [_m(c, f"c{c}", vecs[c]) for c in range(1, 10)] + [_m(99, "c1", [0.5, 0.5, 0.5])]  # stray

    def fake(vectors, min_cluster_size):
        xs = [tuple(v) for v in vectors]
        if len({x[1] for x in xs}) > 1:          # mixed A/B -> split by the 2nd dim; strays are noise
            return [-1 if x[2] == 0.5 else (0 if x[1] == 0 else 1) for x in xs]
        if len({x[2] for x in xs}) > 1:          # inside A -> split by the 3rd dim
            return [0 if x[2] > 0 else 1 for x in xs]
        return [0] * len(xs)                      # nothing finer

    monkeypatch.setattr(service.algo, "cluster", fake)
    tree = service.build_tree(ms, min_calls=3)
    shape = sorted((n.depth, n.parent is None, n.calls, n.leaf) for n in tree)
    assert shape == [(0, True, 3, True), (0, True, 6, False), (1, False, 3, True), (1, False, 3, True)]
    assert ms[-1].cluster_key is None  # the stray is noise at the top: no node claims it
    assert service.build_tree(ms, min_calls=3, max_depth=1) and all(
        n.depth == 0 for n in service.build_tree(ms, min_calls=3, max_depth=1))


def test_medoid_is_the_member_closest_to_the_centroid():
    node = service.Node(0, None, 0, [_m(1, "a", [1.0, 0.0]), _m(2, "b", [0.9, 0.3]), _m(3, "c", [0.7, 0.7])])
    assert node.medoid().id == "m2"
