"""Focused regression tests for the standalone tabletop proposal POC."""
import importlib.util
from pathlib import Path

MODULE = Path(__file__).parents[1] / "tools/tabletop_proposal_poc/tabletop_proposal_poc.py"
SPEC = importlib.util.spec_from_file_location("tabletop_proposal_poc", MODULE)
POC = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POC)

def test_fixed_table_polygon_and_xy_one_to_one_matching():
    table = {"table_id":"table", "center_world_m":[0.0,0.0], "size_local_m":[1.0,2.0], "surface_z_world_m":0.78, "yaw_world_rad":0.0}
    assert POC.table([0.49,0.99,0.8], [table]) is table
    assert POC.table([0.6,0.0,0.8], [table]) is None
    matches, used_proposals, used_truths = POC.match([{"center_map_xyz":[0.03,0.04,1.1]}], [{"ground_truth_world_m":{"x":0.0,"y":0.0,"z":0.78}}])
    assert matches == [(0,0,0.05)]
    assert used_proposals == {0}
    assert used_truths == {0}

def test_one_to_one_match_rejects_second_proposal_for_same_truth():
    proposals = [{"center_map_xyz":[0.01,0.0,0.8]}, {"center_map_xyz":[0.02,0.0,0.8]}]
    truths = [{"ground_truth_world_m":{"x":0.0,"y":0.0,"z":0.78}}]
    matches, used_proposals, used_truths = POC.match(proposals, truths)
    assert matches == [(0,0,0.01)]
    assert used_proposals == {0}
    assert used_truths == {0}
