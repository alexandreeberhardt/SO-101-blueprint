"""Hidden-line vector rendering of the SO-101 arms from the official URDF + STL meshes.

For each requested view, extracts crease and silhouette edges from the posed meshes,
tests their visibility against a GPU depth buffer, and writes 2D polylines (in mm) to JSON.
"""

import json
import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import contourpy
import moderngl
import numpy as np
import trimesh

SIM_DIR = Path(__file__).resolve().parent.parent / "vendor/SO-ARM100/Simulation/SO101"
CREASE_ANGLE_DEG = 32.0
PX_PER_MM = 12.0


def rpy_matrix(roll, pitch, yaw):
    cr, sr = math.cos(roll), math.sin(roll)
    cp, sp = math.cos(pitch), math.sin(pitch)
    cy, sy = math.cos(yaw), math.sin(yaw)
    rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    rz = np.array([[cy, -sy, 0], [sy, cy, 0], [0, 0, 1]])
    return rz @ ry @ rx


def origin_transform(element):
    transform = np.eye(4)
    if element is None:
        return transform
    xyz = [float(v) for v in element.get("xyz", "0 0 0").split()]
    rpy = [float(v) for v in element.get("rpy", "0 0 0").split()]
    transform[:3, :3] = rpy_matrix(*rpy)
    transform[:3, 3] = xyz
    return transform


def axis_angle_transform(axis, angle):
    axis = np.asarray(axis, dtype=float)
    axis = axis / np.linalg.norm(axis)
    transform = np.eye(4)
    transform[:3, :3] = trimesh.transformations.rotation_matrix(angle, axis)[:3, :3]
    return transform


def load_posed_arm(urdf_name, joint_angles):
    """Returns a list of (part_name, mesh_in_mm) and the world position of each joint (mm)."""
    root = ET.parse(SIM_DIR / urdf_name).getroot()
    links = {link.get("name"): link for link in root.findall("link")}
    joints = root.findall("joint")
    children_of = {}
    child_links = set()
    for joint in joints:
        parent = joint.find("parent").get("link")
        children_of.setdefault(parent, []).append(joint)
        child_links.add(joint.find("child").get("link"))
    root_link = next(name for name in links if name not in child_links)

    parts = []
    joint_positions = {}
    stack = [(root_link, np.eye(4))]
    while stack:
        link_name, link_world = stack.pop()
        for visual in links[link_name].findall("visual"):
            mesh_file = visual.find("geometry/mesh").get("filename")
            mesh = trimesh.load(SIM_DIR / mesh_file, force="mesh")
            world = link_world @ origin_transform(visual.find("origin"))
            mesh.apply_transform(world)
            mesh.apply_scale(1000.0)
            parts.append((Path(mesh_file).stem, mesh))
        for joint in children_of.get(link_name, []):
            joint_world = link_world @ origin_transform(joint.find("origin"))
            name = joint.get("name")
            if joint.get("type") == "revolute":
                axis = [float(v) for v in joint.find("axis").get("xyz").split()]
                joint_world = joint_world @ axis_angle_transform(axis, joint_angles.get(name, 0.0))
                joint_positions[name] = (joint_world[:3, 3] * 1000.0).tolist()
            stack.append((joint.find("child").get("link"), joint_world))
    return parts, joint_positions


def view_basis(direction, up):
    forward = np.asarray(direction, dtype=float)
    forward = forward / np.linalg.norm(forward)
    right = np.cross(forward, up)
    right = right / np.linalg.norm(right)
    true_up = np.cross(right, forward)
    return right, true_up, forward


def render_depth(ctx, triangles_uvd, bounds, size):
    """triangles_uvd: (n, 3, 3) projected (u, v, depth). Returns window depth in [0, 1]."""
    (u_min, v_min, d_min), (u_max, v_max, d_max) = bounds
    ndc = np.empty_like(triangles_uvd, dtype="f4")
    ndc[..., 0] = (triangles_uvd[..., 0] - u_min) / (u_max - u_min) * 2 - 1
    ndc[..., 1] = (triangles_uvd[..., 1] - v_min) / (v_max - v_min) * 2 - 1
    ndc[..., 2] = (triangles_uvd[..., 2] - d_min) / (d_max - d_min) * 2 - 1

    program = ctx.program(
        vertex_shader="#version 330\nin vec3 p; void main(){ gl_Position = vec4(p, 1.0); }",
        fragment_shader="#version 330\nout vec4 c; void main(){ c = vec4(1.0); }",
    )
    vbo = ctx.buffer(ndc.reshape(-1, 3).tobytes())
    vao = ctx.vertex_array(program, [(vbo, "3f", "p")])
    depth = ctx.depth_texture(size)
    fbo = ctx.framebuffer(color_attachments=[ctx.renderbuffer(size)], depth_attachment=depth)
    fbo.use()
    ctx.enable(moderngl.DEPTH_TEST)
    ctx.disable(moderngl.CULL_FACE)
    fbo.clear(depth=1.0)
    vao.render(moderngl.TRIANGLES)
    data = np.frombuffer(depth.read(), dtype="f4").reshape(size[1], size[0])
    for resource in (vao, vbo, fbo, depth, program):
        resource.release()
    return data


