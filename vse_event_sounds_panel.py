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


def get_sequencer_scene(context):
    """Get the correct scene for the sequencer (handles Blender 5.0+ changes)"""
    # In Blender 5.0+, the sequencer uses a dedicated scene per workspace
    if hasattr(context, 'sequencer_scene') and context.sequencer_scene:
        return context.sequencer_scene
    return context.scene


def add_sound_strip(sed, name, filepath, channel, frame_start):
    """Add a sound strip, handling different Blender API versions"""
    # Try Blender 5.0+ API first (strips.new_sound)
    if hasattr(sed, 'strips') and hasattr(sed.strips, 'new_sound'):
        return sed.strips.new_sound(
            name=name,
            filepath=filepath,
            channel=channel,
            frame_start=frame_start
        )
    # Fall back to Blender 4.x API (sequences.new_sound)
    elif hasattr(sed, 'sequences') and hasattr(sed.sequences, 'new_sound'):
        return sed.sequences.new_sound(
            name=name,
            filepath=filepath,
            channel=channel,
            frame_start=frame_start
        )
    else:
        raise RuntimeError("Could not find API to add sound strips")


def get_all_strips(sed):
    """Get all strips/sequences, handling different Blender API versions"""
    # Try Blender 5.0+ API first
    if hasattr(sed, 'strips_all'):
        return list(sed.strips_all)
    elif hasattr(sed, 'strips'):
        return list(sed.strips)
    # Fall back to Blender 4.x API
    elif hasattr(sed, 'sequences_all'):
        return list(sed.sequences_all)
    elif hasattr(sed, 'sequences'):
        return list(sed.sequences)
    return []


class VSE_OT_InsertEventSound(bpy.types.Operator):
    """Insert the event sound 5 times into the VSE"""
    bl_idname = "sequencer.insert_event_sound"
    bl_label = "Insert Event Sound"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        # Get the path to the sound file (relative to this addon)
        addon_dir = os.path.dirname(os.path.realpath(__file__))
        sound_path = os.path.join(addon_dir, "geiger_counter_sound.wav")

        # Check if the file exists
        if not os.path.exists(sound_path):
            self.report({'ERROR'}, f"Sound file not found: {sound_path}")
            return {'CANCELLED'}

        # Get the correct scene for the sequencer
        scene = get_sequencer_scene(context)
        
        # Make sure we have a sequence editor
        if not scene.sequence_editor:
            scene.sequence_editor_create()

        sed = scene.sequence_editor

        # Find an available channel - start at 1
        channel = 1
        try:
            all_strips = get_all_strips(sed)
            if all_strips and len(all_strips) > 0:
                channel = max(s.channel for s in all_strips) + 1
        except Exception:
            # If anything fails, just use channel 1
            channel = 1

        # Get the current frame as starting point
        current_frame = scene.frame_current

        # Insert the sound 5 times sequentially
        inserted_count = 0
        frame_offset = current_frame

        for i in range(5):
            try:
                # Add the sound strip
                strip = add_sound_strip(
                    sed,
                    name=f"EventSound_{i+1}",
                    filepath=sound_path,
                    channel=channel,
                    frame_start=frame_offset
                )
                
                # Move the offset for the next strip
                # Handle both old and new property names
                if hasattr(strip, 'frame_final_end'):
                    frame_offset = strip.frame_final_end
                elif hasattr(strip, 'frame_end'):
                    frame_offset = strip.frame_end
                else:
                    # Estimate based on typical audio length
                    frame_offset += 48  # Fallback
                    
                inserted_count += 1
            except Exception as e:
                self.report({'ERROR'}, f"Failed to add strip: {e}")
                return {'CANCELLED'}

        self.report({'INFO'}, f"Inserted {inserted_count} event sounds starting at frame {current_frame}")
        return {'FINISHED'}


class VSE_PT_EventSoundsPanel(bpy.types.Panel):
    """Panel in the N-panel of the Video Sequence Editor"""
    bl_label = "Event Sounds"
    bl_idname = "VSE_PT_event_sounds_panel"
    bl_space_type = 'SEQUENCE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "Event Sounds"

    def draw(self, context):
        layout = self.layout
        
        # Main button to insert sounds
        layout.operator(
            VSE_OT_InsertEventSound.bl_idname,
            text="Insert 5x Event Sound",
            icon='SPEAKER'
        )
        
        # Info box
        box = layout.box()
        box.label(text="Inserts the event sound", icon='INFO')
        box.label(text="5 times sequentially")
        box.label(text="starting at the playhead.")
