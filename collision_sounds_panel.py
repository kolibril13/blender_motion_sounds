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
from bpy.types import Panel, PropertyGroup
from bpy.props import PointerProperty, EnumProperty


class CollisionSoundsProperties(PropertyGroup):
    """Scene-level properties for Collision Sounds"""

    static_plane: PointerProperty(
        name="Static Plane",
        description="The static plane that objects collide with",
        type=bpy.types.Object,
    )

    moving_object_type: EnumProperty(
        name="Type",
        description="Whether the moving source is a single object or a collection",
        items=[
            ('OBJECT', "Object", "A single moving object"),
            ('COLLECTION', "Collection", "A collection of moving objects"),
        ],
        default='OBJECT',
    )

    moving_object: PointerProperty(
        name="Moving Object",
        description="The moving object that collides with the static plane",
        type=bpy.types.Object,
    )

    moving_collection: PointerProperty(
        name="Moving Collection",
        description="A collection of moving objects that collide with the static plane",
        type=bpy.types.Collection,
    )


class VSE_PT_CollisionSoundsPanel(Panel):
    """Main panel for Collision Sounds in the 3D Viewport N-panel"""
    bl_label = "Collision Sounds"
    bl_idname = "VSE_PT_collision_sounds_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Collision Sounds"

    def draw(self, context):
        layout = self.layout
        props = context.scene.collision_sounds

        # --- Static Plane ---
        layout.label(text="Static Plane:", icon='MESH_PLANE')
        layout.prop(props, "static_plane", text="")

        layout.separator()

        # --- Moving Object / Collection ---
        layout.label(text="Moving Object:", icon='OBJECT_DATA')
        row = layout.row(align=True)
        row.prop(props, "moving_object_type", expand=True)

        if props.moving_object_type == 'OBJECT':
            layout.prop(props, "moving_object", text="")
        else:
            layout.prop(props, "moving_collection", text="")


def register():
    bpy.types.Scene.collision_sounds = PointerProperty(type=CollisionSoundsProperties)


def unregister():
    del bpy.types.Scene.collision_sounds
