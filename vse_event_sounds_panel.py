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
from bpy.props import PointerProperty, StringProperty, IntProperty, FloatProperty, BoolProperty, EnumProperty


def get_collections(self, context):
    """Return a list of collections for the enum property."""
    items = []
    for i, col in enumerate(bpy.data.collections):
        items.append((col.name, col.name, f"Collection: {col.name}", 'OUTLINER_COLLECTION', i))
    if not items:
        items.append(('NONE', "No Collections", "No collections available", 'ERROR', 0))
    return items


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
    
    frame_offset: FloatProperty(
        name="Frame Offset",
        description="Number of frames between each sound (0 = back to back). Supports sub-frame values.",
        default=24.0,
        min=0.0,
        precision=3,
        step=100,  # Step of 1.0 in the UI
    )
    
    use_subframe: BoolProperty(
        name="Sub-frame Positioning",
        description="Enable sub-frame (fractional) positioning for precise timing",
        default=False,
    )
    
    # Collection Z-crossing settings
    z_crossing_collection: EnumProperty(
        name="Collection",
        description="Collection to monitor for Z=0 crossings",
        items=get_collections,
    )
    
    z_crossing_direction: EnumProperty(
        name="Direction",
        description="Which direction of crossing to detect",
        items=[
            ('BOTH', "Both", "Trigger on both upward and downward crossings"),
            ('UP', "Upward", "Trigger only when crossing from negative to positive Z"),
            ('DOWN', "Downward", "Trigger only when crossing from positive to negative Z"),
        ],
        default='BOTH',
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


class VSE_OT_AddSoundsAtZCrossings(Operator):
    """Scan timeline for objects crossing Z=0 and add sounds at those frames"""
    bl_idname = "vse_event.add_sounds_at_z_crossings"
    bl_label = "Add Sounds at Z Crossings"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        settings = context.scene.vse_event_sound_settings
        collection_name = settings.z_crossing_collection
        direction = settings.z_crossing_direction
        
        # Check if collection exists
        if collection_name == 'NONE' or collection_name not in bpy.data.collections:
            self.report({'ERROR'}, "Please select a valid collection")
            return {'CANCELLED'}
        
        collection = bpy.data.collections[collection_name]
        
        # Get all objects in the collection (including nested)
        def get_all_objects_in_collection(col):
            objects = list(col.objects)
            for child_col in col.children:
                objects.extend(get_all_objects_in_collection(child_col))
            return objects
        
        objects = get_all_objects_in_collection(collection)
        
        if not objects:
            self.report({'ERROR'}, f"Collection '{collection_name}' has no objects")
            return {'CANCELLED'}
        
        # Get the sound file path
        sound_path = bpy.path.abspath(settings.sound_file)
        if not sound_path or not os.path.exists(sound_path):
            addon_dir = os.path.dirname(os.path.realpath(__file__))
            sound_path = os.path.join(addon_dir, "geiger_counter_sound.wav")
        
        if not os.path.exists(sound_path):
            self.report({'ERROR'}, f"Sound file not found: {sound_path}")
            return {'CANCELLED'}
        
        # Get timeline range
        scene = context.scene
        frame_start = scene.frame_start
        frame_end = scene.frame_end
        
        # Store current frame to restore later
        original_frame = scene.frame_current
        
        # Find all Z-crossing frames
        crossing_frames = set()
        
        for obj in objects:
            prev_z = None
            
            for frame in range(frame_start, frame_end + 1):
                scene.frame_set(frame)
                
                # Get world-space Z position
                world_z = obj.matrix_world.translation.z
                
                if prev_z is not None:
                    # Check for crossing
                    crossed = False
                    
                    if direction == 'BOTH':
                        crossed = (prev_z < 0 and world_z >= 0) or (prev_z > 0 and world_z <= 0)
                    elif direction == 'UP':
                        crossed = prev_z < 0 and world_z >= 0
                    elif direction == 'DOWN':
                        crossed = prev_z > 0 and world_z <= 0
                    
                    if crossed:
                        crossing_frames.add(frame)
                
                prev_z = world_z
        
        # Restore original frame
        scene.frame_set(original_frame)
        
        if not crossing_frames:
            self.report({'WARNING'}, f"No Z=0 crossings found for objects in '{collection_name}'")
            return {'CANCELLED'}
        
        # Sort frames
        crossing_frames = sorted(crossing_frames)
        
        # Get the correct scene for the sequencer
        seq_scene = get_sequencer_scene(context)
        
        # Make sure we have a sequence editor
        if not seq_scene.sequence_editor:
            seq_scene.sequence_editor_create()
        
        sed = seq_scene.sequence_editor
        
        # Find an available channel
        channel = 1
        try:
            all_strips = get_all_strips(sed)
            if all_strips and len(all_strips) > 0:
                channel = max(s.channel for s in all_strips) + 1
        except Exception:
            channel = 1
        
        # Insert sounds at crossing frames
        inserted_count = 0
        for frame in crossing_frames:
            try:
                strip = add_sound_strip(
                    sed,
                    name=f"ZCross_{frame}",
                    filepath=sound_path,
                    channel=channel,
                    frame_start=frame
                )
                inserted_count += 1
            except Exception as e:
                self.report({'WARNING'}, f"Failed to add strip at frame {frame}: {e}")
        
        self.report({'INFO'}, f"Added {inserted_count} sounds at Z-crossing frames")
        return {'FINISHED'}


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
        use_subframe = settings.use_subframe

        # Insert the sound strips
        inserted_count = 0
        frame_position = float(current_frame)
        sound_length = None

        for i in range(repeat_count):
            try:
                # For strip creation, we need an integer frame
                # We'll create at the integer position then adjust if using subframe
                create_frame = int(frame_position) if use_subframe else int(round(frame_position))
                
                # Add the sound strip
                strip = add_sound_strip(
                    sed,
                    name=f"EventSound_{i+1}",
                    filepath=sound_path,
                    channel=channel,
                    frame_start=create_frame
                )
                
                # Apply sub-frame offset if enabled
                # Note: frame_start can be set to float after creation
                if use_subframe and hasattr(strip, 'frame_start'):
                    strip.frame_start = frame_position
                
                # Calculate sound length from first strip
                if sound_length is None:
                    if hasattr(strip, 'frame_final_end') and hasattr(strip, 'frame_final_start'):
                        sound_length = strip.frame_final_end - strip.frame_final_start
                    elif hasattr(strip, 'frame_end'):
                        sound_length = strip.frame_end - strip.frame_start
                    else:
                        sound_length = 48  # Fallback
                
                # Move to next position based on offset setting
                if custom_offset > 0:
                    # Use custom frame offset (can be fractional)
                    frame_position += custom_offset
                else:
                    # Back to back (use sound length)
                    if hasattr(strip, 'frame_final_end'):
                        frame_position = float(strip.frame_final_end)
                    elif hasattr(strip, 'frame_end'):
                        frame_position = float(strip.frame_end)
                    else:
                        frame_position += sound_length
                    
                inserted_count += 1
            except Exception as e:
                self.report({'ERROR'}, f"Failed to add strip: {e}")
                return {'CANCELLED'}

        self.report({'INFO'}, f"Inserted {inserted_count} event sounds starting at frame {current_frame}")
        return {'FINISHED'}


class VSE_PT_EventSoundsPanel(Panel):
    """Main panel in the N-panel of the 3D Viewport"""
    bl_label = "Event Sounds"
    bl_idname = "VSE_PT_event_sounds_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Event Sounds"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.vse_event_sound_settings
        
        # Sound file selection - compact header
        row = layout.row(align=True)
        row.label(text="Sound:", icon='SOUND')
        if settings.sound_file:
            filename = os.path.basename(settings.sound_file)
            row.label(text=filename)
        else:
            row.label(text="Default")
        
        layout.operator(
            "vse_event.select_sound_file",
            text="Browse...",
            icon='FILEBROWSER'
        )


class VSE_PT_RepeatSoundsPanel(Panel):
    """Sub-panel for repeating sounds at intervals"""
    bl_label = "Repeat at Interval"
    bl_idname = "VSE_PT_repeat_sounds_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Event Sounds"
    bl_parent_id = "VSE_PT_event_sounds_panel"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.vse_event_sound_settings
        
        # Compact settings
        col = layout.column(align=True)
        
        row = col.row(align=True)
        row.prop(settings, "repeat_count", text="Count")
        
        row = col.row(align=True)
        row.prop(settings, "frame_offset", text="Interval")
        
        layout.separator()
        
        # Main button
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator(
            VSE_OT_InsertEventSound.bl_idname,
            text=f"Insert {settings.repeat_count} Sounds",
            icon='ADD'
        )
        
        # Compact info
        row = layout.row()
        row.alignment = 'CENTER'
        if settings.frame_offset == 0:
            row.label(text="Back-to-back from playhead")
        else:
            row.label(text=f"Every {settings.frame_offset:.1f}f from playhead")


class VSE_PT_ZCrossingPanel(Panel):
    """Sub-panel for Z-crossing sound triggers"""
    bl_label = "Trigger on Z-Crossing"
    bl_idname = "VSE_PT_z_crossing_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Event Sounds"
    bl_parent_id = "VSE_PT_event_sounds_panel"

    def draw(self, context):
        layout = self.layout
        settings = context.scene.vse_event_sound_settings
        
        # Collection selector - compact
        col = layout.column(align=True)
        
        row = col.row(align=True)
        row.label(text="Collection:", icon='OUTLINER_COLLECTION')
        row = col.row(align=True)
        row.prop(settings, "z_crossing_collection", text="")
        
        col.separator()
        
        row = col.row(align=True)
        row.label(text="Direction:", icon='SORT_DESC')
        row = col.row(align=True)
        row.prop(settings, "z_crossing_direction", text="")
        
        layout.separator()
        
        # Main button
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator(
            VSE_OT_AddSoundsAtZCrossings.bl_idname,
            text="Add Sounds at Crossings",
            icon='ADD'
        )
        
        # Compact info
        row = layout.row()
        row.alignment = 'CENTER'
        row.label(text="Scans timeline for Z=0 crossings")


def register():
    bpy.types.Scene.vse_event_sound_settings = PointerProperty(type=VSE_PG_EventSoundSettings)


def unregister():
    del bpy.types.Scene.vse_event_sound_settings
