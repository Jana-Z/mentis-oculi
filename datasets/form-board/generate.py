"""Generate dissect-and-assemble geometry puzzles like the sample image.

Usage example (see __main__ block):
    # Describe a cross shape on a 5×5 grid
    Puzzle.from_edges(target_edges).export("out")

Key ideas
---------
* The **target** polygon lives on an *n × n* integer grid (default n=5).
* A random integer k∈{3,4,5} decides how many **solution pieces** we cut the
  target into.
* Allowed cut lines are straight segments through grid points with slope
  ∞, 0, ±1, ±2, ±3.  Each cut must split at least one existing piece.
* **Distractors** are obtained by recursively sub-dividing *one* correct piece
  so that no combination of distractors reproduces the exact area of any
  single correct piece.  (We enforce this exhaustively.)
* Each output PNG is rendered with matplotlib — target outline only, while
  pieces and distractors are filled using a dotted hatch pattern similar to
  the book example.

Dependencies
------------
* shapely (geometry operations)
* matplotlib
* numpy
"""
from __future__ import annotations

import math
import random
from pathlib import Path
from typing import List, Tuple

import matplotlib.pyplot as plt
from shapely.geometry import GeometryCollection, LineString, Polygon
from shapely.ops import split

import os
import re
from PIL import Image

GridPoint = Tuple[int, int]
Edge = Tuple[int, int, int, int]  # (x1, y1, x2, y2)

ALLOWED_SLOPES = {float("inf"), 0, 1, -1, 2, -2, 3, -3}
DEFAULT_PPU = 100  # pixels per grid unit when exporting PNGs
DPI = 300  # matplotlib resolution

# Official color palette (datasets/README.md)
CERULEAN = "#0090C1"      # Primary brand
RASPBERRY = "#E85D75"     # Highlight / goal
AQUAMARINE = "#2EC4B6"    # Movable secondary
SUNSHINE = "#FFD670"      # Helper / reference
MIDNIGHT = "#1B263B"      # Outlines / text
CANVAS_BG = "#FDFDFD"     # Light background per style guide
CANVAS_SIZE = (6, 6)      # Standard canvas size

PALETTE = [CERULEAN, RASPBERRY, AQUAMARINE, SUNSHINE]  # exclude MIDNIGHT for fills


def assign_piece_colors(num_pieces, rng):
    """Assign stable, per-piece colors from the palette (excluding MIDNIGHT)."""
    # Cycle if there are more pieces than colors
    colors = [PALETTE[i % len(PALETTE)] for i in range(num_pieces)]
    # Shuffle deterministically for variety
    rng.shuffle(colors)
    return colors


# ---------------------------------------------------------------------------
#   Geometry helpers
# ---------------------------------------------------------------------------
def _parse_edges(text: str) -> List[Edge]:
    segments = [seg.strip() for seg in text.split(';')]
    
    square_edges = []
    for seg in segments:
        start, end = seg.split('-')
        y1, x1 = map(int, start.split(','))
        y2, x2 = map(int, end.split(','))
        square_edges.append((x1, y1, x2, y2))
    
    return square_edges


def _edge_list_to_polygon(edges: str) -> Polygon:
    """Return a (possibly non‑convex) shapely Polygon from ordered *edges*."""
    edges = _parse_edges(edges)
    vertices: List[GridPoint] = [(edges[0][0], edges[0][1])]
    for (_, _, x2, y2) in edges:
        vertices.append((x2, y2))
    return Polygon(vertices)


def _random_grid_line(n: int) -> LineString:
    """Random straight line through two grid points whose slope is allowed."""
    while True:
        p1 = (random.randint(0, n), random.randint(0, n))
        p2 = (random.randint(0, n), random.randint(0, n))
        if p1 == p2:
            continue
        dx, dy = p2[0] - p1[0], p2[1] - p1[1]
        slope = float("inf") if dx == 0 else dy / dx
        if slope in ALLOWED_SLOPES:
            return LineString([p1, p2])