def extract_edges(mesh, view_direction):
    """Returns (segments (n,2,3), kind array) with kind 0 = silhouette, 1 = crease/boundary."""
    normals = mesh.face_normals
    adjacency = mesh.face_adjacency
    angles = mesh.face_adjacency_angles
    edges = mesh.face_adjacency_edges
    facing = normals @ view_direction
    side_a = facing[adjacency[:, 0]] < 0
    side_b = facing[adjacency[:, 1]] < 0
    silhouette = side_a != side_b
    crease = angles > math.radians(CREASE_ANGLE_DEG)
    # A crease only matters if at least one adjacent face is visible-facing.
    crease &= side_a | side_b
    keep = silhouette | crease
    segments = mesh.vertices[edges[keep]]
    kinds = np.where(silhouette[keep], 0, 1)

    edge_counts = np.bincount(mesh.edges_unique_inverse, minlength=len(mesh.edges_unique))
    boundary = mesh.edges_unique[edge_counts == 1]
    if len(boundary):
        segments = np.concatenate([segments, mesh.vertices[boundary]])
        kinds = np.concatenate([kinds, np.ones(len(boundary), dtype=int)])
    return segments, kinds


def classify_visibility(segments_uvd, depth_map, bounds, size, eps_px):
    """Samples each segment; returns per-segment boolean visibility arrays at sample points."""
    (u_min, v_min, d_min), (u_max, v_max, d_max) = bounds
    width, height = size
    padded = np.pad(depth_map, 1, mode="edge")
    neighbourhood_max = np.max(
        [padded[dy:dy + height, dx:dx + width] for dy in range(3) for dx in range(3)], axis=0
    )
    mm_per_px = (u_max - u_min) / width
    eps = eps_px * mm_per_px / (d_max - d_min)

    lengths_px = np.linalg.norm(segments_uvd[:, 1, :2] - segments_uvd[:, 0, :2], axis=1) / mm_per_px
    sample_counts = np.clip(np.ceil(lengths_px / 1.5).astype(int) + 1, 2, 400)
    results = []
    for count in np.unique(sample_counts):
        index = np.nonzero(sample_counts == count)[0]
        t = np.linspace(0.0, 1.0, count)
        start = segments_uvd[index, 0][:, None, :]
        end = segments_uvd[index, 1][:, None, :]
        points = start + (end - start) * t[None, :, None]
        px = ((points[..., 0] - u_min) / (u_max - u_min) * width).astype(int).clip(0, width - 1)
        py = ((points[..., 1] - v_min) / (v_max - v_min) * height).astype(int).clip(0, height - 1)
        z = (points[..., 2] - d_min) / (d_max - d_min)
        visible = z <= neighbourhood_max[py, px] + eps
        results.extend(zip(index, visible))
    results.sort(key=lambda item: item[0])
    return [visible for _, visible in results]


def split_runs(segment_uv, visible):
    """Splits a sampled segment into (visible_flag, start_t, end_t) runs."""
    count = len(visible)
    runs = []
    run_start = 0
    for i in range(1, count + 1):
        if i == count or visible[i] != visible[run_start]:
            t0 = run_start / (count - 1)
            t1 = min(i, count - 1) / (count - 1)
            if t1 > t0:
                runs.append((bool(visible[run_start]), t0, t1))
            run_start = i
    return runs


def chain_segments(segments, decimals=3):
    """Joins 2D segments sharing endpoints into polylines."""
    keyed = [(tuple(np.round(a, decimals)), tuple(np.round(b, decimals))) for a, b in segments]
    neighbours = {}
    for index, (a, b) in enumerate(keyed):
        neighbours.setdefault(a, []).append(index)
        neighbours.setdefault(b, []).append(index)
    used = np.zeros(len(keyed), dtype=bool)
    polylines = []
    for start_index in range(len(keyed)):
        if used[start_index]:
            continue
        used[start_index] = True
        line = [keyed[start_index][0], keyed[start_index][1]]
        for direction in (1, -1):
            while True:
                tip = line[-1] if direction == 1 else line[0]
                next_index = next((i for i in neighbours[tip] if not used[i]), None)
                if next_index is None:
                    break
                used[next_index] = True
                a, b = keyed[next_index]
                other = b if a == tip else a
                if direction == 1:
                    line.append(other)
                else:
                    line.insert(0, other)
        polylines.append(line)
    return polylines


