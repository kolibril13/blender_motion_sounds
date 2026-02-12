# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTIBILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import bpy
import bmesh
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import tempfile
from pathlib import Path
from bpy.types import Operator
from mathutils.bvhtree import BVHTree

EPSILON = 0.0005


class COLLISION_OT_detect(Operator):
    """Scan the timeline and detect collisions between the moving object(s) and the static plane"""
    bl_idname = "collision_sounds.detect"
    bl_label = "Detect Collisions"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        props = context.scene.collision_sounds
        if props.static_plane is None:
            return False
        if props.moving_object_type == 'OBJECT' and props.moving_object is None:
            return False
        if props.moving_object_type == 'COLLECTION' and props.moving_collection is None:
            return False
        return True

    def execute(self, context):
        props = context.scene.collision_sounds
        scene = context.scene
        start = scene.frame_start
        end = scene.frame_end
        original_frame = scene.frame_current

        plane_obj = props.static_plane

        # Collect moving objects
        moving_objects = self._get_moving_objects(props)
        if not moving_objects:
            self.report({'WARNING'}, "No moving objects found")
            return {'CANCELLED'}

        # Build BVH for the static plane and get color data
        depsgraph = context.evaluated_depsgraph_get()
        plane_bvh, plane_mesh, color_data = self._build_plane_bvh(plane_obj, depsgraph)

        # Per-object results
        all_results = {}

        for obj in moving_objects:
            result = self._scan_object(
                scene, obj, plane_bvh, plane_mesh, color_data,
                start, end,
            )
            all_results[obj.name] = result

        # Restore frame
        scene.frame_set(original_frame)
        plane_obj.evaluated_get(depsgraph).to_mesh_clear()

        # Report bounces
        total_bounces = sum(len(r["collision_frames"]) for r in all_results.values())
        self.report({'INFO'}, f"Detected {total_bounces} bounce(s) across {len(moving_objects)} object(s)")

        for obj_name, result in all_results.items():
            for frame, color in zip(result["collision_frames"], result["collision_colors"]):
                print(
                    f"[{obj_name}] Bounce at frame {frame} | "
                    f"RGB = ({color[0]:.3f}, {color[1]:.3f}, {color[2]:.3f})"
                )

        # Plot results
        self._plot_results(all_results, start, end)

        return {'FINISHED'}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_moving_objects(self, props):
        """Return a list of objects to check for collisions."""
        if props.moving_object_type == 'OBJECT':
            return [props.moving_object]
        else:
            collection = props.moving_collection
            if collection is None:
                return []
            return [obj for obj in collection.all_objects if obj.type == 'MESH']

    def _build_plane_bvh(self, plane_obj, depsgraph):
        """Build a BVH tree from the static plane and return color data."""
        plane_eval = plane_obj.evaluated_get(depsgraph)
        plane_mesh = plane_eval.to_mesh()

        bm = bmesh.new()
        bm.from_mesh(plane_mesh)
        bm.transform(plane_obj.matrix_world)
        plane_bvh = BVHTree.FromBMesh(bm)
        bm.free()

        # Try to get vertex color attribute
        color_data = None
        if plane_mesh.color_attributes:
            color_layer = plane_mesh.color_attributes[0]
            color_data = color_layer.data

        return plane_bvh, plane_mesh, color_data

    def _scan_object(self, scene, obj, plane_bvh, plane_mesh, color_data,
                     start, end):
        """Scan the timeline for a single moving object and detect bounces."""
        frames = []
        distances = []
        collision_frames = []
        collision_colors = []
        colors_r = []
        colors_g = []
        colors_b = []
        was_colliding = False

        for frame in range(start, end + 1):
            scene.frame_set(frame)

            center = obj.matrix_world.translation
            radius = max(obj.dimensions) / 2

            loc, normal, face_index, dist = plane_bvh.find_nearest(center)

            if loc is None:
                continue

            surface_distance = dist - radius

            frames.append(frame)
            distances.append(surface_distance)

            # Sample vertex paint color from closest face
            avg_color = (0.0, 0.0, 0.0)
            if color_data is not None and face_index is not None:
                poly = plane_mesh.polygons[face_index]
                face_colors = []
                for loop_index in poly.loop_indices:
                    c = color_data[loop_index].color
                    face_colors.append((c[0], c[1], c[2]))
                if face_colors:
                    avg_color = (
                        sum(c[0] for c in face_colors) / len(face_colors),
                        sum(c[1] for c in face_colors) / len(face_colors),
                        sum(c[2] for c in face_colors) / len(face_colors),
                    )

            colors_r.append(avg_color[0])
            colors_g.append(avg_color[1])
            colors_b.append(avg_color[2])

            # Bounce detection (leading edge)
            is_colliding = surface_distance <= EPSILON
            if is_colliding and not was_colliding:
                collision_frames.append(frame)
                collision_colors.append(avg_color)
            was_colliding = is_colliding

        return {
            "frames": frames,
            "distances": distances,
            "collision_frames": collision_frames,
            "collision_colors": collision_colors,
            "colors_r": colors_r,
            "colors_g": colors_g,
            "colors_b": colors_b,
        }

    def _plot_results(self, all_results, start, end):
        """Plot distance and color on a single shared plot in Blender's Image Editor."""
        fig, ax = plt.subplots(figsize=(10, 4), dpi=100)

        # Use a color cycle for multiple objects
        obj_colors = plt.cm.tab10.colors

        for idx, (obj_name, result) in enumerate(all_results.items()):
            frames = result["frames"]
            distances = result["distances"]
            collision_frames = result["collision_frames"]

            if not frames:
                continue

            line_color = obj_colors[idx % len(obj_colors)]

            # Distance line
            ax.plot(
                frames, distances,
                color=line_color, linewidth=1, label=f"{obj_name}",
            )

            # Bounce markers
            if collision_frames:
                collision_dists = [
                    distances[frames.index(f)] for f in collision_frames
                ]
                ax.scatter(
                    collision_frames, collision_dists,
                    color=line_color, edgecolors='red',
                    zorder=5, s=50, linewidths=1.5,
                )
                for f in collision_frames:
                    ax.axvline(f, color='red', alpha=0.25, linewidth=0.8)

        ax.axhline(0, color='gray', linewidth=0.5, linestyle='--')
        ax.set_xlabel("Frame")
        ax.set_ylabel("Surface Distance")
        ax.set_title("Collision Detection — Distance to Plane")
        ax.legend()
        ax.grid(True, alpha=0.2)

        fig.tight_layout()

        # Save to temp file and load into Blender
        temp_path = Path(tempfile.gettempdir()) / "CollisionSounds_Plot.png"
        fig.savefig(str(temp_path), bbox_inches='tight')
        plt.close(fig)

        img_name = "CollisionSounds_Plot"
        if img_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[img_name])
        img = bpy.data.images.load(str(temp_path))
        img.name = img_name

        # Try to show in an existing Image Editor, or convert an area
        for area in bpy.context.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.spaces.active.image = img
                break
        else:
            for area in bpy.context.screen.areas:
                if area.type in {'OUTLINER', 'PROPERTIES'}:
                    area.type = 'IMAGE_EDITOR'
                    area.spaces.active.image = img
                    break

        print(f"Plot saved to: {temp_path}")
        print(f"Image '{img_name}' loaded into Blender")