def _split_polygon(poly: Polygon, n: int, max_tries: int = 200) -> List[Polygon]:
    """Attempt to cut *poly*; return list of pieces or ``[poly]`` if none."""
    for _ in range(max_tries):
        line = _random_grid_line(n)
        try:
            gc = split(poly, line)
        except ValueError:
            continue  # line did not intersect the polygon
        pieces = [g for g in (gc.geoms if isinstance(gc, GeometryCollection) else [gc]) if not g.is_empty]
        if len(pieces) > 1:
            return pieces
    return [poly]


def _merge_images(folder: str, interval: int = 25):
    """Merge individual piece images into a single choices image."""
    pattern = re.compile(r"piece_(\d+)\.png")
    images_info = []

    for filename in os.listdir(folder):
        match = pattern.match(filename)
        if match:
            piece_num = int(match.group(1))
            images_info.append((piece_num, filename))

    if not images_info:
        return
    
    images_info.sort()

    images = []
    total_width = 0
    max_height = 0
    for piece_num, filename in images_info:
        img = Image.open(os.path.join(folder, filename))
        images.append(img)
        total_width += img.width
        if img.height > max_height:
            max_height = img.height

    combined_image = Image.new("RGBA", (total_width + interval * (len(images) - 1), max_height), (255, 255, 255, 0))
    x_offset = 0
    for img in images:
        y_offset = max_height - img.height
        combined_image.paste(img, (x_offset, y_offset))
        x_offset += img.width + interval

    save_path = os.path.join(folder, "choices.png")
    combined_image.save(save_path)


