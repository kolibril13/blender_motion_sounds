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
import os


class VSE_OT_InsertGeigerSound(bpy.types.Operator):
    """Insert the Geiger counter sound 5 times into the VSE"""
    bl_idname = "sequencer.insert_geiger_sound"
    bl_label = "Insert Geiger Sound"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Get the path to the sound file (relative to this addon)
        addon_dir = os.path.dirname(os.path.realpath(__file__))
        sound_path = os.path.join(addon_dir, "geiger_counter_sound.wav")

        # Check if the file exists
        if not os.path.exists(sound_path):
            self.report({'ERROR'}, f"Sound file not found: {sound_path}")
            return {'CANCELLED'}

        # Make sure we have a scene with a sequence editor
        scene = context.scene
        if not scene.sequence_editor:
            scene.sequence_editor_create()

        sed = scene.sequence_editor

        # Find an available channel
        channel = 1
        if sed.sequences:
            # Find the highest used channel and use the one above it
            channel = max(s.channel for s in sed.sequences) + 1

        # Get the current frame as starting point
        current_frame = scene.frame_current

        # Insert the sound 5 times sequentially
        inserted_count = 0
        frame_offset = current_frame

        for i in range(5):
            # Add the sound strip
            strip = sed.sequences.new_sound(
                name=f"Geiger_{i+1}",
                filepath=sound_path,
                channel=channel,
                frame_start=frame_offset
            )
            
            # Move the offset for the next strip
            frame_offset = strip.frame_final_end
            inserted_count += 1

        self.report({'INFO'}, f"Inserted {inserted_count} Geiger counter sounds starting at frame {current_frame}")
        return {'FINISHED'}


class VSE_PT_GeigerPanel(bpy.types.Panel):
    """Panel in the N-panel of the Video Sequence Editor"""
    bl_label = "Geiger Counter"
    bl_idname = "VSE_PT_geiger_panel"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Geiger"

    def draw(self, context):
        layout = self.layout
        
        # Main button to insert sounds
        layout.operator(
            VSE_OT_InsertGeigerSound.bl_idname,
            text="Insert 5x Geiger Sound",
            icon='SPEAKER'
        )
        
        # Info box
        box = layout.box()
        box.label(text="Inserts the Geiger counter", icon='INFO')
        box.label(text="sound 5 times sequentially")
        box.label(text="starting at the playhead.")
