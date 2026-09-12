#!/usr/bin/env python3
"""Deterministic coverage for conservative final-output deduplication."""

from dataclasses import dataclass
import unittest

from vision_final_dedup import final_deduplicate_clusters
from vision_final_dedup import partition_by_minimum_observations


@dataclass(frozen=True)
class Cluster:
    cluster_id: int
    class_name: str
    x: float
    y: float
    z: float = 0.75
    observation_count: int = 3


class TestFinalDeduplication(unittest.TestCase):
    """Keep final-output behavior independent of ROS and YOLO dependencies."""

    final_radius = 0.08

    @staticmethod
    def _run(clusters, protected_pairs=(), lineages=None):
        if lineages is None:
            lineages = {
                cluster.cluster_id: frozenset((cluster.cluster_id,))
                for cluster in clusters
            }
        return final_deduplicate_clusters(
            clusters,
            TestFinalDeduplication.final_radius,
            set(protected_pairs),
            lineages,
        )

    def test_known_duplicate_apple_merges_without_protection(self):
        clusters = [
            Cluster(0, 'apple', -2.027, 0.056, observation_count=4),
            Cluster(1, 'apple', -2.092, 0.086, observation_count=6),
        ]

        results, merges = self._run(clusters)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].class_name, 'apple')
        self.assertEqual(results[0].observation_count, 10)
        self.assertEqual(results[0].source_cluster_ids, (0, 1))
        self.assertEqual(len(merges), 1)
        self.assertAlmostEqual(merges[0].distance, 0.071589, places=5)

    def test_same_frame_separate_apple_clusters_are_protected(self):
        clusters = [
            Cluster(0, 'apple', -2.027, 0.056),
            Cluster(1, 'apple', -2.092, 0.086),
        ]

        results, merges = self._run(clusters, (frozenset((0, 1)),))

        self.assertEqual(len(results), 2)
        self.assertEqual(merges, [])

    def test_removed_online_cluster_id_remains_protected_by_lineage(self):
        clusters = [
            Cluster(0, 'apple', -2.027, 0.056),
            Cluster(2, 'apple', -2.092, 0.086),
        ]
        lineages = {
            0: frozenset((0, 1)),
            2: frozenset((2,)),
        }

        results, merges = self._run(
            clusters,
            (frozenset((1, 2)),),
            lineages,
        )

        self.assertEqual(len(results), 2)
        self.assertEqual(merges, [])

    def test_nearby_different_classes_never_merge(self):
        clusters = [
            Cluster(0, 'apple', 1.000, 1.000),
            Cluster(1, 'coke_can', 1.010, 1.010),
        ]

        results, merges = self._run(clusters)

        self.assertEqual(len(results), 2)
        self.assertEqual(merges, [])

    def test_same_class_farther_than_final_radius_does_not_merge(self):
        clusters = [
            Cluster(0, 'apple', 1.000, 1.000),
            Cluster(1, 'apple', 1.081, 1.000),
        ]

        results, merges = self._run(clusters)

        self.assertEqual(len(results), 2)
        self.assertEqual(merges, [])

    def test_chain_candidates_do_not_collapse_three_clusters(self):
        clusters = [
            Cluster(0, 'apple', 0.000, 0.000),
            Cluster(1, 'apple', 0.070, 0.000),
            Cluster(2, 'apple', 0.140, 0.000),
        ]

        results, merges = self._run(clusters)

        self.assertEqual(len(results), 2)
        self.assertEqual(len(merges), 1)
        self.assertEqual(len(merges[0].first_cluster_ids), 1)
        self.assertEqual(len(merges[0].second_cluster_ids), 1)

    def test_unconfirmed_cluster_is_excluded_before_final_deduplication(self):
        clusters = [
            Cluster(0, 'apple', -2.027, 0.056, observation_count=3),
            Cluster(1, 'apple', -2.092, 0.086, observation_count=2),
        ]
        confirmed = [
            cluster for cluster in clusters if cluster.observation_count >= 3
        ]

        results, merges = self._run(confirmed)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].source_cluster_ids, (0,))
        self.assertEqual(results[0].observation_count, 3)
        self.assertEqual(merges, [])

    def test_final_evidence_threshold_uses_merged_observation_total(self):
        clusters = [
            Cluster(0, 'apple', -3.423, -3.337, observation_count=3),
            Cluster(1, 'apple', -3.493, -3.338, observation_count=2),
            Cluster(2, 'apple', -3.603, -3.376, observation_count=4),
        ]

        results, _merges = self._run(clusters)
        accepted, suppressed = partition_by_minimum_observations(results, 5)

        self.assertEqual(len(accepted), 1)
        self.assertEqual(accepted[0].source_cluster_ids, (0, 1))
        self.assertEqual(accepted[0].observation_count, 5)
        self.assertEqual(len(suppressed), 1)
        self.assertEqual(suppressed[0].source_cluster_ids, (2,))

    def test_final_evidence_threshold_rejects_invalid_value(self):
        with self.assertRaisesRegex(ValueError, 'at least one'):
            partition_by_minimum_observations([], 0)


if __name__ == '__main__':
    unittest.main()
