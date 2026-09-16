#!/usr/bin/env python3
"""Offline, class-agnostic RGB-D tabletop proposal POC.

No ROS or YOLO imports: depth plus recorded map-to-camera TF is converted to
/map points, then fixed tabletop geometry removes the table and 3-D voxel
components become proposals. GT is loaded only after proposal creation to score.
"""
from __future__ import annotations
import argparse, collections, json, math
from pathlib import Path
from typing import Any
import cv2
import numpy as np

# Fixed before inspecting evaluation labels: 3-cm table thickness, 16-bit-mm
# depth, and conservative tabletop object dimensions (not GT-derived tuning).
P = {"pixel_stride": 2, "table_xy_margin_m": .015,
     "calibrated_table_surface_offset_m": -.175, "min_height_above_table_m": .012, "max_height_above_table_m": .45,
     "voxel_size_m": .015, "min_voxels": 5, "min_points": 18,
     "max_extent_m": .45, "stable_frames_required": 5,
     "frames_per_viewpoint": 8, "match_threshold_m": .10}

def load(p: Path) -> Any: return json.loads(p.read_text(encoding="utf-8"))

def rot(q):
    x,y,z,w=(float(q[k]) for k in ("x","y","z","w")); n=math.sqrt(x*x+y*y+z*z+w*w)
    if not n: raise ValueError("zero quaternion")
    x,y,z,w=x/n,y/n,z/n,w/n
    return np.array([[1-2*(y*y+z*z),2*(x*y-z*w),2*(x*z+y*w)], [2*(x*y+z*w),1-2*(x*x+z*z),2*(y*z-x*w)], [2*(x*z-y*w),2*(y*z+x*w),1-2*(x*x+y*y)]])

def map_points(depth, camera, frame):
    s=P["pixel_stride"]; d=depth[::s,::s].astype(float)/1000.; valid=np.isfinite(d)&(d>=.2)&(d<=5.)
    r,c=np.nonzero(valid)
    if not len(r): return np.empty((0,3))
    r*=s; c*=s; z=d[valid]; k=camera["k"]; fx,fy,cx,cy=map(float,(k[0],k[4],k[2],k[5]))
    local=np.column_stack(((c-cx)*z/fx,(r-cy)*z/fy,z)); t=frame.get("map_to_camera")
    if t is None: return np.empty((0,3))
    translation=np.array([float(t["translation"][a]) for a in ("x","y","z")])
    return local@rot(t["rotation"]).T+translation

def table(point, tables):
    for tab in tables:
        dx,dy=point[0]-float(tab["center_world_m"][0]),point[1]-float(tab["center_world_m"][1]); yaw=float(tab["yaw_world_rad"])
        lx=math.cos(yaw)*dx+math.sin(yaw)*dy; ly=-math.sin(yaw)*dx+math.cos(yaw)*dy; sx,sy=map(float,tab["size_local_m"])
        if abs(lx)<=sx/2+P["table_xy_margin_m"] and abs(ly)<=sy/2+P["table_xy_margin_m"]: return tab
    return None

def foreground(points, tables):
    """Remove a fixed calibrated table plane within each fixed tabletop ROI.

    A table-only ROI patch measured 0.175 m below its SDF height because this
    simulator's RGB-D/TF chain uses a stable map-Z convention offset.  The
    offset is a geometry calibration, not an object or GT-derived value.
    """
    keep=[]
    for point in points:
        tab=table(point,tables)
        if tab is None: continue
        plane=float(tab["surface_z_world_m"])+P["calibrated_table_surface_offset_m"]
        height=point[2]-plane
        if P["min_height_above_table_m"]<=height<=P["max_height_above_table_m"]: keep.append(point)
    return np.asarray(keep).reshape((-1,3)) if keep else np.empty((0,3))

def components(points):
    if not len(points): return []
    buckets=collections.defaultdict(list)
    for i,key in enumerate(np.floor(points/P["voxel_size_m"]).astype(int)): buckets[tuple(key)].append(i)
    remaining=set(buckets); groups=[]; neighbors=[(a,b,c) for a in (-1,0,1) for b in (-1,0,1) for c in (-1,0,1)]
    while remaining:
        start=remaining.pop(); queue=[start]; cells=[start]
        while queue:
            x,y,z=queue.pop()
            for a,b,c in neighbors:
                n=(x+a,y+b,z+c)
                if n in remaining: remaining.remove(n); queue.append(n); cells.append(n)
        if len(cells)<P["min_voxels"]: continue
        group=points[[i for cell in cells for i in buckets[cell]]]; extent=group.max(0)-group.min(0)
        if len(group)>=P["min_points"] and extent.max()<=P["max_extent_m"]: groups.append(group)
    return groups

def proposals(depth_path,camera,frame,tables):
    depth=cv2.imread(str(depth_path),cv2.IMREAD_UNCHANGED)
    if depth is None or depth.dtype!=np.uint16: raise ValueError(f"invalid 16-bit depth: {depth_path}")
    out=[]
    for group in components(foreground(map_points(depth,camera,frame),tables)):
        out.append({"center_map_xyz":[round(float(x),6) for x in np.median(group,0)],"extent_xyz_m":[round(float(x),6) for x in group.max(0)-group.min(0)],"point_count":int(len(group))})
    return out

