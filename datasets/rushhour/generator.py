from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, asdict
from typing import List, Tuple, Dict, Any, Optional, Callable

from shapely.affinity import rotate, translate
from shapely.geometry import Polygon, box, LineString
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# Official color palette (datasets/README.md)
CERULEAN = "#0090C1"      # Primary brand
RASPBERRY = "#E85D75"     # Highlight / goal (red car)
AQUAMARINE = "#2EC4B6"    # Movable secondary
SUNSHINE = "#FFD670"      # Helper / reference
MIDNIGHT = "#1B263B"      # Outlines / text / static obstacles

# Extended color palette for unique car colors
PURPLE = "#C42E88"
INDIGO = "#5A4FCF"
DARK_ORANGE = "#C46A2E"

# Pool of colors for movable cars (excluding RASPBERRY which is for red_car)
MOVABLE_CAR_COLORS = [
    CERULEAN,      # Blue
    AQUAMARINE,    # Teal
    SUNSHINE,      # Yellow
    PURPLE,   # Purple
    INDIGO,     # Dark teal
    DARK_ORANGE,   # Orange
]

@dataclass
class Pose:
    x: float
    y: float
    theta: float  # radians


@dataclass
class ObjectSpec:
    id: str
    shape: str  # rectangle or polygon
    size: Tuple[float, float] | None = None  # for rectangles (length, width)
    vertices: List[Tuple[float, float]] | None = None  # for polygons in local frame
    pose: Pose | None = None
    movable: bool = True
    color_hex: str | None = None


def _rectangle_polygon(length: float, width: float) -> Polygon:
    half_l = length / 2.0
    half_w = width / 2.0
    return box(-half_l, -half_w, half_l, half_w)


def _convex_polygon(vertices: List[Tuple[float, float]]) -> Polygon:
    # Assumes vertices are ordered counter-clockwise and form a convex polygon
    return Polygon(vertices)


def _place_shape_on_board(local_poly: Polygon, pose: Pose) -> Polygon:
    world = rotate(local_poly, pose.theta * 180.0 / math.pi, origin=(0.0, 0.0), use_radians=False)
    world = translate(world, pose.x, pose.y)
    return world


def _random_pose(rng: random.Random, board_w: float, board_h: float, margin: float, theta_choices: List[float]) -> Pose:
    x = rng.uniform(margin, board_w - margin)
    y = rng.uniform(margin, board_h - margin)
    theta = rng.choice(theta_choices)
    return Pose(x=x, y=y, theta=theta)


def _non_overlapping_place(
    rng: random.Random,
    board_w: float,
    board_h: float,
    existing: List[Polygon],
    local_poly: Polygon,
    theta_choices: List[float],
    max_tries: int = 10000,
    margin_factor: float = 0.4,
    predicate: Optional[Callable[[Pose, Polygon], bool]] = None,
) -> Tuple[Pose, Polygon]:
    # Inflate margin to reduce edge-touch instability
    margin = max(local_poly.bounds[2] - local_poly.bounds[0], local_poly.bounds[3] - local_poly.bounds[1]) * margin_factor
    board = box(0.0 + margin, 0.0 + margin, board_w - margin, board_h - margin)

    for _ in range(max_tries):
        pose = _random_pose(rng, board_w, board_h, margin, theta_choices)
        candidate = _place_shape_on_board(local_poly, pose)
        if not board.contains(candidate):
            continue
        if all(candidate.disjoint(p) for p in existing):
            if predicate is None or predicate(pose, candidate):
                return pose, candidate
    raise RuntimeError("Failed to place object without overlap. Consider relaxing parameters.")

