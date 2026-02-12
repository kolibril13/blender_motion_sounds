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
import os
import math
import random
import colorsys
from bpy.types import Panel, PropertyGroup, Operator, UIList
from bpy.props import (
    PointerProperty,
    CollectionProperty,
    StringProperty,
    FloatProperty,
    FloatVectorProperty,
    IntProperty,
    EnumProperty,
)
from mathutils.bvhtree import BVHTree


# ============================================================
# Constants
# ============================================================

SUPPORTED_AUDIO_EXTENSIONS = {'.wav', '.mp3', '.ogg', '.flac', '.aiff', '.aif'}


# ============================================================
# Color Matching Functions
# ============================================================

def euclidean_rgb_distance(color_a, color_b):
    """Compute Euclidean distance between two RGB colors (each in 0-1 range).

    Args:
        color_a: Tuple/list of (r, g, b).
        color_b: Tuple/list of (r, g, b).

    Returns:
        Float distance (0 = identical, sqrt(3) ~ 1.732 = max).
    """
    return math.sqrt(
        (color_a[0] - color_b[0]) ** 2
        + (color_a[1] - color_b[1]) ** 2
        + (color_a[2] - color_b[2]) ** 2
    )


def find_closest_slot(sampled_color, sound_slots):
    """Find the sound slot whose color is nearest to `sampled_color`.

    Uses Euclidean RGB distance (closest-color-wins).

    Args:
        sampled_color: Tuple (r, g, b) in 0-1 range.
        sound_slots:   Iterable of SZ_SoundSlot items.

    Returns:
        (slot, distance) or (None, inf) when no slots exist.
    """
    best_slot = None
    best_dist = float('inf')

    for slot in sound_slots:
        dist = euclidean_rgb_distance(sampled_color, slot.color)
        if dist < best_dist:
            best_dist = dist
            best_slot = slot

    return best_slot, best_dist


# ============================================================
# Vertex Color Sampling
# ============================================================

def sample_vertex_color_at_face(mesh, face_index, color_attribute_name):
    """Average the vertex-paint color across a polygon's face corners.

    Works with face-corner domain color attributes (the default for
    Blender vertex paint).

    Args:
        mesh:                 bpy.types.Mesh (evaluated).
        face_index:           Index of the polygon hit by the BVH query.
        color_attribute_name: Name of the color attribute layer.

    Returns:
        Tuple (r, g, b) averaged over the face corners, or None on error.
    """
    color_layer = mesh.color_attributes.get(color_attribute_name)
    if color_layer is None:
        return None

    color_data = color_layer.data
    poly = mesh.polygons[face_index]

    r_sum = g_sum = b_sum = 0.0
    count = 0
    for loop_index in poly.loop_indices:
        c = color_data[loop_index].color
        r_sum += c[0]
        g_sum += c[1]
        b_sum += c[2]
        count += 1

    if count == 0:
        return None

    return (r_sum / count, g_sum / count, b_sum / count)


# ============================================================
# Helper: generate distinguishable default colors
# ============================================================

def _generate_slot_color(index):
    """Return an RGB tuple using golden-ratio hue spacing."""
    hue = (index * 0.618033988749895) % 1.0
    r, g, b = colorsys.hsv_to_rgb(hue, 0.8, 0.9)
    return (r, g, b)


# ============================================================
# Data Model  (PropertyGroups)
# ============================================================

class SZ_SoundFileItem(PropertyGroup):
    """A single sound file entry inside a slot's sound bank."""

    filepath: StringProperty(
        name="File Path",
        description="Path to a sound file",
        subtype='FILE_PATH',
        default="",
    )


class SZ_SoundSlot(PropertyGroup):
    """One sound-zone slot: color key + sound bank + per-slot mix settings."""

    color: FloatVectorProperty(
        name="Color",
        description="RGB color that identifies this sound zone on the mesh",
        subtype='COLOR',
        min=0.0,
        max=1.0,
        size=3,
        default=(1.0, 0.0, 0.0),
    )

    sound_files: CollectionProperty(type=SZ_SoundFileItem)
    active_sound_file_index: IntProperty(default=0)

    volume_multiplier: FloatProperty(
        name="Volume",
        description="Volume multiplier for sounds triggered from this slot",
        default=1.0,
        min=0.0,
        max=2.0,
        subtype='FACTOR',
    )

    pitch_min: FloatProperty(
        name="Min",
        description="Lower bound of random pitch multiplier",
        default=0.9,
        min=0.1,
        max=3.0,
    )

    pitch_max: FloatProperty(
        name="Max",
        description="Upper bound of random pitch multiplier",
        default=1.1,
        min=0.1,
        max=3.0,
    )