def match(props,truths):
    eligible=[]
    for pi,p in enumerate(props):
        for ti,t in enumerate(truths):
            q=t["ground_truth_world_m"]; e=math.hypot(p["center_map_xyz"][0]-q["x"], p["center_map_xyz"][1]-q["y"])
            if e<P["match_threshold_m"]: eligible.append((e,pi,ti))
    matches=[]; usedp=set(); usedt=set()
    for e,pi,ti in sorted(eligible):
        if pi not in usedp and ti not in usedt: matches.append((pi,ti,e)); usedp.add(pi); usedt.add(ti)
    return matches,usedp,usedt

def selected(run):
    capture=run/"capture"; depth={int(p.stem.rsplit("_",1)[1]) for p in (capture/"runtime_depth").glob("*.png")}; by={1:[],2:[]}
    for line in (capture/"frames.jsonl").read_text().splitlines():
        r=json.loads(line)
        if r["kind"]=="runtime_raw" and r["stamp_ns"] in depth and r.get("phase")=="rotation" and r.get("viewpoint_index") in by: by[r["viewpoint_index"]].append(r)
    selected = {}
    for view, frames in by.items():
        frames = sorted(frames, key=lambda r:r["stamp_ns"])
        count = min(P["frames_per_viewpoint"], len(frames))
        selected[view] = [frames[round(index * (len(frames) - 1) / (count - 1))] for index in range(count)] if count > 1 else frames
    return selected

def analyze(run,tables):
    camera=load(run/"capture"/"camera_info.json"); summary=load(run/"summary.json"); truths=summary["objects"]; views={}; all_frames=[]
    for v,frames in selected(run).items():
        output=[]
        for f in frames:
            stamp=int(f["stamp_ns"]); p=proposals(run/"capture"/"runtime_depth"/f"runtime_depth_{stamp}.png",camera,f,tables); m,up,ut=match(p,truths)
            output.append({"stamp_ns":stamp,"proposals":p,"matches":m,"false_proposal_count":len(p)-len(up),"missed_truth_indices":sorted(set(range(len(truths))) - ut)})
        views[str(v)]=output; all_frames+=output
    stats=[]
    for ti,t in enumerate(truths):
        errors=[e for f in all_frames for _,matched,e in f["matches"] if matched==ti]
        stats.append({"truth_index":ti,"class_name":t["class_name"],"matched_frames":len(errors),"stable":len(errors)>=P["stable_frames_required"],"errors_m":errors,"split_frames":sum(sum(1 for _,matched,_ in f["matches"] if matched==ti)>1 for f in all_frames)})
    return {"run_dir":str(run),"trial_id":summary["trial_id"],"frames":views,"truths":truths,"truth_stats":stats}

def metrics(runs):
    stats=[s for r in runs for s in r["truth_stats"]]; frames=[f for r in runs for v in r["frames"].values() for f in v]; errors=[e for s in stats for e in s["errors_m"]]; classes={}
    for s in stats:
        row=classes.setdefault(s["class_name"],{"gt":0,"stable":0,"frame_matched":0,"errors":[]}); row["gt"]+=1; row["stable"]+=s["stable"]; row["frame_matched"]+=s["matched_frames"]; row["errors"]+=s["errors_m"]
    n=len(stats); return {"ground_truth_count":n,"stable_truth_count":sum(s["stable"] for s in stats),"stable_recall":sum(s["stable"] for s in stats)/n if n else 0,"frame_truth_recall":sum(len(f["matches"]) for f in frames)/(len(frames)*n) if frames and n else 0,"false_proposals":sum(f["false_proposal_count"] for f in frames),"false_proposals_per_frame":sum(f["false_proposal_count"] for f in frames)/len(frames) if frames else 0,"proposal_count_per_frame":[len(f["proposals"]) for f in frames],"error_m":{"min":min(errors) if errors else None,"median":float(np.median(errors)) if errors else None,"max":max(errors) if errors else None,"lt_5cm":sum(e<.05 for e in errors),"5_to_8cm":sum(.05<=e<.08 for e in errors),"8_to_10cm":sum(.08<=e<.1 for e in errors),"gte_10cm":sum(e>=.1 for e in errors)},"classes":{k:{"gt":v["gt"],"stable":v["stable"],"frame_matched":v["frame_matched"],"center_median_m":float(np.median(v["errors"])) if v["errors"] else None,"center_max_m":max(v["errors"]) if v["errors"] else None} for k,v in sorted(classes.items())}}

def main():
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument("--run-dir",action="append",required=True,type=Path); parser.add_argument("--tables",required=True,type=Path); parser.add_argument("--output",required=True,type=Path); args=parser.parse_args()
    runs=[analyze(path,load(args.tables)["tables"]) for path in args.run_dir]; doc={"schema_version":1,"boundary":"class-agnostic offline RGB-D proposals; GT only in post-hoc one-to-one scoring","parameters":P,"runs":runs,"metrics":metrics(runs)}; args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(doc,indent=2)+"\n"); print(json.dumps(doc["metrics"],indent=2))
if __name__=="__main__": main()