def apply_action(instance: Dict[str, Any], action: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply an action to an instance and return the new state.
    Action: {"object_id": str, "direction": +1/-1, "distance": float}
    Instance: {"objects": [...], "board": {...}}
    """
    import copy
    new_instance = copy.deepcopy(instance)
    
    obj = next(o for o in new_instance["objects"] if o["id"] == action["object_id"])
    axis = obj["local_axis"]
    delta = action["direction"] * action["distance"]
    
    obj["pose"]["x"] += axis[0] * delta
    obj["pose"]["y"] += axis[1] * delta
    
    return new_instance


def _axis_from_theta(theta: float) -> Tuple[float, float]:
    return math.cos(theta), math.sin(theta)


def _translate_poly(poly: Polygon, dx: float, dy: float) -> Polygon:
    return translate(poly, dx, dy)


def _inside_board(board_w: float, board_h: float, poly: Polygon) -> bool:
    board = box(0.0, 0.0, board_w, board_h)
    return board.contains(poly)


def _is_free(candidate: Polygon, idx: int, world_polys: List[Polygon], board_w: float, board_h: float) -> bool:
    if not _inside_board(board_w, board_h, candidate):
        return False
    for j, other in enumerate(world_polys):
        if j == idx:
            continue
        if not candidate.disjoint(other):
            return False
    return True


def _max_translation_along_axis(
    idx: int,
    start_poly: Polygon,
    axis: Tuple[float, float],
    world_polys: List[Polygon],
    board_w: float,
    board_h: float,
    step_initial: float = 0.25,
    epsilon: float = 1e-3,
) -> Tuple[float, float]:
    # positive direction
    t_pos = 0.0
    step = step_initial
    while step > epsilon:
        while True:
            dx = axis[0] * (t_pos + step)
            dy = axis[1] * (t_pos + step)
            cand = _translate_poly(start_poly, dx, dy)
            if _is_free(cand, idx, world_polys, board_w, board_h):
                t_pos += step
            else:
                break
        step *= 0.5

    # negative direction
    t_neg = 0.0
    step = step_initial
    while step > epsilon:
        while True:
            dx = axis[0] * (t_neg - step)
            dy = axis[1] * (t_neg - step)
            cand = _translate_poly(start_poly, dx, dy)
            if _is_free(cand, idx, world_polys, board_w, board_h):
                t_neg -= step
            else:
                break
        step *= 0.5

    return t_neg, t_pos


def _max_translation_along_axis_static(
    start_poly: Polygon,
    axis: Tuple[float, float],
    static_polys: List[Polygon],
    board_w: float,
    board_h: float,
    step_initial: float = 0.25,
    epsilon: float = 1e-3,
) -> Tuple[float, float]:
    def is_free_static(candidate: Polygon) -> bool:
        if not _inside_board(board_w, board_h, candidate):
            return False
        for other in static_polys:
            if not candidate.disjoint(other):
                    return False
        return True
    
    t_pos = 0.0
    step = step_initial
    while step > epsilon:
        while True:
            dx = axis[0] * (t_pos + step)
            dy = axis[1] * (t_pos + step)
            cand = _translate_poly(start_poly, dx, dy)
            if is_free_static(cand):
                t_pos += step
            else:
                break
        step *= 0.5

    t_neg = 0.0
    step = step_initial
    while step > epsilon:
        while True:
            dx = axis[0] * (t_neg - step)
            dy = axis[1] * (t_neg - step)
            cand = _translate_poly(start_poly, dx, dy)
            if is_free_static(cand):
                t_neg -= step
            else:
                break
        step *= 0.5

    return t_neg, t_pos


def generate_initial_state(
    seed: int = 0,
    board_width: float = 10.0,
    board_height: float = 10.0,
    red_car_length: float = 1.8,
    red_car_width: float = 0.9,
    difficulty_stage: int = 2,
) -> Dict[str, Any]:
    rng = random.Random(seed)

    placed_polys: List[Polygon] = []
    objects_out: List[Dict[str, Any]] = []

    # 1) Place exit first: choose a side and size to match red car width
    exit_side = rng.choice(["left", "right", "top", "bottom"])
    # Exit opening matches red car width (with small margin for clearance)
    exit_opening = red_car_width + 0.1
    
    if exit_side in ("left", "right"):
        # Exit on left/right: opening is vertical (height = exit_opening)
        exit_w, exit_h = (0.0, exit_opening)  # No thickness, just an opening
        exit_y = rng.uniform(1.5, board_height - 1.5 - exit_h)
        exit_x = 0.0 if exit_side == "left" else board_width
        # For collision detection, create a small box at the edge
        if exit_side == "left":
            exit_rect = box(-0.5, exit_y, 0.0, exit_y + exit_h)
        else:
            exit_rect = box(board_width, exit_y, board_width + 0.5, exit_y + exit_h)
    else:
        # Exit on top/bottom: opening is horizontal (width = exit_opening)
        exit_w, exit_h = (exit_opening, 0.0)  # No thickness, just an opening
        exit_x = rng.uniform(1.5, board_width - 1.5 - exit_w)
        exit_y = 0.0 if exit_side == "bottom" else board_height
        # For collision detection, create a small box at the edge
        if exit_side == "bottom":
            exit_rect = box(exit_x, -0.5, exit_x + exit_w, 0.0)
        else:
            exit_rect = box(exit_x, board_height, exit_x + exit_w, board_height + 0.5)

    # Store exit info for rendering and solution detection
    # Note: w/h may be 0 for exits that are just openings in the wall.
    # Use opening_start/opening_end for proper detection in verification code.
    if exit_side in ("left", "right"):
        exit_desc = {
            "side": exit_side,
            "x": exit_x,
            "y": exit_y,
            "w": 0.0,
            "h": exit_opening,
            "opening_start": exit_y,
            "opening_end": exit_y + exit_opening,
        }
    else:
        exit_desc = {
            "side": exit_side,
            "x": exit_x,
            "y": exit_y,
            "w": exit_opening,
            "h": 0.0,
            "opening_start": exit_x,
            "opening_end": exit_x + exit_opening,
        }

    # 2) Place red car (target piece) constructively at opposite margin along the corridor
    if exit_side in ("left", "right"):
        red_theta = 0.0  # horizontal axis
        corridor_y = float((exit_rect.bounds[1] + exit_rect.bounds[3]) * 0.5)
        # keep corridor reasonably away from walls for clearance
        corridor_y = max(2.0, min(board_height - 2.0, corridor_y))
        red_x = 1.0 if exit_side == "right" else board_width - 1.0
        red_y = corridor_y
    else:
        red_theta = math.pi / 2.0  # vertical axis
        corridor_x = float((exit_rect.bounds[0] + exit_rect.bounds[2]) * 0.5)
        corridor_x = max(2.0, min(board_width - 2.0, corridor_x))
        red_y = 1.0 if exit_side == "top" else board_height - 1.0
        red_x = corridor_x

    red_local = _rectangle_polygon(red_car_length, red_car_width)
    red_pose = Pose(x=red_x, y=red_y, theta=red_theta)
    red_world = _place_shape_on_board(red_local, red_pose)
    # Ensure inside board
    if not _inside_board(board_width, board_height, red_world):
        raise RuntimeError("Red car placement failed; out of bounds.")
    # Ensure not overlapping (first element so no overlaps yet)

    placed_polys.append(red_world)
    red_axis = _axis_from_theta(red_pose.theta)
    objects_out.append(
        {
            "id": "red_car",
            "shape": "rectangle",
            "size": [red_car_length, red_car_width],
            "pose": asdict(red_pose),
            "local_axis": [red_axis[0], red_axis[1]],
            "movable": True,
            "color_hex": RASPBERRY,
        }
    )

    # Corridor band used for blocking and clearance checks
    if exit_side in ("left", "right"):
        corridor_line = LineString([(min(red_pose.x, exit_rect.centroid.x), red_pose.y), (max(red_pose.x, exit_rect.centroid.x), red_pose.y)])
    else:
        corridor_line = LineString([(red_pose.x, min(red_pose.y, exit_rect.centroid.y)), (red_pose.x, max(red_pose.y, exit_rect.centroid.y))])
    band = corridor_line.buffer(red_car_width * 0.9)

    # 3) Depending on stage, place blockers/distractors
    # Determine total number of movables (excluding red car) for label pool sizing
    num_blockers = 0
    if difficulty_stage >= 2:
        num_blockers = 1
    if difficulty_stage >= 4:
        num_blockers = 2
    num_distractors_stage = 0
    if difficulty_stage >= 3:
        num_distractors_stage = 2 if difficulty_stage <= 4 else 3
    num_secondary_blockers = 1 if difficulty_stage >= 4 else 0
    total_movables = num_blockers + num_distractors_stage + num_secondary_blockers
    
    # Prepare label pool and color pool for non-red movables
    label_pool = [chr(ord('A') + i) for i in range(total_movables)]
    rng.shuffle(label_pool)
    # Use unique colors for each car - make a copy and shuffle
    color_pool = MOVABLE_CAR_COLORS.copy()
    rng.shuffle(color_pool)
    
    if difficulty_stage == 1:
        # no blockers
        pass
    else:
        # helper to place a blocker with clearance assurance
        def place_blocker_between(red_pose: Pose, static_extra: Optional[List[Polygon]] = None) -> Tuple[Pose, Polygon]:
            nonlocal label
            length, width = 2.0, 0.9
            local = _rectangle_polygon(length, width)
            theta_choices_stage2 = [math.radians(d) for d in (-30, -15, 0, 15, 30)]
            tries = 80
            for _ in range(tries):
                # pick position along corridor band
                if exit_side in ("left", "right"):
                    exit_cx = float((exit_rect.bounds[0] + exit_rect.bounds[2]) * 0.5)
                    start_x = min(red_pose.x, exit_cx) + 2.0
                    end_x = max(red_pose.x, exit_cx) - 2.0
                    if end_x <= start_x:
                        break
                    xi = rng.uniform(start_x, end_x)
                    yi = red_pose.y
                else:
                    exit_cy = float((exit_rect.bounds[1] + exit_rect.bounds[3]) * 0.5)
                    start_y = min(red_pose.y, exit_cy) + 2.0
                    end_y = max(red_pose.y, exit_cy) - 2.0
                    if end_y <= start_y:
                        break
                    yi = rng.uniform(start_y, end_y)
                    xi = red_pose.x
                # sample orientation not parallel to red axis (allow near-perpendicular and slanted)
                blocker_theta = rng.choice([t for t in theta_choices_stage2 if abs(((t - red_theta) % math.pi)) > math.radians(10)])
                pose_try = Pose(x=xi, y=yi, theta=blocker_theta)
                world_try = _place_shape_on_board(local, pose_try)
                if not _inside_board(board_width, board_height, world_try):
                    continue
                if not all(world_try.disjoint(p) for p in placed_polys):
                    continue
                # must block the corridor band initially
                if world_try.disjoint(band):
                    continue
                # ensure a clearable position exists along its axis
                axis_try = _axis_from_theta(pose_try.theta)
                static_for_blocker = [red_world]
                if static_extra:
                    static_for_blocker.extend(static_extra)
                tmin, tmax = _max_translation_along_axis_static(world_try, axis_try, static_for_blocker, board_width, board_height)
                # candidate end positions
                cand_worlds = [
                    _translate_poly(world_try, axis_try[0] * tmin, axis_try[1] * tmin),
                    _translate_poly(world_try, axis_try[0] * tmax, axis_try[1] * tmax),
                ]
                ok = any(w.disjoint(band) for w in cand_worlds)
                if ok:
                    return pose_try, world_try
            raise RuntimeError("Failed to place a solvable blocker.")

        pose, world = place_blocker_between(red_pose)
        placed_polys.append(world)
        axis = _axis_from_theta(pose.theta)
        # Assign randomized label and unique color for blocker A
        label = label_pool.pop()
        color = color_pool.pop()
        objects_out.append(
            {
                "id": "blocker_A",
                "shape": "rectangle",
                "size": [2.0, 0.9],
                "pose": asdict(pose),
                "local_axis": [axis[0], axis[1]],
                "movable": True,
                "color_hex": color,
                "label": label,
            }
        )

        # Stage 4+: place a second blocker as well
        if difficulty_stage >= 4:
            # For stage 4, don't treat first blocker as static (allow them to independently clear)
            # For stage 5, we do want them to potentially interact
            static_for_second = [world] if difficulty_stage >= 4 else None
            pose2, world2 = place_blocker_between(red_pose, static_extra=static_for_second)
            placed_polys.append(world2)
            axis2 = _axis_from_theta(pose2.theta)
            # Assign randomized label and unique color for blocker B
            label_b = label_pool.pop()
            color_b = color_pool.pop()
            objects_out.append(
                {
                    "id": "blocker_B",
                    "shape": "rectangle",
                    "size": [2.0, 0.9],
                    "pose": asdict(pose2),
                    "local_axis": [axis2[0], axis2[1]],
                    "movable": True,
                    "color_hex": color_b,
                    "label": label_b,
                }
            )

    # 4) Stage 3+: add a static obstacle to restrict blocker movement (e.g., allow only one clearing direction)
    if difficulty_stage >= 3:
        # place a static rectangular obstacle near the blocker so it can only move one way
        obs_length = rng.uniform(1.6, 2.4)
        obs_width = rng.uniform(0.8, 1.1)
        obs_local = _rectangle_polygon(obs_length, obs_width)
        def _restrict_pose(pose: Pose, candidate: Polygon) -> bool:
            # keep obstacle out of the red corridor band but near blocker to constrain it
            # near blocker bounding box expanded
            # choose the last placed blocker-like shape
            blocker_world = placed_polys[-1]
            return candidate.disjoint(band) and candidate.distance(blocker_world) < 1.5
        obs_pose, obs_world = _non_overlapping_place(
            rng, board_width, board_height, placed_polys, obs_local, theta_choices=[0.0], predicate=_restrict_pose
        )
        placed_polys.append(obs_world)
        objects_out.append(
            {
                "id": "static_obs_0",
                "shape": "rectangle",
                "size": [obs_length, obs_width],
                "pose": asdict(obs_pose),
                "local_axis": [1.0, 0.0],
                "movable": False,
                "color_hex": MIDNIGHT,
            }
        )

        # Also add distractor cars away from corridor band
        # continue using color_pool and label_pool for unique colors across movables
        for k in range(num_distractors_stage):
            d_length = rng.uniform(1.6, 2.4)
            d_width = rng.uniform(0.8, 1.1)
            d_local = _rectangle_polygon(d_length, d_width)
            d_theta = rng.choice([math.radians(d) for d in (-30, -15, 0, 15, 30)])
            def _away_band(pose: Pose, candidate: Polygon) -> bool:
                return candidate.disjoint(band)
            d_pose, d_world = _non_overlapping_place(
                rng, board_width, board_height, placed_polys, d_local, theta_choices=[d_theta], predicate=_away_band
            )
            placed_polys.append(d_world)
            d_axis = _axis_from_theta(d_pose.theta)
            d_color = color_pool.pop()
            d_label = label_pool.pop()
            objects_out.append(
                {
                    "id": f"distractor_{k}",
                    "shape": "rectangle",
                    "size": [d_length, d_width],
                    "pose": asdict(d_pose),
                    "local_axis": [d_axis[0], d_axis[1]],
                    "movable": True,
                    "color_hex": d_color,
                    "label": d_label,
            }
        )

    # Compute drive segments for movables along their local axes
    # Build world polygons aligned with objects_out order
    world_polys: List[Polygon] = []
    for obj in objects_out:
        if obj["shape"] == "rectangle" and obj.get("size"):
            local = _rectangle_polygon(obj["size"][0], obj["size"][1])
        elif obj["shape"] == "polygon" and obj.get("vertices"):
            local = _convex_polygon([(float(x), float(y)) for x, y in obj["vertices"]])
        else:
            local = _rectangle_polygon(1.0, 1.0)
        p = Pose(**obj["pose"])  # type: ignore[arg-type]
        world_polys.append(_place_shape_on_board(local, p))

    for i, obj in enumerate(objects_out):
        if not obj.get("movable", True):
            continue
        axis = tuple(obj["local_axis"])  # type: ignore[assignment]
        if obj["id"] == "red_car":
            # compute against statics only (no blocker), enforcing that once blocker moves, red can pass
            static_polys = [w for j, w in enumerate(world_polys) if not objects_out[j].get("movable", True)]
            t_min, t_max = _max_translation_along_axis_static(world_polys[i], axis, static_polys, board_width, board_height)
        else:
            t_min, t_max = _max_translation_along_axis(i, world_polys[i], axis, world_polys, board_width, board_height)
        cx = obj["pose"]["x"]
        cy = obj["pose"]["y"]
        line_start = [cx + t_min * axis[0], cy + t_min * axis[1]]
        line_end = [cx + t_max * axis[0], cy + t_max * axis[1]]
        obj["drive_segment"] = {"t_min": t_min, "t_max": t_max, "line": [line_start, line_end]}

    # Stage 5: Now place secondary blocker using computed drive segments
    if difficulty_stage >= 4 and num_blockers > 0:
        # Find a corridor blocker to block (prefer the first one placed)
        corridor_blocker_candidates = []
        for i, obj in enumerate(objects_out):
            if not obj.get("movable", True) or obj["id"] == "red_car":
                continue
            if world_polys[i].intersects(band):
                corridor_blocker_candidates.append(i)
        
        if corridor_blocker_candidates:
            primary_blocker_idx = corridor_blocker_candidates[0]
            primary_blocker = objects_out[primary_blocker_idx]
            primary_axis = tuple(primary_blocker["local_axis"])
            primary_ds = primary_blocker.get("drive_segment", {})
            primary_t_min, primary_t_max = primary_ds.get("t_min", 0.0), primary_ds.get("t_max", 0.0)
            primary_pose = Pose(**primary_blocker["pose"])
            
            if primary_blocker["shape"] == "rectangle" and primary_blocker.get("size"):
                primary_local = _rectangle_polygon(primary_blocker["size"][0], primary_blocker["size"][1])
            else:
                primary_local = _rectangle_polygon(2.0, 0.9)
            primary_world = _place_shape_on_board(primary_local, primary_pose)
            
            # Determine which direction clears the corridor
            dx_min = primary_axis[0] * primary_t_min
            dy_min = primary_axis[1] * primary_t_min
            cand_min = _translate_poly(primary_world, dx_min, dy_min)
            
            dx_max = primary_axis[0] * primary_t_max
            dy_max = primary_axis[1] * primary_t_max
            cand_max = _translate_poly(primary_world, dx_max, dy_max)
            
            # Try multiple positions along the clearing path
            secondary_placed = False
            for attempt_ratio in [0.65, 0.5, 0.75, 0.4, 0.85]:
                # Pick clearing direction
                if cand_min.disjoint(band):
                    block_t = primary_t_min * attempt_ratio
                elif cand_max.disjoint(band):
                    block_t = primary_t_max * attempt_ratio
                else:
                    continue
                
                # Try multiple orientations
                for secondary_theta in [math.radians(d) for d in (-30, -15, 0, 15, 30)]:
                    secondary_length = rng.uniform(1.8, 2.2)
                    secondary_width = rng.uniform(0.8, 1.0)
                    secondary_local = _rectangle_polygon(secondary_length, secondary_width)
                    
                    sec_x = primary_pose.x + primary_axis[0] * block_t
                    sec_y = primary_pose.y + primary_axis[1] * block_t
                    secondary_pose = Pose(x=sec_x, y=sec_y, theta=secondary_theta)
                    secondary_world = _place_shape_on_board(secondary_local, secondary_pose)
                    
                    # Check if placement is valid and actually blocks the primary
                    if _inside_board(board_width, board_height, secondary_world) and all(secondary_world.disjoint(p) for p in placed_polys):
                        # Verify it blocks the primary blocker's clearance path
                        if cand_min.disjoint(band):
                            blocks_path = not cand_min.disjoint(secondary_world)
                        else:
                            blocks_path = not cand_max.disjoint(secondary_world)
                        
                        if blocks_path:
                            placed_polys.append(secondary_world)
                            secondary_axis = _axis_from_theta(secondary_pose.theta)
                            label_sec = label_pool.pop() if label_pool else "X"
                            color_sec = color_pool.pop() if color_pool else DARK_ORANGE
                            
                            secondary_obj = {
                                "id": "blocker_secondary",
                                "shape": "rectangle",
                                "size": [secondary_length, secondary_width],
                                "pose": asdict(secondary_pose),
                                "local_axis": [secondary_axis[0], secondary_axis[1]],
                                "movable": True,
                                "color_hex": color_sec,
                                "label": label_sec,
                            }
                            objects_out.append(secondary_obj)
                            
                            # Compute drive segment for secondary blocker
                            world_polys.append(secondary_world)
                            sec_idx = len(objects_out) - 1
                            t_min_sec, t_max_sec = _max_translation_along_axis(sec_idx, secondary_world, secondary_axis, world_polys, board_width, board_height)
                            cx_sec = secondary_pose.x
                            cy_sec = secondary_pose.y
                            line_start_sec = [cx_sec + t_min_sec * secondary_axis[0], cy_sec + t_min_sec * secondary_axis[1]]
                            line_end_sec = [cx_sec + t_max_sec * secondary_axis[0], cy_sec + t_max_sec * secondary_axis[1]]
                            secondary_obj["drive_segment"] = {"t_min": t_min_sec, "t_max": t_max_sec, "line": [line_start_sec, line_end_sec]}
                            secondary_placed = True
                            break
                
                if secondary_placed:
                    break

    instance = {
        "board": {"width": board_width, "height": board_height, "exits": [exit_desc]},
        "objects": objects_out,
    }
    return instance


def generate_initial_state_json(**kwargs: Any) -> str:
    return json.dumps(generate_initial_state(**kwargs), indent=2)


def compute_greedy_solution(instance: Dict[str, Any], max_actions: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Shortest-plan BFS under push-until-collision semantics:
      - Non-red movables: can only move to t_neg or t_pos (extrema) along their local axis.
      - Red car: can also 'stop at exit' if the exit lies within its free bound in a direction.
    Returns a list of actions: [{"object_id": str, "direction": +1/-1, "distance": float}, ...]
    """
    import copy
    objects0 = instance["objects"]
    board_w = instance["board"]["width"]
    board_h = instance["board"]["height"]
    exit_rect = box(
        instance["board"]["exits"][0]["x"],
        instance["board"]["exits"][0]["y"],
        instance["board"]["exits"][0]["x"] + instance["board"]["exits"][0]["w"],
        instance["board"]["exits"][0]["y"] + instance["board"]["exits"][0]["h"],
    )

    # -------- helpers --------------------------------------------------------

    def world_polys_for(objs: List[Dict[str, Any]]) -> List[Polygon]:
        wps = []
        for o in objs:
            if o["shape"] == "rectangle" and o.get("size"):
                local = _rectangle_polygon(o["size"][0], o["size"][1])
            elif o["shape"] == "polygon" and o.get("vertices"):
                local = _convex_polygon([(float(x), float(y)) for x, y in o["vertices"]])
            else:
                local = _rectangle_polygon(1.0, 1.0)
            p = Pose(**o["pose"])
            wps.append(_place_shape_on_board(local, p))
        return wps

    def recompute_extrema(idx: int, objs: List[Dict[str, Any]], wps: List[Polygon]) -> Tuple[float, float]:
        axis = tuple(objs[idx]["local_axis"])
        t_neg, t_pos = _max_translation_along_axis(
            idx, wps[idx], axis, wps, board_w, board_h, step_initial=0.25, epsilon=1e-3
        )
        return t_neg, t_pos

    def move_poly(poly: Polygon, axis: Tuple[float, float], t: float) -> Polygon:
        return _translate_poly(poly, axis[0] * t, axis[1] * t)

    def is_solved(state: Dict[str, Any]) -> bool:
        """Check if red car has reached the board edge at the exit."""
        red = next(o for o in state["objects"] if o["id"] == "red_car")
        rp = world_polys_for([red])[0]
        bounds = rp.bounds  # (minx, miny, maxx, maxy)
        
        exit_side = instance["board"]["exits"][0]["side"]
        tolerance = 0.1  # Small tolerance for floating point comparison
        
        if exit_side == "right":
            return bounds[2] >= board_w - tolerance  # maxx at right edge
        elif exit_side == "left":
            return bounds[0] <= tolerance  # minx at left edge
        elif exit_side == "top":
            return bounds[3] >= board_h - tolerance  # maxy at top edge
        elif exit_side == "bottom":
            return bounds[1] <= tolerance  # miny at bottom edge
        return False

    def state_hash(state: Dict[str, Any]) -> str:
        parts = []
        for o in state["objects"]:
            if not o.get("movable", True):
                continue
            x = f"{o['pose']['x']:.3f}"
            y = f"{o['pose']['y']:.3f}"
            parts.append(o["id"] + ":" + x + "," + y)
        return "|".join(sorted(parts))

    # Calculate distance for red car to reach the board edge (exit)
    def distance_to_reach_exit(start_poly: Polygon, axis: Tuple[float, float], t_hi: float, eps: float = 1e-3) -> Optional[float]:
        """
        Calculate the distance needed for the red car's front to reach the board edge at the exit.
        The car should move until its front edge touches the border.
        Returns None if the car can't reach the exit within t_hi.
        """
        if t_hi <= eps:
            return None
        
        exit_side = instance["board"]["exits"][0]["side"]
        
        # Get the car's bounding box
        bounds = start_poly.bounds  # (minx, miny, maxx, maxy)
        
        # Calculate how far the car needs to move for its front to reach the edge
        if exit_side == "right":
            # Car moves right (+x), front is at maxx, needs to reach board_w
            current_front = bounds[2]
            target = board_w
            needed = target - current_front
        elif exit_side == "left":
            # Car moves left (-x), front is at minx, needs to reach 0
            current_front = bounds[0]
            target = 0
            needed = current_front - target  # Will be positive
        elif exit_side == "top":
            # Car moves up (+y), front is at maxy, needs to reach board_h
            current_front = bounds[3]
            target = board_h
            needed = target - current_front
        elif exit_side == "bottom":
            # Car moves down (-y), front is at miny, needs to reach 0
            current_front = bounds[1]
            target = 0
            needed = current_front - target  # Will be positive
        else:
            return None
        
        # The movement along axis to achieve this distance
        # For axis-aligned movement, needed distance = t * |axis component|
        if exit_side in ("left", "right"):
            axis_component = abs(axis[0])
        else:
            axis_component = abs(axis[1])
        
        if axis_component < eps:
            return None  # Car not moving in the right direction
        
        t_needed = needed / axis_component
        
        if t_needed <= eps:
            return 0.0  # Already at exit
        if t_needed > t_hi + eps:
            return None  # Can't reach within allowed range
        
        return min(t_needed, t_hi)

    # Precompute red index for convenience
    red_idx0 = next(i for i, o in enumerate(objects0) if o["id"] == "red_car")

    # -------- BFS over atomic push-until-collision moves ---------------------
    from collections import deque
    q = deque([(copy.deepcopy(instance), [])])
    seen = set()
    max_depth = max_actions if max_actions is not None else 5

    while q:
        state, actions = q.popleft()
        if len(actions) > max_depth:
            continue

        h = state_hash(state)
        if h in seen:
            continue
        seen.add(h)

        if is_solved(state):
            return actions

        objs = state["objects"]
        wps = world_polys_for(objs)

        # Generate extreme moves for each movable (and red's stop-at-exit)
        # Sort for determinism: by id, then by direction (-1 before +1) when enqueuing
        candidates: List[Tuple[int, int, float, str]] = []  # (idx, dir, dist, obj_id)

        for i, obj in enumerate(objs):
            if not obj.get("movable", True):
                continue
            axis = tuple(obj["local_axis"])
            t_neg, t_pos = recompute_extrema(i, objs, wps)
            # Non-zero extremes only
            if t_neg < -1e-3:
                candidates.append((i, -1, abs(t_neg), obj["id"]))
            if t_pos > 1e-3:
                candidates.append((i, +1, t_pos, obj["id"]))

            # Red car extra: snap to reach the exit (board edge)
            if i == red_idx0:
                # positive direction snap
                t_hit_pos = distance_to_reach_exit(wps[i], axis, max(0.0, t_pos))
                if t_hit_pos is not None and t_hit_pos > 1e-3:
                    candidates.append((i, +1, float(f"{t_hit_pos:.3f}"), obj["id"]))
                # negative direction snap
                # reuse by flipping axis & bound to positive search
                if t_neg < -1e-3:
                    t_hit_neg = distance_to_reach_exit(wps[i], (-axis[0], -axis[1]), abs(t_neg))
                    if t_hit_neg is not None and t_hit_neg > 1e-3:
                        candidates.append((i, -1, float(f"{t_hit_neg:.3f}"), obj["id"]))

        # Deduplicate potentially identical moves per object/direction (e.g., snap == extreme)
        keyset = set()
        deduped: List[Tuple[int, int, float, str]] = []
        for idx, d, dist, oid in candidates:
            k = (idx, d, float(f"{dist:.3f}"))
            if k not in keyset:
                keyset.add(k)
                deduped.append((idx, d, k[2], oid))

        # Stable ordering helps reproducibility
        deduped.sort(key=lambda t: (t[3], t[1], t[2]))

        # Enqueue successors
        for idx, direction, dist, _oid in deduped:
            action = {"object_id": objs[idx]["id"], "direction": direction, "distance": dist}
            new_state = apply_action(state, action)
            new_actions = actions + [action]
            q.append((new_state, new_actions))

    # Should be rare with the constructive generator; keep your fallback just in case
    raise RuntimeError("BFS failed to find a solution")


def render_instance(instance: Dict[str, Any], figsize: Tuple[int, int] = (6, 6)) -> plt.Figure:
    bw = instance["board"]["width"]
    bh = instance["board"]["height"]

    fig, ax = plt.subplots(figsize=figsize)
    ax.set_aspect('equal')
    # Extend view slightly to show cars exiting
    ax.set_xlim(-0.2, bw + 0.2)
    ax.set_ylim(-0.2, bh + 0.2)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_frame_on(False)  # We'll draw our own border with gap
    
    # Draw board border with gap at exit
    border_color = MIDNIGHT
    border_width = 2.0
    
    for ex in instance["board"]["exits"]:
        side = ex["side"]
        opening_start = ex.get("opening_start", ex["y"] if side in ("left", "right") else ex["x"])
        opening_end = ex.get("opening_end", opening_start + (ex["h"] if side in ("left", "right") else ex["w"]))
        
        if side == "left":
            # Left border with gap
            ax.plot([0, 0], [0, opening_start], color=border_color, linewidth=border_width, solid_capstyle='butt')
            ax.plot([0, 0], [opening_end, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')
            # Other borders (complete)
            ax.plot([0, bw], [0, 0], color=border_color, linewidth=border_width, solid_capstyle='butt')  # bottom
            ax.plot([bw, bw], [0, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')  # right
            ax.plot([0, bw], [bh, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')  # top
        elif side == "right":
            # Right border with gap
            ax.plot([bw, bw], [0, opening_start], color=border_color, linewidth=border_width, solid_capstyle='butt')
            ax.plot([bw, bw], [opening_end, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')
            # Other borders (complete)
            ax.plot([0, bw], [0, 0], color=border_color, linewidth=border_width, solid_capstyle='butt')  # bottom
            ax.plot([0, 0], [0, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')  # left
            ax.plot([0, bw], [bh, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')  # top
        elif side == "bottom":
            # Bottom border with gap
            ax.plot([0, opening_start], [0, 0], color=border_color, linewidth=border_width, solid_capstyle='butt')
            ax.plot([opening_end, bw], [0, 0], color=border_color, linewidth=border_width, solid_capstyle='butt')
            # Other borders (complete)
            ax.plot([0, 0], [0, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')  # left
            ax.plot([bw, bw], [0, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')  # right
            ax.plot([0, bw], [bh, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')  # top
        elif side == "top":
            # Top border with gap
            ax.plot([0, opening_start], [bh, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')
            ax.plot([opening_end, bw], [bh, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')
            # Other borders (complete)
            ax.plot([0, 0], [0, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')  # left
            ax.plot([bw, bw], [0, bh], color=border_color, linewidth=border_width, solid_capstyle='butt')  # right
            ax.plot([0, bw], [0, 0], color=border_color, linewidth=border_width, solid_capstyle='butt')  # bottom
        
        # Draw green exit marker - slightly larger than opening and peaking into the board
        exit_padding = 0.15  # How much larger than the opening on each side
        exit_depth = 0.4     # How far the marker extends outside the board
        exit_peek = 0.2      # How far the marker peeks into the board
        
        if side == "left":
            # Marker extends from outside (-exit_depth) to inside (exit_peek)
            ax.add_patch(plt.Rectangle(
                (-exit_depth, opening_start - exit_padding),
                exit_depth + exit_peek,  # width
                (opening_end - opening_start) + 2 * exit_padding,  # height
                color="#81C784", alpha=0.8, zorder=0
            ))
        elif side == "right":
            ax.add_patch(plt.Rectangle(
                (bw - exit_peek, opening_start - exit_padding),
                exit_depth + exit_peek,  # width
                (opening_end - opening_start) + 2 * exit_padding,  # height
                color="#81C784", alpha=0.8, zorder=0
            ))
        elif side == "bottom":
            ax.add_patch(plt.Rectangle(
                (opening_start - exit_padding, -exit_depth),
                (opening_end - opening_start) + 2 * exit_padding,  # width
                exit_depth + exit_peek,  # height
                color="#81C784", alpha=0.8, zorder=0
            ))
        elif side == "top":
            ax.add_patch(plt.Rectangle(
                (opening_start - exit_padding, bh - exit_peek),
                (opening_end - opening_start) + 2 * exit_padding,  # width
                exit_depth + exit_peek,  # height
                color="#81C784", alpha=0.8, zorder=0
            ))

    for obj in instance["objects"]:
        color = obj.get("color_hex") or ("#1976D2" if obj.get("movable", True) else "#607D8B")
        # Axis rail clipped to board boundaries
        if obj.get("movable", True) and obj.get("local_axis"):
            axx, axy = obj["local_axis"]
            cx = obj["pose"]["x"]
            cy = obj["pose"]["y"]
            
            # Calculate intersection with board boundaries
            # Find t values where the line crosses each boundary
            t_values = []
            
            # Line: (cx + axx*t, cy + axy*t)
            # For each boundary, solve for t
            eps = 1e-9
            if abs(axx) > eps:
                t_values.append((0 - cx) / axx)   # left boundary (x=0)
                t_values.append((bw - cx) / axx)  # right boundary (x=bw)
            if abs(axy) > eps:
                t_values.append((0 - cy) / axy)   # bottom boundary (y=0)
                t_values.append((bh - cy) / axy)  # top boundary (y=bh)
            
            # Filter t values to those that result in points inside the board
            valid_t = []
            for t in t_values:
                px, py = cx + axx * t, cy + axy * t
                if -eps <= px <= bw + eps and -eps <= py <= bh + eps:
                    valid_t.append(t)
            
            if len(valid_t) >= 2:
                t_min, t_max = min(valid_t), max(valid_t)
                x1, y1 = cx + axx * t_min, cy + axy * t_min
                x2, y2 = cx + axx * t_max, cy + axy * t_max
                # Clamp to board boundaries
                x1, y1 = max(0, min(bw, x1)), max(0, min(bh, y1))
                x2, y2 = max(0, min(bw, x2)), max(0, min(bh, y2))
                
                ax.plot([x1, x2], [y1, y2], color=color, linewidth=1.6, alpha=0.35, linestyle='dashed', zorder=1)
            
            # Original, minimal arrow centered in the car (no outline)
            ax.arrow(cx, cy, axx * 0.6, axy * 0.6, head_width=0.2, head_length=0.35, length_includes_head=True, color=MIDNIGHT, alpha=0.5, zorder=1.5, linewidth=0)

            # Draw objects and drive rails
    for obj in instance["objects"]:
        color = obj.get("color_hex") or ("#1976D2" if obj.get("movable", True) else "#607D8B")
        if obj["shape"] == "rectangle" and obj.get("size"):
            local = _rectangle_polygon(obj["size"][0], obj["size"][1])
        else:
            if obj["shape"] == "polygon" and obj.get("vertices"):
                local = _convex_polygon([(float(x), float(y)) for x, y in obj["vertices"]])
            else:
                local = _rectangle_polygon(1.0, 1.0)
        pose = Pose(**obj["pose"])  # type: ignore[arg-type]
        world = _place_shape_on_board(local, pose)
        x, y = world.exterior.xy
        ax.fill(x, y, color=color, alpha=1.0, linewidth=1.0, edgecolor="#263238")

        # labels for movables (above arrows)
        if obj.get("movable", True):
            lbl = obj.get("label") if obj["id"] != "red_car" else "R"
            ax.text(pose.x, pose.y, lbl, color="#FFFFFF", fontsize=10, ha='center', va='center', weight='bold', bbox=dict(boxstyle="circle,pad=0.15", fc="#00000080", ec="none"), zorder=3)

    # No title per style guide
    fig.tight_layout()
    return fig


def plot_from_metadata(
    metadata_path: str,
    figsize: Tuple[int, int] = (6, 6),
    save_path: Optional[str] = None,
    show: bool = True
) -> plt.Figure:
    """Load instance metadata from a JSON file and render it.
    
    Args:
        metadata_path: Path to the metadata.json file.
        figsize: Figure size as (width, height) tuple.
        save_path: Optional path to save the rendered figure.
        show: If True, display the figure using plt.show().
    
    Returns:
        The matplotlib Figure object.
    """
    with open(metadata_path, "r") as f:
        instance = json.load(f)
    
    fig = render_instance(instance, figsize=figsize)
    
    if save_path:
        fig.savefig(save_path, dpi=150, bbox_inches="tight")
    
    if show:
        plt.show()
    
    return fig


if __name__ == "__main__":
    import os
    metadata_paths = ["output/level_01/puzzle_0014/metadata.json",
            "output/level_03/puzzle_0024/metadata.json",
            "output/level_05/puzzle_0021/metadata.json"]
    for metadata_path in metadata_paths:
        save_path = 'output_fig/'+metadata_path.replace("output/", "").replace("metadata.json", "initial.png")
        # Create the subdir for save path
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plot_from_metadata(metadata_path, save_path=save_path)
        print(f"Saved to {save_path}")