def _poll_mesh_object(self, obj):
    """PointerProperty poll: only allow mesh objects."""
    return obj.type == 'MESH'


class SZ_SoundZoneSettings(PropertyGroup):
    """Scene-level settings for the Sound Zones system."""

    sound_slots: CollectionProperty(type=SZ_SoundSlot)
    active_slot_index: IntProperty(default=0)

    target_surface: PointerProperty(
        name="Surface",
        description="Mesh with vertex paint that defines the sound zones",
        type=bpy.types.Object,
        poll=_poll_mesh_object,
    )

    moving_object: PointerProperty(
        name="Moving Object",
        description="Object whose proximity/contact triggers sounds (e.g. a ball)",
        type=bpy.types.Object,
    )

    color_attribute_name: StringProperty(
        name="Color Attribute",
        description="Name of the vertex color attribute on the surface mesh",
        default="Col",
    )

    collision_epsilon: FloatProperty(
        name="Collision Threshold",
        description="Surface distance at which a collision is registered",
        default=0.005,
        min=0.0,
        soft_max=0.1,
        unit='LENGTH',
    )


# ============================================================
# UILists
# ============================================================

class SZ_UL_SoundSlotList(UIList):
    """Draws each sound slot as a row with a color swatch, name, and file count."""

    bl_idname = "SZ_UL_sound_slot_list"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index):
        slot = item
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            row.prop(slot, "color", text="")
            row.prop(slot, "name", text="", emboss=False)
            row.label(text=f"[{len(slot.sound_files)}]")
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.prop(slot, "color", text="")