def render_view(ctx, parts, direction, up):
    right, true_up, forward = view_basis(direction, up)
    projection = np.stack([right, true_up, forward])

    all_vertices = np.concatenate([mesh.vertices for _, mesh in parts]) @ projection.T
    low = all_vertices.min(axis=0) - 2.0
    high = all_vertices.max(axis=0) + 2.0
    bounds = (low, high)
    size = (int((high[0] - low[0]) * PX_PER_MM), int((high[1] - low[1]) * PX_PER_MM))

    triangles = np.concatenate([mesh.triangles for _, mesh in parts]) @ projection.T
    depth_map = render_depth(ctx, triangles, bounds, size)

    buckets = {"silhouette": [], "crease": [], "hidden": []}
    for _, mesh in parts:
        segments, kinds = extract_edges(mesh, forward)
        if not len(segments):
            continue
        segments_uvd = segments @ projection.T
        visibilities = classify_visibility(segments_uvd, depth_map, bounds, size, eps_px=1.5)
        for segment, kind, visible in zip(segments_uvd, kinds, visibilities):
            uv = segment[:, :2]
            if visible.all():
                buckets["silhouette" if kind == 0 else "crease"].append(uv)
                continue
            if not visible.any():
                buckets["hidden"].append(uv)
                continue
            for is_visible, t0, t1 in split_runs(uv, visible):
                piece = np.array([uv[0] + (uv[1] - uv[0]) * t0, uv[0] + (uv[1] - uv[0]) * t1])
                if is_visible:
                    buckets["silhouette" if kind == 0 else "crease"].append(piece)
                else:
                    buckets["hidden"].append(piece)

    outer, inner = split_outer_silhouette(buckets["silhouette"], depth_map, bounds, size)
    buckets["silhouette"] = inner
    buckets["outline"] = outer
    lines = {name: chain_segments(segs) for name, segs in buckets.items()}
    return {
        "bounds": [low[:2].tolist(), high[:2].tolist()],
        "projection": projection.tolist(),
        "lines": lines,
        "fill": silhouette_polygons(depth_map, bounds),
    }


def split_outer_silhouette(segments, depth_map, bounds, size, probe_px=2.5):
    """Separates silhouette pieces bordering the background (outer outline) from inner ones."""
    if not segments:
        return [], []
    (u_min, v_min, _), (u_max, v_max, _) = bounds
    width, height = size
    px_per_mm = width / (u_max - u_min)
    background = depth_map >= 1.0
    stacked = np.array(segments)
    direction = stacked[:, 1] - stacked[:, 0]
    length = np.linalg.norm(direction, axis=1, keepdims=True)
    normal = np.stack([-direction[:, 1], direction[:, 0]], axis=1) / np.maximum(length, 1e-9)
    is_outer = np.zeros(len(stacked), dtype=bool)
    for t in (0.25, 0.5, 0.75):
        point = stacked[:, 0] + direction * t
        for sign in (1, -1):
            probe = point + normal * sign * probe_px / px_per_mm
            px = ((probe[:, 0] - u_min) * px_per_mm).astype(int).clip(0, width - 1)
            py = ((probe[:, 1] - v_min) * px_per_mm).astype(int).clip(0, height - 1)
            is_outer |= background[py, px]
    outer = [segment for segment, flag in zip(segments, is_outer) if flag]
    inner = [segment for segment, flag in zip(segments, is_outer) if not flag]
    return outer, inner


def silhouette_polygons(depth_map, bounds, step=3):
    """Outline of the covered area, as closed polygons in mm (outer rings and holes)."""
    (u_min, v_min, _), (u_max, v_max, _) = bounds
    mask = (depth_map[::step, ::step] < 1.0).astype(float)
    mask = np.pad(mask, 1)
    height, width = mask.shape
    generator = contourpy.contour_generator(z=mask, line_type=contourpy.LineType.Separate)
    polygons = []
    for ring in generator.lines(0.5):
        u = u_min + (ring[:, 0] - 1) * step / PX_PER_MM
        v = v_min + (ring[:, 1] - 1) * step / PX_PER_MM
        polygons.append(np.round(np.stack([u, v], axis=1), 2).tolist())
    return polygons


def main(config_path, output_path):
    config = json.loads(Path(config_path).read_text())
    ctx = moderngl.create_standalone_context()
    output = {}
    for arm_name, arm in config["arms"].items():
        parts, joint_positions = load_posed_arm(arm["urdf"], arm.get("joints", {}))
        output[arm_name] = {"joints": joint_positions, "views": {}}
        for view_name, view in arm["views"].items():
            result = render_view(ctx, parts, view["direction"], view["up"])
            projection = np.array(result["projection"])
            result["joints_2d"] = {
                name: (np.array(position) @ projection.T)[:2].tolist()
                for name, position in joint_positions.items()
            }
            output[arm_name]["views"][view_name] = result
            counts = {name: len(polys) for name, polys in result["lines"].items()}
            print(arm_name, view_name, counts, flush=True)
    Path(output_path).write_text(json.dumps(output))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
