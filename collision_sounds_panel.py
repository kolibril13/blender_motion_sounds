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

from bpy.types import Panel


class VSE_PT_CollisionSoundsPanel(Panel):
    """Main panel for Collision Sounds in the 3D Viewport N-panel"""
    bl_label = "Collision Sounds"
    bl_idname = "VSE_PT_collision_sounds_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Collision Sounds"

    def draw(self, context):
        layout = self.layout
        layout.label(text="Collision sound settings go here.", icon='PHYSICS')
