"""Conservative final-output deduplication for visual object clusters."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class FinalOutputCluster:
    """Temporary cluster used only while making a final answer snapshot."""

    class_name: str
    x: float
    y: float
    z: float
    observation_count: int
    source_cluster_ids: tuple
    lineage_cluster_ids: frozenset


@dataclass(frozen=True)
class FinalMerge:
    """One conservative final-output merge, retained for logging."""

    class_name: str
    first_cluster_ids: tuple
    second_cluster_ids: tuple
    distance: float
    first_observations: int
    second_observations: int


def _same_frame_separate(first, second, protected_pairs):
    """Return whether prior same-frame evidence says clusters are distinct."""
    for first_id in first.lineage_cluster_ids:
        for second_id in second.lineage_cluster_ids:
            if frozenset((first_id, second_id)) in protected_pairs:
                return True
    return False


def _merge_pair(first, second):
    """Make a count-weighted temporary centroid without touching tracking."""
    total = first.observation_count + second.observation_count
    first_weight = first.observation_count / total
    second_weight = second.observation_count / total
    return FinalOutputCluster(
        class_name=first.class_name,
        x=first.x * first_weight + second.x * second_weight,
        y=first.y * first_weight + second.y * second_weight,
        z=first.z * first_weight + second.z * second_weight,
        observation_count=total,
        source_cluster_ids=tuple(
            sorted(first.source_cluster_ids + second.source_cluster_ids)
        ),
        lineage_cluster_ids=(
            first.lineage_cluster_ids | second.lineage_cluster_ids
        ),
    )


def final_deduplicate_clusters(
    clusters,
    final_radius,
    protected_pairs,
    lineage_by_cluster_id,
):
    """
    Return a conservative, non-mutating final output cluster snapshot.

    The candidate list is built from original clusters and selected greedily by
    ascending distance. A cluster may appear in at most one selected pair, so
    A--B and B--C candidates can never collapse A, B, and C into one output.
    """
    if final_radius <= 0.0:
        raise ValueError('final_radius must be greater than zero.')

    temporary_clusters = []
    for cluster in clusters:
        cluster_id = cluster.cluster_id
        lineage = frozenset(
            lineage_by_cluster_id.get(cluster_id, frozenset((cluster_id,)))
        )
        temporary_clusters.append(
            FinalOutputCluster(
                class_name=cluster.class_name,
                x=float(cluster.x),
                y=float(cluster.y),
                z=float(cluster.z),
                observation_count=cluster.observation_count,
                source_cluster_ids=(cluster_id,),
                lineage_cluster_ids=lineage,
            )
        )

    candidates = []
    for first_index, first in enumerate(temporary_clusters):
        for second_index, second in enumerate(
            temporary_clusters[first_index + 1:],
            start=first_index + 1,
        ):
            if first.class_name != second.class_name:
                continue
            distance = math.hypot(first.x - second.x, first.y - second.y)
            if distance >= final_radius:
                continue
            if _same_frame_separate(first, second, protected_pairs):
                continue
            candidates.append((
                distance,
                first.class_name,
                first.source_cluster_ids,
                second.source_cluster_ids,
                first_index,
                second_index,
            ))

    candidates.sort()
    selected_indices = set()
    results_by_index = {}
    merges = []
    for (
        distance,
        _class_name,
        _first_ids,
        _second_ids,
        first_index,
        second_index,
    ) in candidates:
        if first_index in selected_indices or second_index in selected_indices:
            continue
        first = temporary_clusters[first_index]
        second = temporary_clusters[second_index]
        results_by_index[first_index] = _merge_pair(first, second)
        selected_indices.update((first_index, second_index))
        merges.append(
            FinalMerge(
                class_name=first.class_name,
                first_cluster_ids=first.source_cluster_ids,
                second_cluster_ids=second.source_cluster_ids,
                distance=distance,
                first_observations=first.observation_count,
                second_observations=second.observation_count,
            )
        )

    results = list(results_by_index.values())
    results.extend(
        cluster
        for index, cluster in enumerate(temporary_clusters)
        if index not in selected_indices
    )
    results.sort(key=lambda cluster: (
        cluster.class_name,
        cluster.x,
        cluster.y,
        cluster.source_cluster_ids,
    ))
    return results, merges