class SZ_UL_SoundFileList(UIList):
    """Draws each sound file as a row showing the filename."""

    bl_idname = "SZ_UL_sound_file_list"

    def draw_item(self, context, layout, data, item, icon, active_data,
                  active_property, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            filepath = item.filepath
            filename = os.path.basename(filepath) if filepath else "(empty)"
            layout.label(text=filename, icon='SOUND')
        elif self.layout_type == 'GRID':
            layout.alignment = 'CENTER'
            layout.label(text="", icon='SOUND')


# ============================================================
# Operators – Slot Management
# ============================================================

class SZ_OT_AddSlot(Operator):
    """Add a new sound slot with an auto-generated color"""

    bl_idname = "sound_zones.add_slot"
    bl_label = "Add Sound Slot"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.sz_settings
        slot = settings.sound_slots.add()

        n = len(settings.sound_slots)
        slot.color = _generate_slot_color(n - 1)
        slot.name = f"Slot {n}"

        settings.active_slot_index = n - 1
        return {'FINISHED'}


class SZ_OT_RemoveSlot(Operator):
    """Remove the active sound slot"""

    bl_idname = "sound_zones.remove_slot"
    bl_label = "Remove Sound Slot"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return len(context.scene.sz_settings.sound_slots) > 0

    def execute(self, context):
        settings = context.scene.sz_settings
        idx = settings.active_slot_index
        settings.sound_slots.remove(idx)
        settings.active_slot_index = min(idx, len(settings.sound_slots) - 1)
        return {'FINISHED'}


class SZ_OT_MoveSlot(Operator):
    """Reorder the active sound slot"""

    bl_idname = "sound_zones.move_slot"
    bl_label = "Move Sound Slot"
    bl_options = {'REGISTER', 'UNDO'}

    direction: EnumProperty(
        items=[('UP', "Up", ""), ('DOWN', "Down", "")],
    )

    @classmethod
    def poll(cls, context):
        return len(context.scene.sz_settings.sound_slots) > 1

    def execute(self, context):
        settings = context.scene.sz_settings
        idx = settings.active_slot_index

        if self.direction == 'UP' and idx > 0:
            settings.sound_slots.move(idx, idx - 1)
            settings.active_slot_index -= 1
        elif self.direction == 'DOWN' and idx < len(settings.sound_slots) - 1:
            settings.sound_slots.move(idx, idx + 1)
            settings.active_slot_index += 1

        return {'FINISHED'}


# ============================================================
# Operators – Sound File Management
# ============================================================

class SZ_OT_AddSoundFile(Operator):
    """Browse for sound files and add them to the active slot"""

    bl_idname = "sound_zones.add_sound_file"
    bl_label = "Add Sound File"
    bl_options = {'REGISTER'}

    filepath: StringProperty(subtype='FILE_PATH')
    directory: StringProperty(subtype='DIR_PATH')
    files: CollectionProperty(type=bpy.types.OperatorFileListElement)

    filter_glob: StringProperty(
        default="*.wav;*.mp3;*.ogg;*.flac;*.aiff;*.aif",
        options={'HIDDEN'},
    )

    @classmethod
    def poll(cls, context):
        return len(context.scene.sz_settings.sound_slots) > 0

    def execute(self, context):
        settings = context.scene.sz_settings
        slot = settings.sound_slots[settings.active_slot_index]

        added = 0
        for f in self.files:
            filepath = os.path.join(self.directory, f.name)
            ext = os.path.splitext(f.name)[1].lower()
            if ext in SUPPORTED_AUDIO_EXTENSIONS:
                item = slot.sound_files.add()
                item.filepath = filepath
                added += 1

        # Fallback when the file browser returns a single path instead of a list
        if added == 0 and self.filepath:
            item = slot.sound_files.add()
            item.filepath = self.filepath
            added = 1

        self.report({'INFO'}, f"Added {added} sound file(s) to '{slot.name}'")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class SZ_OT_RemoveSoundFile(Operator):
    """Remove the selected sound file from the active slot"""

    bl_idname = "sound_zones.remove_sound_file"
    bl_label = "Remove Sound File"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        settings = context.scene.sz_settings
        if not settings.sound_slots:
            return False
        slot = settings.sound_slots[settings.active_slot_index]
        return len(slot.sound_files) > 0

    def execute(self, context):
        settings = context.scene.sz_settings
        slot = settings.sound_slots[settings.active_slot_index]
        idx = slot.active_sound_file_index
        slot.sound_files.remove(idx)
        slot.active_sound_file_index = min(idx, len(slot.sound_files) - 1)
        return {'FINISHED'}


# ============================================================
# Operator – Main: Scan Timeline & Add Sounds from Color Zones
# ============================================================

class SZ_OT_AddSoundsAtCollisions(Operator):
    """Scan timeline for collisions between the moving object and the painted
    surface, match vertex-paint color to sound slots, and add VSE sound strips"""

    bl_idname = "sound_zones.add_sounds_at_collisions"
    bl_label = "Add Sounds from Color Zones"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        s = context.scene.sz_settings
        return (
            s.target_surface is not None
            and s.moving_object is not None
            and len(s.sound_slots) > 0
        )

    def execute(self, context):
        settings = context.scene.sz_settings
        scene = context.scene

        target = settings.target_surface
        mover = settings.moving_object
        color_attr = settings.color_attribute_name
        epsilon = settings.collision_epsilon

        # Validate that at least one slot has sounds
        valid_slots = [s for s in settings.sound_slots if len(s.sound_files) > 0]
        if not valid_slots:
            self.report({'ERROR'},
                        "No slots have sound files. Add sounds to at least one slot.")
            return {'CANCELLED'}

        # --------------------------------------------------
        # Build BVH from the evaluated surface mesh
        # --------------------------------------------------
        depsgraph = context.evaluated_depsgraph_get()
        target_eval = target.evaluated_get(depsgraph)
        target_mesh = target_eval.to_mesh()

        color_layer = target_mesh.color_attributes.get(color_attr)
        if color_layer is None:
            target_eval.to_mesh_clear()
            self.report({'ERROR'},
                        f"Color attribute '{color_attr}' not found on '{target.name}'")
            return {'CANCELLED'}

        bm = bmesh.new()
        bm.from_mesh(target_mesh)
        bm.transform(target.matrix_world)
        surface_bvh = BVHTree.FromBMesh(bm)
        bm.free()

        # --------------------------------------------------
        # Scan every frame for collision events
        # --------------------------------------------------
        frame_start = scene.frame_start
        frame_end = scene.frame_end
        original_frame = scene.frame_current

        was_colliding = False
        collision_events = []  # (frame, slot_name, filepath, volume, pitch)

        for frame in range(frame_start, frame_end + 1):
            scene.frame_set(frame)

            center = mover.matrix_world.translation
            dims = mover.dimensions
            radius = min(dims.x, dims.y, dims.z) / 2 if dims.length > 0 else 0

            loc, normal, face_index, dist = surface_bvh.find_nearest(center)
            if loc is None:
                was_colliding = False
                continue

            surface_distance = dist - radius
            is_colliding = surface_distance <= epsilon

            if is_colliding and not was_colliding:
                # --- sample vertex paint color at the contact face ---
                sampled = sample_vertex_color_at_face(
                    target_mesh, face_index, color_attr
                )
                if sampled is None:
                    was_colliding = is_colliding
                    continue

                # --- closest-color-wins matching ---
                slot, color_dist = find_closest_slot(sampled, settings.sound_slots)
                if slot is None or len(slot.sound_files) == 0:
                    was_colliding = is_colliding
                    continue

                # --- pick a random sound from the slot's bank ---
                sound_item = random.choice(list(slot.sound_files))
                filepath = bpy.path.abspath(sound_item.filepath)
                if not os.path.exists(filepath):
                    self.report({'WARNING'},
                                f"File missing: {filepath}")
                    was_colliding = is_colliding
                    continue

                pitch = random.uniform(slot.pitch_min, slot.pitch_max)
                volume = slot.volume_multiplier

                collision_events.append(
                    (frame, slot.name, filepath, volume, pitch)
                )

            was_colliding = is_colliding

        scene.frame_set(original_frame)
        target_eval.to_mesh_clear()

        if not collision_events:
            self.report({'WARNING'}, "No collision events detected")
            return {'CANCELLED'}

        # --------------------------------------------------
        # Add VSE sound strips (reuse helpers from existing module)
        # --------------------------------------------------
        from . import vse_event_sounds_panel as vsp

        seq_scene = vsp.get_sequencer_scene(context)
        if not seq_scene.sequence_editor:
            seq_scene.sequence_editor_create()
        sed = seq_scene.sequence_editor

        base_channel = vsp.find_next_available_channel(sed)

        inserted = 0
        new_strips = []

        for frame, slot_name, filepath, volume, pitch in collision_events:
            try:
                strip_name = f"SZ_{slot_name}_f{frame}"
                strip = vsp.add_sound_strip(
                    sed,
                    name=strip_name,
                    filepath=filepath,
                    channel=base_channel,
                    frame_start=frame,
                )

                if hasattr(strip, 'volume'):
                    strip.volume = volume
                if hasattr(strip, 'pitch') and pitch != 1.0:
                    strip.pitch = pitch

                new_strips.append(strip)
                inserted += 1
            except Exception as e:
                self.report({'WARNING'}, f"Failed at frame {frame}: {e}")

        if new_strips:
            vsp.separate_overlapping_strips(new_strips, base_channel)

        self.report({'INFO'},
                    f"Added {inserted} sounds from color-zone collisions "
                    f"(channel {base_channel}+)")
        return {'FINISHED'}


# ============================================================
# Operator – Utility: Quantize Vertex Colors
# ============================================================

class SZ_OT_QuantizeVertexColors(Operator):
    """Snap every vertex color on the surface to the nearest slot color.
    Useful for cleaning up hand-painted zones so they map cleanly to slots"""

    bl_idname = "sound_zones.quantize_vertex_colors"
    bl_label = "Quantize Vertex Colors to Slots"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        s = context.scene.sz_settings
        return s.target_surface is not None and len(s.sound_slots) > 0

    def execute(self, context):
        settings = context.scene.sz_settings
        target = settings.target_surface
        color_attr = settings.color_attribute_name

        mesh = target.data
        color_layer = mesh.color_attributes.get(color_attr)
        if color_layer is None:
            self.report({'ERROR'},
                        f"Color attribute '{color_attr}' not found on "
                        f"'{target.name}'")
            return {'CANCELLED'}

        color_data = color_layer.data
        modified = 0

        for i in range(len(color_data)):
            c = color_data[i].color  # RGBA
            sampled = (c[0], c[1], c[2])

            slot, dist = find_closest_slot(sampled, settings.sound_slots)
            if slot is not None:
                color_data[i].color[0] = slot.color[0]
                color_data[i].color[1] = slot.color[1]
                color_data[i].color[2] = slot.color[2]
                # alpha is preserved
                modified += 1

        mesh.update()

        self.report({'INFO'},
                    f"Quantized {modified} vertex colors to "
                    f"{len(settings.sound_slots)} slot color(s)")
        return {'FINISHED'}


# ============================================================
# UI Panels
# ============================================================

class SZ_PT_SoundZonesPanel(Panel):
    """Sound Zones – map vertex-paint colors to sound banks"""

    bl_label = "Sound Zones"
    bl_idname = "SZ_PT_sound_zones_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Sounds"
    bl_parent_id = "VSE_PT_motion_sounds_panel"
    bl_order = 10

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sz_settings

        # --- Object references ---
        col = layout.column(align=True)
        col.prop(settings, "target_surface", icon='MESH_PLANE')
        col.prop(settings, "moving_object", icon='MESH_UVSPHERE')
        col.prop(settings, "color_attribute_name", icon='COLOR')
        col.prop(settings, "collision_epsilon")

        layout.separator()

        # --- Sound Slot list ---
        row = layout.row()
        row.template_list(
            "SZ_UL_sound_slot_list", "",
            settings, "sound_slots",
            settings, "active_slot_index",
            rows=3,
        )

        col = row.column(align=True)
        col.operator("sound_zones.add_slot", icon='ADD', text="")
        col.operator("sound_zones.remove_slot", icon='REMOVE', text="")
        col.separator()
        op = col.operator("sound_zones.move_slot", icon='TRIA_UP', text="")
        op.direction = 'UP'
        op = col.operator("sound_zones.move_slot", icon='TRIA_DOWN', text="")
        op.direction = 'DOWN'


class SZ_PT_SlotDetailPanel(Panel):
    """Per-slot settings and sound bank"""

    bl_label = "Slot Settings"
    bl_idname = "SZ_PT_slot_detail_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Sounds"
    bl_parent_id = "SZ_PT_sound_zones_panel"
    bl_order = 1

    @classmethod
    def poll(cls, context):
        settings = context.scene.sz_settings
        return (
            len(settings.sound_slots) > 0
            and settings.active_slot_index < len(settings.sound_slots)
        )

    def draw(self, context):
        layout = self.layout
        settings = context.scene.sz_settings
        slot = settings.sound_slots[settings.active_slot_index]

        # Name + color
        col = layout.column(align=True)
        col.prop(slot, "name")
        col.prop(slot, "color")

        layout.separator()

        # Volume + pitch range
        col = layout.column(align=True)
        col.prop(slot, "volume_multiplier", slider=True)
        col.label(text="Random Pitch Range:")
        row = col.row(align=True)
        row.prop(slot, "pitch_min")
        row.prop(slot, "pitch_max")

        layout.separator()

        # Sound bank
        col = layout.column()
        col.label(text="Sound Bank:", icon='FILE_SOUND')

        row = col.row()
        row.template_list(
            "SZ_UL_sound_file_list", "",
            slot, "sound_files",
            slot, "active_sound_file_index",
            rows=2,
        )

        sub = row.column(align=True)
        sub.operator("sound_zones.add_sound_file", icon='ADD', text="")
        sub.operator("sound_zones.remove_sound_file", icon='REMOVE', text="")


class SZ_PT_ActionsPanel(Panel):
    """Action buttons for the Sound Zones system"""

    bl_label = "Actions"
    bl_idname = "SZ_PT_actions_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Sounds"
    bl_parent_id = "SZ_PT_sound_zones_panel"
    bl_order = 2

    def draw(self, context):
        layout = self.layout

        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator(
            "sound_zones.add_sounds_at_collisions",
            text="Add Sounds from Color Zones",
            icon='PLAY',
        )

        layout.separator()

        row = layout.row()
        row.operator(
            "sound_zones.quantize_vertex_colors",
            text="Quantize Vertex Colors",
            icon='BRUSH_DATA',
        )


# ============================================================
# Registration
# ============================================================

def register():
    bpy.types.Scene.sz_settings = PointerProperty(type=SZ_SoundZoneSettings)


def unregister():
    del bpy.types.Scene.sz_settings