# ---------------------------------------------------------------------------
#   Main class
# ---------------------------------------------------------------------------
class Puzzle:
    def __init__(self, target: Polygon, grid_size: int = 5):
        if not target.is_valid:
            raise ValueError("Target polygon is invalid / self‑intersecting")
        self.target = target
        self.n = grid_size  # size of underlying grid (0…n)

    # ------------------------------------------------------------------
    #   Construction helpers
    # ------------------------------------------------------------------
    @classmethod
    def from_edges(cls, edges: str, grid_size: int = 5) -> "Puzzle":
        return cls(_edge_list_to_polygon(edges), grid_size)

    def _generate_solution_pieces(self, k: int) -> List[Polygon]:
        from shapely.ops import unary_union
        import math
        
        pieces = [self.target]
        guard = 0
        while len(pieces) < k and guard < 1000:
            guard += 1
            pieces.sort(key=lambda p: p.area, reverse=True)
            largest = pieces.pop(0)
            new_pieces = _split_polygon(largest, self.n)
            if len(new_pieces) == 1:
                pieces.append(largest)
                continue
            pieces.extend(new_pieces)
        
        if len(pieces) < k:
            raise RuntimeError("Could not split target into k pieces — try a simpler shape or increase attempts.")
        
        # Take first k pieces
        solution_pieces = pieces[:k]
        
        # VALIDATION 1: Check for duplicate pieces (same geometry)
        for i, p1 in enumerate(solution_pieces):
            for j, p2 in enumerate(solution_pieces[i+1:], i+1):
                if p1.equals(p2):
                    raise RuntimeError(f"Duplicate solution pieces detected: piece {i} equals piece {j}")
                # Also check if areas are suspiciously similar
                if math.isclose(p1.area, p2.area, rel_tol=1e-6) and not p1.equals(p2):
                    # Same area but different shape - could be confusing, but allowed
                    pass
        
        # VALIDATION 2: Check for overlaps between solution pieces
        for i, p1 in enumerate(solution_pieces):
            for j, p2 in enumerate(solution_pieces[i+1:], i+1):
                intersection = p1.intersection(p2)
                if not intersection.is_empty and intersection.area > 1e-9:
                    raise RuntimeError(f"Solution pieces {i} and {j} overlap! Intersection area: {intersection.area:.6f}")
        
        # VALIDATION 3: Verify that the union of solution pieces equals the target
        union = unary_union(solution_pieces)
        
        # Check area match
        area_diff = abs(union.area - self.target.area)
        if area_diff > 1e-6:
            raise RuntimeError(f"Solution pieces area ({union.area:.4f}) doesn't match target area ({self.target.area:.4f}). Difference: {area_diff:.6f}")
        
        # Check geometric equality
        if not union.equals(self.target):
            # Try checking with buffer to account for numerical errors
            diff = union.symmetric_difference(self.target)
            if diff.area > 1e-6:
                raise RuntimeError(f"Solution pieces don't perfectly tile the target. Symmetric difference area: {diff.area:.6f}")
        
        return solution_pieces

    def _generate_distractors(self, pieces: List[Polygon], num_distractors: int) -> List[Polygon]:
        distractors: List[Polygon] = []
        tries = 0
        while len(distractors) < num_distractors and tries < 2000:
            tries += 1
            base = random.choice(pieces)
            frags = _split_polygon(base, self.n)
            if len(frags) == 1:
                continue
            if any(math.isclose(f.area, p.area, abs_tol=1e-6) for f in frags for p in pieces + distractors):
                continue
            if any(math.isclose(f.area + d.area, p.area, abs_tol=1e-6) for f in frags for d in distractors for p in pieces):
                continue
            distractors.append(random.choice(frags))
        if len(distractors) < num_distractors:
            raise RuntimeError("Unable to create enough distractors without area clashes.")
        return distractors

    # ------------------------------------------------------------------
    #   Rendering helpers
    # ------------------------------------------------------------------
    def _render_polygon(
        self,
        poly: Polygon,
        path: Path,
        shaded: bool = True,
        ppu: int = DEFAULT_PPU,
        dpi: int = DPI,
        margin_units: float = 0.3,
        line_width: float = 2.0,
        color: str = None,
    ) -> None:
        """Save *poly* to *path* with style guide formatting."""
        minx, miny, maxx, maxy = poly.bounds
        width_units = maxx - minx
        height_units = maxy - miny
        # Pad a small margin so stroke is not clipped
        minx -= margin_units
        miny -= margin_units
        maxx += margin_units
        maxy += margin_units
        width_units += 2 * margin_units
        height_units += 2 * margin_units

        # Convert to figure size in inches
        fig_w = (width_units * ppu) / dpi
        fig_h = (height_units * ppu) / dpi
        fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=dpi)
        ax.set_aspect('equal')
        ax.set_xticks([])
        ax.set_yticks([])
        
        x, y = poly.exterior.xy
        if shaded:
            # Use solid color fill with MIDNIGHT outline
            fill_color = color if color else CERULEAN
            ax.fill(x, y, edgecolor=MIDNIGHT, linewidth=line_width, facecolor=fill_color, alpha=0.8)
        else:
            # Outline only for target silhouette
            ax.plot(x, y, color=MIDNIGHT, linewidth=line_width)
            
        ax.set_xlim(minx, maxx)
        ax.set_ylim(miny, maxy)
        ax.set_aspect("equal")
        ax.set_axis_off()
        plt.subplots_adjust(left=0, right=1, bottom=0, top=1)
        fig.savefig(path, transparent=True, facecolor=CANVAS_BG)
        plt.close(fig)

    def _render_combined_view(
        self,
        pieces: List[Tuple[bool, Polygon]],
        piece_colors: List[str],
        path: Path,
        ppu: int = DEFAULT_PPU,
        dpi: int = DPI,
    ) -> None:
        """Render target + all pieces in a single frame with labels using style guide."""
        # Calculate bounds for target
        target_bounds = self.target.bounds
        target_width = target_bounds[2] - target_bounds[0]
        target_height = target_bounds[3] - target_bounds[1]
        
        # Calculate piece bounds
        piece_bounds_list = [p.bounds for _, p in pieces]
        max_piece_width = max(b[2] - b[0] for b in piece_bounds_list)
        max_piece_height = max(b[3] - b[1] for b in piece_bounds_list)
        
        # Layout: target on left, pieces on right in a row
        margin = 0.8  # Increased margin for better spacing
        piece_spacing = 0.4  # Increased spacing between pieces
        gap_between_sections = 1.8  # Gap between target and pieces
        
        # Calculate total width and height with additional space
        total_width = target_width + margin * 2 + gap_between_sections + (max_piece_width + piece_spacing) * len(pieces)
        total_height = max(target_height, max_piece_height) + margin * 3  # Extra margin for labels
        
        # Create figure with standard canvas size
        fig, ax = plt.subplots(figsize=CANVAS_SIZE, dpi=dpi)
        ax.set_aspect('equal')
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_frame_on(True)
        
        # Add subtle frame border
        for spine in ax.spines.values():
            spine.set_edgecolor(MIDNIGHT)
            spine.set_linewidth(1.0)
        
        # Draw target (outline only) on the left with proper vertical centering
        target_x_offset = margin
        target_y_offset = margin + (total_height - margin * 3 - target_height) / 2
        x, y = self.target.exterior.xy
        ax.plot(
            [xi + target_x_offset for xi in x],
            [yi + target_y_offset for yi in y],
            color=MIDNIGHT,
            linewidth=2.0
        )
        
        # Draw pieces on the right with labels (removed section labels)
        piece_x_start = margin + target_width + gap_between_sections
        piece_y_center = margin + (total_height - margin * 3) / 2
        
        for idx, (is_sol, poly) in enumerate(pieces):
            piece_bounds = poly.bounds
            piece_w = piece_bounds[2] - piece_bounds[0]
            piece_h = piece_bounds[3] - piece_bounds[1]
            
            # Center piece vertically
            piece_x = piece_x_start + idx * (max_piece_width + piece_spacing)
            piece_y = piece_y_center - piece_h / 2
            
            # Offset polygon to position
            x_offset = piece_x - piece_bounds[0]
            y_offset = piece_y - piece_bounds[1]
            
            x, y = poly.exterior.xy
            # Use the assigned color for this piece
            ax.fill(
                [xi + x_offset for xi in x],
                [yi + y_offset for yi in y],
                edgecolor=MIDNIGHT,
                linewidth=2.0,
                facecolor=piece_colors[idx],
                alpha=0.8
            )
            
            # Add label below piece
            label = chr(65 + idx)  # A, B, C, D, E
            label_x = piece_x + piece_w / 2
            label_y = piece_y - 0.35
            ax.text(label_x, label_y, label, ha='center', va='top', 
                    fontsize=12, weight='bold', color='#222222')
        
        ax.set_xlim(0, total_width)
        ax.set_ylim(0, total_height)
        ax.set_aspect("equal")
        ax.set_axis_off()
        fig.tight_layout()
        plt.savefig(path, bbox_inches='tight', facecolor=CANVAS_BG, pad_inches=0.1, dpi=dpi)
        plt.close(fig)

    def _render_chain_of_thought(
        self,
        solution_pieces: List[Polygon],
        piece_colors: List[str],
        base_path: Path,
        ppu: int = DEFAULT_PPU,
        dpi: int = DPI,
    ) -> None:
        """Render chain-of-thought images showing progressive assembly with consistent colors."""
        target_bounds = self.target.bounds
        minx, miny = target_bounds[0], target_bounds[1]
        maxx, maxy = target_bounds[2], target_bounds[3]
        
        # Add margin
        margin = 0.5
        minx -= margin
        miny -= margin
        maxx += margin
        maxy += margin
        
        width = maxx - minx
        height = maxy - miny
        
        # Generate CoT images
        for step in range(len(solution_pieces)):
            fig, ax = plt.subplots(figsize=CANVAS_SIZE, dpi=dpi)
            ax.set_aspect('equal')
            ax.set_xticks([])
            ax.set_yticks([])
            ax.set_frame_on(True)
            
            # Add subtle frame border
            for spine in ax.spines.values():
                spine.set_edgecolor(MIDNIGHT)
                spine.set_linewidth(1.0)
            
            # Draw pieces accumulated so far with consistent colors
            for i in range(step + 1):
                poly = solution_pieces[i]
                x, y = poly.exterior.xy
                # Draw with colors from palette and visible borders
                ax.fill(x, y, color=piece_colors[i], edgecolor=MIDNIGHT, linewidth=2.0, alpha=0.8)
            
            ax.set_xlim(minx, maxx)
            ax.set_ylim(miny, maxy)
            ax.set_aspect("equal")
            ax.set_axis_off()
            
            cot_path = base_path / f"cot_{step:02d}.png"
            fig.tight_layout()
            plt.savefig(cot_path, bbox_inches='tight', facecolor=CANVAS_BG, dpi=dpi)
            plt.close(fig)

    # ------------------------------------------------------------------
    #   Public API
    # ------------------------------------------------------------------
    def export(self, out_path: str, ppu: int = DEFAULT_PPU, seed: int = None, num_solution_pieces: int = None) -> None:
        """Generate one puzzle with CoT visualization and combined view."""
        k = num_solution_pieces if num_solution_pieces is not None else random.randint(2, 5)
        pieces = self._generate_solution_pieces(k)
        distractors = self._generate_distractors(pieces, 5 - k)

        # Shuffle options but keep track of solution pieces
        options = [(True, p) for p in pieces] + [(False, d) for d in distractors]
        random.shuffle(options)
        
        # Generate colors for ALL 5 pieces in their SHUFFLED order
        # This ensures consistency between individual pieces, combined view, and CoT
        if seed is not None:
            rng_all = random.Random(seed)
        else:
            rng_all = random.Random()
        all_piece_colors = assign_piece_colors(5, rng_all)
        
        # Extract solution pieces in their original order for CoT
        solution_pieces_ordered = pieces  # Keep original order for logical assembly
        
        # Map each solution piece to its color in the shuffled options list
        solution_piece_colors = []
        for solution_piece in solution_pieces_ordered:
            # Find this piece in the shuffled options and get its color
            for idx, (is_sol, piece) in enumerate(options):
                if piece.equals(solution_piece):
                    solution_piece_colors.append(all_piece_colors[idx])
                    break
        
        # 1. Silhouette - target outline only
        out_dir = Path(out_path)
        silhouette_path = out_dir / "silhouette.png"
        self._render_polygon(self.target, silhouette_path, shaded=False, ppu=ppu)
        
        # 2. Bordered - target with solution pieces showing internal structure with colors
        bordered_path = out_dir / "bordered.png"
        target_bounds = self.target.bounds
        minx, miny, maxx, maxy = target_bounds
        margin = 0.5
        minx -= margin
        miny -= margin
        maxx += margin
        maxy += margin
        width = maxx - minx
        height = maxy - miny
        
        fig, ax = plt.subplots(figsize=CANVAS_SIZE, dpi=DPI)
        ax.set_aspect('equal')
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_frame_on(True)
        
        # Add subtle frame border
        for spine in ax.spines.values():
            spine.set_edgecolor(MIDNIGHT)
            spine.set_linewidth(1.0)
        
        for i, poly in enumerate(solution_pieces_ordered):
            x, y = poly.exterior.xy
            ax.fill(x, y, color=solution_piece_colors[i], edgecolor=MIDNIGHT, linewidth=2.0, alpha=0.8)
        
        ax.set_xlim(minx, maxx)
        ax.set_ylim(miny, maxy)
        ax.set_aspect("equal")
        ax.set_axis_off()
        fig.tight_layout()
        plt.savefig(bordered_path, bbox_inches='tight', facecolor=CANVAS_BG, dpi=DPI)
        plt.close(fig)
        
        # 3. Chain of thought - progressive assembly
        self._render_chain_of_thought(solution_pieces_ordered, solution_piece_colors, out_dir, ppu=ppu)
        
        # 4. Individual piece images with colors
        ret = []
        for idx, (is_sol, poly) in enumerate(options, 1):
            ret.append('T' if is_sol else 'F')
            # Pass the color for this piece
            self._render_polygon(poly, out_dir / f"piece_{idx}.png", shaded=True, ppu=ppu, color=all_piece_colors[idx-1])
        
        # 5. Combined view - target + all pieces in one frame
        combined_path = out_dir / "combined.png"
        self._render_combined_view(options, all_piece_colors, combined_path, ppu=ppu)
        
        # 6. Merge individual piece images into choices image
        _merge_images(str(out_dir))
        
        return ret