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
from bpy.types import Panel, PropertyGroup, Operator
from bpy.props import PointerProperty, StringProperty, IntProperty


class VSE_PG_EventSoundSettings(PropertyGroup):
    """Property group for event sound settings."""
    
    sound_file: StringProperty(
        name="Sound File",
        description="Path to the sound file to insert",
        subtype='FILE_PATH',
        default="",
    )
    
    repeat_count: IntProperty(
        name="Repeat Count",
        description="Number of times to insert the sound",
        default=5,
        min=1,
        max=1000,
    )
    
    frame_offset: IntProperty(
        name="Frame Offset",
        description="Number of frames between each sound (0 = back to back)",
        default=24,
        min=0,
    )


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


class VSE_OT_SelectSoundFile(Operator):
    """Open file browser to select a sound file"""
    bl_idname = "vse_event.select_sound_file"
    bl_label = "Select Sound File"
    bl_options = {'REGISTER'}
    
    filepath: StringProperty(
        subtype='FILE_PATH',
        default="",
    )
    
    filter_glob: StringProperty(
        default="*.wav;*.mp3;*.ogg;*.flac;*.aiff;*.aif",
        options={'HIDDEN'},
    )
    
    def execute(self, context):
        context.scene.vse_event_sound_settings.sound_file = self.filepath
        return {'FINISHED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class VSE_OT_InsertEventSound(Operator):
    """Insert the event sound into the VSE"""
    bl_idname = "sequencer.insert_event_sound"
    bl_label = "Insert Event Sound"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.vse_event_sound_settings
        
        # Get the sound file path
        sound_path = bpy.path.abspath(settings.sound_file)
        
        # If no custom sound file, use the default bundled one
        if not sound_path or not os.path.exists(sound_path):
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
        
        # Get settings
        repeat_count = settings.repeat_count
        custom_offset = settings.frame_offset

        # Insert the sound strips
        inserted_count = 0
        frame_position = current_frame
        sound_length = None

        for i in range(repeat_count):
            try:
                # Add the sound strip
                strip = add_sound_strip(
                    sed,
                    name=f"EventSound_{i+1}",
                    filepath=sound_path,
                    channel=channel,
                    frame_start=frame_position
                )
                
                # Calculate sound length from first strip
                if sound_length is None:
                    if hasattr(strip, 'frame_final_end'):
                        sound_length = strip.frame_final_end - strip.frame_final_start
                    elif hasattr(strip, 'frame_end'):
                        sound_length = strip.frame_end - strip.frame_start
                    else:
                        sound_length = 48  # Fallback
                
                # Move to next position based on offset setting
                if custom_offset > 0:
                    # Use custom frame offset
                    frame_position += custom_offset
                else:
                    # Back to back (use sound length)
                    if hasattr(strip, 'frame_final_end'):
                        frame_position = strip.frame_final_end
                    elif hasattr(strip, 'frame_end'):
                        frame_position = strip.frame_end
                    else:
                        frame_position += sound_length
                    
                inserted_count += 1
            except Exception as e:
                self.report({'ERROR'}, f"Failed to add strip: {e}")
                return {'CANCELLED'}

        self.report({'INFO'}, f"Inserted {inserted_count} event sounds starting at frame {current_frame}")
        return {'FINISHED'}


class VSE_PT_EventSoundsPanel(Panel):
    """Panel in the N-panel of the 3D Viewport"""
    bl_label = "Event Sounds"
    bl_idname = "VSE_PT_event_sounds_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Event Sounds"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.vse_event_sound_settings
        
        # Sound file selection
        box = layout.box()
        box.label(text="Sound File:", icon='SOUND')
        
        if settings.sound_file:
            # Show current file name
            filename = os.path.basename(settings.sound_file)
            box.label(text=filename)
        else:
            box.label(text="(Using default sound)")
        
        box.operator(
            "vse_event.select_sound_file",
            text="Select Sound File",
            icon='FILEBROWSER'
        )
        
        layout.separator()
        
        # Settings
        box = layout.box()
        box.label(text="Settings:", icon='SETTINGS')
        col = box.column(align=True)
        col.prop(settings, "repeat_count", text="Repeat Count")
        col.prop(settings, "frame_offset", text="Frame Offset")
        
        # Info about frame offset
        if settings.frame_offset == 0:
            box.label(text="(Back to back)", icon='INFO')
        else:
            box.label(text=f"(Every {settings.frame_offset} frames)", icon='INFO')
        
        layout.separator()
        
        # Main button to insert sounds
        layout.operator(
            VSE_OT_InsertEventSound.bl_idname,
            text=f"Insert {settings.repeat_count}x Sound",
            icon='SPEAKER'
        )
        
        # Info about where sounds will be inserted
        box = layout.box()
        box.label(text="Inserts into the VSE", icon='SEQUENCE')
        box.label(text="starting at playhead")


def register():
    bpy.types.Scene.vse_event_sound_settings = PointerProperty(type=VSE_PG_EventSoundSettings)


def unregister():
    del bpy.types.Scene.vse_event_sound_settings
