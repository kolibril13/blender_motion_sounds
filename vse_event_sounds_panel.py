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
import random
from bpy.types import Panel, PropertyGroup, Operator
from bpy.props import PointerProperty, StringProperty, FloatProperty, EnumProperty


def get_armatures(self, context):
    """Return a list of armature objects for the enum property."""
    items = []
    for i, obj in enumerate(bpy.data.objects):
        if obj.type == 'ARMATURE':
            items.append((obj.name, obj.name, f"Armature: {obj.name}", 'ARMATURE_DATA', i))
    if not items:
        items.append(('NONE', "No Armatures", "No armatures available", 'ERROR', 0))
    return items


def get_bone_collections(self, context):
    """Return a list of bone collections for the selected armature."""
    items = [
        ('ALL', "All Bones", "Monitor all bones in the armature", 'BONE_DATA', 0),
        ('SELECTED', "Selected Bones", "Monitor only bones currently selected in Pose Mode", 'RESTRICT_SELECT_OFF', 1),
    ]
    
    settings = context.scene.vse_event_sound_settings
    armature_name = settings.z_crossing_armature
    
    if armature_name and armature_name != 'NONE' and armature_name in bpy.data.objects:
        armature_obj = bpy.data.objects[armature_name]
        if armature_obj.type == 'ARMATURE' and armature_obj.data:
            armature_data = armature_obj.data
            # Blender 4.0+ uses collections instead of bone_groups
            if hasattr(armature_data, 'collections'):
                for i, bcol in enumerate(armature_data.collections):
                    items.append((bcol.name, bcol.name, f"Bone Collection: {bcol.name}", 'GROUP_BONE', i + 2))
            # Fallback for older Blender versions with bone_groups
            elif hasattr(armature_data, 'bone_groups') and armature_data.bone_groups:
                for i, bg in enumerate(armature_data.bone_groups):
                    items.append((bg.name, bg.name, f"Bone Group: {bg.name}", 'GROUP_BONE', i + 2))
    
    return items


SUPPORTED_AUDIO_EXTENSIONS = {'.wav', '.mp3', '.ogg', '.flac', '.aiff', '.aif'}


def get_sound_files_from_folder(folder_path):
    """Get all supported audio files from a folder."""
    if not folder_path or not os.path.isdir(folder_path):
        return []
    
    sound_files = []
    for filename in os.listdir(folder_path):
        ext = os.path.splitext(filename)[1].lower()
        if ext in SUPPORTED_AUDIO_EXTENSIONS:
            sound_files.append(filename)
    
    return sorted(sound_files)


def get_sound_files_enum(self, context):
    """Return a list of sound files for the enum property."""
    settings = context.scene.vse_event_sound_settings
    folder_path = bpy.path.abspath(settings.sound_folder)
    
    items = []
    sound_files = get_sound_files_from_folder(folder_path)
    
    if not sound_files:
        items.append(('NONE', "No sounds found", "Select a folder with audio files", 'ERROR', 0))
    else:
        for i, filename in enumerate(sound_files):
            # Use filename as both identifier and display name
            items.append((filename, filename, f"Sound file: {filename}", 'SOUND', i))
    
    return items


class VSE_PG_EventSoundSettings(PropertyGroup):
    """Property group for event sound settings."""
    
    sound_folder: StringProperty(
        name="Sound Folder",
        description="Path to folder containing sound files",
        subtype='DIR_PATH',
        default="",
    )
    
    sound_selection_mode: EnumProperty(
        name="Sound Selection Mode",
        description="How to select sounds for interaction events",
        items=[
            ('RANDOM', "Random Sound", "Randomly select a sound file from the folder for each event", 'FILE_REFRESH', 0),
            ('SINGLE', "Single Sound", "Use one selected sound file for every event", 'SOUND', 1),
        ],
        default='RANDOM',
    )
    
    sound_file: EnumProperty(
        name="Sound File",
        description="Select a sound file from the folder",
        items=get_sound_files_enum,
    )
    
    volume_slowest: FloatProperty(
        name="Slowest Volume",
        description="Volume for the slowest Z-crossings",
        default=0.3,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    
    volume_fastest: FloatProperty(
        name="Fastest Volume",
        description="Volume for the fastest Z-crossings",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    
    volume_randomness: FloatProperty(
        name="Volume Randomness",
        description="Random variation applied after speed-based volume (0 = no variation, 1 = can reduce to 0)",
        default=0.2,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    
    # Armature/Bone Collection settings
    z_crossing_armature: EnumProperty(
        name="Armature",
        description="Armature to monitor bone Z-crossings",
        items=get_armatures,
    )
    
    z_crossing_bone_collection: EnumProperty(
        name="Bone Collection",
        description="Bone collection to filter which bones to monitor",
        items=get_bone_collections,
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


def apply_strip_color_by_channel(strip, channel):
    """Apply a color tag to a strip based on the channel number.
    
    Each import batch gets a unique color based on its starting channel.
    """
    # Blender 4.0+ uses color_tag (enum) with COLOR_01 through COLOR_09
    if hasattr(strip, 'color_tag'):
        # Use channel to determine color (cycling through 9 colors)
        tag_index = ((channel - 1) % 9) + 1  # COLOR_01 to COLOR_09
        strip.color_tag = f'COLOR_{tag_index:02d}'


def get_random_volume(base_volume, randomness):
    """Calculate a random volume based on randomness factor.
    
    With randomness=0, returns base_volume.
    With randomness=1, returns a value between 0 and base_volume.
    """
    if randomness <= 0:
        return base_volume
    
    # Calculate the minimum volume based on randomness
    # At randomness=1, min_volume=0. At randomness=0, min_volume=base_volume
    min_volume = base_volume * (1.0 - randomness)
    return random.uniform(min_volume, base_volume)


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


def find_next_available_channel(sed):
    """Find the next channel above all existing strips.
    
    Returns the channel number one above the highest used channel.
    This ensures each new import batch starts on a fresh channel
    and gets a new color.
    """
    all_strips = get_all_strips(sed)
    if not all_strips:
        return 1
    
    # Find the highest channel in use
    max_channel = max(s.channel for s in all_strips)
    
    # Return the next channel above all existing strips
    return max_channel + 1


def strips_overlap(strip1, strip2):
    """Check if two strips overlap in time."""
    # Get start and end frames for each strip
    start1 = strip1.frame_final_start if hasattr(strip1, 'frame_final_start') else strip1.frame_start
    end1 = strip1.frame_final_end if hasattr(strip1, 'frame_final_end') else (strip1.frame_start + 48)
    start2 = strip2.frame_final_start if hasattr(strip2, 'frame_final_start') else strip2.frame_start
    end2 = strip2.frame_final_end if hasattr(strip2, 'frame_final_end') else (strip2.frame_start + 48)
    
    # Check for overlap (strips overlap if one starts before the other ends)
    return start1 < end2 and start2 < end1


def separate_overlapping_strips(strips, base_channel):
    """Separate overlapping strips onto different channels.
    
    Uses a greedy algorithm: for each strip, find the lowest channel
    where it doesn't overlap with any already-placed strip.
    """
    if not strips:
        return
    
    # Sort strips by their start frame
    sorted_strips = sorted(strips, key=lambda s: s.frame_final_start if hasattr(s, 'frame_final_start') else s.frame_start)
    
    # Track which strips are on which channel
    # channel_strips[channel] = list of strips on that channel
    channel_strips = {}
    
    for strip in sorted_strips:
        # Find the lowest channel where this strip fits without overlap
        test_channel = base_channel
        while True:
            if test_channel not in channel_strips:
                # Empty channel, use it
                channel_strips[test_channel] = [strip]
                strip.channel = test_channel
                break
            
            # Check if strip overlaps with any existing strip on this channel
            has_overlap = False
            for existing_strip in channel_strips[test_channel]:
                if strips_overlap(strip, existing_strip):
                    has_overlap = True
                    break
            
            if not has_overlap:
                # No overlap, use this channel
                channel_strips[test_channel].append(strip)
                strip.channel = test_channel
                break
            
            # Try next channel
            test_channel += 1


class VSE_OT_AddSoundsAtZCrossings(Operator):
    """Scan timeline for bones crossing Z threshold and add sounds at those frames"""
    bl_idname = "vse_event.add_sounds_at_z_crossings"
    bl_label = "Add Sounds at Z Crossings"
    bl_options = {'REGISTER', 'UNDO'}
    
    def get_bones_in_collection(self, armature_obj, bone_collection_name):
        """Get list of bone names that belong to the specified bone collection."""
        armature_data = armature_obj.data
        bone_names = []
        
        if bone_collection_name == 'ALL':
            return [bone.name for bone in armature_obj.pose.bones]
        
        if bone_collection_name == 'SELECTED':
            # Get currently selected pose bones from context
            # This works in Pose Mode and returns the selected bones
            selected_pose_bones = bpy.context.selected_pose_bones
            if selected_pose_bones:
                for pose_bone in selected_pose_bones:
                    # id_data gives us the Armature data block (not the Object)
                    # Compare with armature_obj.data to check it's the same armature
                    if pose_bone.id_data.name == armature_data.name:
                        bone_names.append(pose_bone.name)
            return bone_names
        
        # Blender 4.0+ uses bone collections
        if hasattr(armature_data, 'collections'):
            for bcol in armature_data.collections:
                if bcol.name == bone_collection_name:
                    # Get bones assigned to this collection
                    for bone in armature_data.bones:
                        if hasattr(bone, 'collections') and bcol in bone.collections.values():
                            bone_names.append(bone.name)
                        elif hasattr(bcol, 'bones'):
                            if bone.name in [b.name for b in bcol.bones]:
                                bone_names.append(bone.name)
                    break
        
        return bone_names
    
    def execute(self, context):
        settings = context.scene.vse_event_sound_settings
        armature_name = settings.z_crossing_armature
        direction = settings.z_crossing_direction
        
        # Check if armature exists
        if armature_name == 'NONE' or armature_name not in bpy.data.objects:
            self.report({'ERROR'}, "Please select a valid armature")
            return {'CANCELLED'}
        
        armature_obj = bpy.data.objects[armature_name]
        if armature_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"'{armature_name}' is not an armature")
            return {'CANCELLED'}
        
        # Get the sound folder and selection mode
        sound_folder = bpy.path.abspath(settings.sound_folder)
        selection_mode = settings.sound_selection_mode
        
        # For single mode, get the selected file
        # For random mode, we'll get the list of available files
        available_sound_files = []
        sound_path = None
        
        if sound_folder and os.path.isdir(sound_folder):
            available_sound_files = get_sound_files_from_folder(sound_folder)
            
            if selection_mode == 'SINGLE':
                sound_filename = settings.sound_file
                if sound_filename and sound_filename != 'NONE':
                    sound_path = os.path.join(sound_folder, sound_filename)
            elif selection_mode == 'RANDOM':
                if not available_sound_files:
                    self.report({'ERROR'}, "No sound files found in the selected folder")
                    return {'CANCELLED'}
                # We'll select randomly per event, so just validate folder has sounds
                sound_path = "RANDOM_MODE"
        
        # Fall back to default bundled sound if no file selected (single mode only)
        if selection_mode == 'SINGLE' and (not sound_path or not os.path.exists(sound_path)):
            addon_dir = os.path.dirname(os.path.realpath(__file__))
            sound_path = os.path.join(addon_dir, "geiger_counter_sound.wav")
        
        # Validate sound path exists (skip for random mode which was validated above)
        if selection_mode == 'SINGLE' and not os.path.exists(sound_path):
            self.report({'ERROR'}, f"Sound file not found: {sound_path}")
            return {'CANCELLED'}
        
        # Get timeline range
        scene = context.scene
        frame_start = scene.frame_start
        frame_end = scene.frame_end
        
        # Store current frame to restore later
        original_frame = scene.frame_current
        
        # Get bones to monitor
        bone_collection_name = settings.z_crossing_bone_collection
        bone_names = self.get_bones_in_collection(armature_obj, bone_collection_name)
        
        if not bone_names:
            if bone_collection_name == 'SELECTED':
                self.report({'ERROR'}, "No bones selected. Select bones in Pose Mode first.")
            else:
                self.report({'ERROR'}, f"No bones found in bone collection '{bone_collection_name}'")
            return {'CANCELLED'}
        
        # Get pose bones references once
        pose_bones = [armature_obj.pose.bones[name] for name in bone_names if name in armature_obj.pose.bones]
        
        if not pose_bones:
            self.report({'ERROR'}, "No valid pose bones found")
            return {'CANCELLED'}
        
        # Find all Z-crossing frames with their crossing speeds and bone names
        # Dict: frame -> (speed, bone_name) - keeps the fastest crossing per frame
        crossing_data = {}
        
        # Track previous Z positions for each bone
        prev_z = {bone.name: None for bone in pose_bones}
        threshold = 0.1
        
        # Single pass through timeline - evaluate all bones at each frame
        for frame in range(frame_start, frame_end + 1):
            scene.frame_set(frame)
            
            # Get world matrix once per frame
            world_matrix = armature_obj.matrix_world
            
            # Check all bones at this frame
            for pose_bone in pose_bones:
                tail_world = world_matrix @ pose_bone.tail
                world_z = tail_world.z
                bone_prev_z = prev_z[pose_bone.name]
                
                # Inline crossing check for speed
                if bone_prev_z is not None:
                    if direction == 'BOTH':
                        crossed = (bone_prev_z < threshold and world_z >= threshold) or (bone_prev_z > threshold and world_z <= threshold)
                    elif direction == 'UP':
                        crossed = bone_prev_z < threshold and world_z >= threshold
                    else:  # DOWN
                        crossed = bone_prev_z > threshold and world_z <= threshold
                    
                    if crossed:
                        # Calculate crossing speed (absolute Z delta per frame)
                        crossing_speed = abs(world_z - bone_prev_z)
                        # Keep the maximum speed if multiple bones cross at the same frame
                        if frame not in crossing_data or crossing_speed > crossing_data[frame][0]:
                            crossing_data[frame] = (crossing_speed, pose_bone.name)
                
                prev_z[pose_bone.name] = world_z
        
        # Restore original frame
        scene.frame_set(original_frame)
        
        if bone_collection_name == 'ALL':
            source_name = "all bones"
        elif bone_collection_name == 'SELECTED':
            source_name = f"{len(bone_names)} selected bones"
        else:
            source_name = f"bones in '{bone_collection_name}'"
        
        if not crossing_data:
            self.report({'WARNING'}, f"No Z crossings found for {source_name}")
            return {'CANCELLED'}
        
        # Sort frames and normalize speeds
        crossing_frames = sorted(crossing_data.keys())
        speeds = [crossing_data[f][0] for f in crossing_frames]  # Extract speed from tuple
        max_speed = max(speeds) if speeds else 1.0
        min_speed = min(speeds) if speeds else 0.0
        speed_range = max_speed - min_speed if max_speed > min_speed else 1.0
        
        # Get the correct scene for the sequencer
        seq_scene = get_sequencer_scene(context)
        
        # Make sure we have a sequence editor
        if not seq_scene.sequence_editor:
            seq_scene.sequence_editor_create()
        
        sed = seq_scene.sequence_editor
        
        # Find the first completely empty channel for this import batch
        base_channel = find_next_available_channel(sed)
        
        # Insert sounds at crossing frames with speed-based volume
        inserted_count = 0
        new_strips = []
        volume_slowest = settings.volume_slowest
        volume_fastest = settings.volume_fastest
        volume_randomness = settings.volume_randomness
        
        for frame in crossing_frames:
            try:
                # Get the bone name that triggered this crossing
                crossing_speed, bone_name = crossing_data[frame]
                
                # Determine which sound file to use
                if selection_mode == 'RANDOM' and available_sound_files:
                    current_sound_path = os.path.join(sound_folder, random.choice(available_sound_files))
                else:
                    current_sound_path = sound_path
                
                # Calculate speed-based volume (faster crossing = louder)
                # Normalize speed to 0-1 range (crossing_speed already extracted above)
                if speed_range > 0:
                    # Normalize: 0 = slowest, 1 = fastest
                    normalized_speed = (crossing_speed - min_speed) / speed_range
                else:
                    normalized_speed = 1.0
                
                # Map to user-defined volume range
                base_volume = volume_slowest + (normalized_speed * (volume_fastest - volume_slowest))
                
                # Apply random variation
                final_volume = get_random_volume(base_volume, volume_randomness)
                
                # Format volume as percentage for the name (e.g., 0.75 -> 75)
                volume_percent = int(round(final_volume * 100))
                
                strip = add_sound_strip(
                    sed,
                    name=f"{bone_name}_{frame}_v{volume_percent}",
                    filepath=current_sound_path,
                    channel=base_channel,
                    frame_start=frame
                )
                
                # Apply color based on the base channel (each import batch gets one color)
                apply_strip_color_by_channel(strip, base_channel)
                
                # Apply the calculated volume
                if hasattr(strip, 'volume'):
                    strip.volume = final_volume
                
                new_strips.append(strip)
                inserted_count += 1
            except Exception as e:
                self.report({'WARNING'}, f"Failed to add strip at frame {frame}: {e}")
        
        # Separate overlapping strips onto different channels (starting from base_channel)
        if new_strips:
            separate_overlapping_strips(new_strips, base_channel)
            # Apply the same color to all strips (they may have moved to different channels)
            for strip in new_strips:
                apply_strip_color_by_channel(strip, base_channel)
        
        self.report({'INFO'}, f"Added {inserted_count} sounds at Z-crossing frames (channel {base_channel}+)")
        return {'FINISHED'}


class VSE_OT_SelectSoundFolder(Operator):
    """Open file browser to select a folder containing sound files"""
    bl_idname = "vse_event.select_sound_folder"
    bl_label = "Select Sound Folder"
    bl_options = {'REGISTER'}
    
    directory: StringProperty(
        subtype='DIR_PATH',
        default="",
    )
    
    def execute(self, context):
        context.scene.vse_event_sound_settings.sound_folder = self.directory
        return {'FINISHED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


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
        
        # Sound folder selection
        col = layout.column(align=True)
        col.label(text="Sound Folder:", icon='FILE_FOLDER')
        
        row = col.row(align=True)
        if settings.sound_folder:
            folder_name = os.path.basename(os.path.normpath(settings.sound_folder))
            row.label(text=folder_name, icon='CHECKMARK')
        else:
            row.label(text="Not selected", icon='ERROR')
        
        col.operator(
            "vse_event.select_sound_folder",
            text="Select Folder...",
            icon='FILEBROWSER'
        )
        
        # Sound selection mode and file dropdown (only show if folder is selected)
        if settings.sound_folder:
            layout.separator()
            col = layout.column(align=True)
            col.label(text="Sound Selection:", icon='SOUND')
            row = col.row(align=True)
            row.prop(settings, "sound_selection_mode", expand=True)
            
            # Only show sound file dropdown in single mode
            if settings.sound_selection_mode == 'SINGLE':
                col.separator()
                col.label(text="Sound File:", icon='PLAY_SOUND')
                col.prop(settings, "sound_file", text="")
            else:
                # Show info about random mode
                col.separator()
                folder_path = bpy.path.abspath(settings.sound_folder)
                sound_count = len(get_sound_files_from_folder(folder_path))
                col.label(text=f"Will use {sound_count} sound(s) randomly", icon='INFO')
        
        layout.separator()
        
        # Volume settings
        col = layout.column(align=True)
        col.label(text="Volume (Speed-Based):", icon='SPEAKER')
        col.prop(settings, "volume_slowest", text="Slowest", slider=True)
        col.prop(settings, "volume_fastest", text="Fastest", slider=True)
        
        col.separator()
        col.prop(settings, "volume_randomness", text="Randomness", slider=True)


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
        
        col = layout.column(align=True)
        
        # Armature selector
        col.prop(settings, "z_crossing_armature", text="Armature")
        
        # Bone collection selector
        col.prop(settings, "z_crossing_bone_collection", text="Bones")
        
        col.separator()
        
        # Direction selector
        col.prop(settings, "z_crossing_direction", text="Direction")
        
        layout.separator()
        
        # Main button
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator(
            VSE_OT_AddSoundsAtZCrossings.bl_idname,
            text="Add Sounds at Crossings",
            icon='ADD'
        )
        
        # Info
        box = layout.box()
        col = box.column(align=True)
        col.scale_y = 0.8
        col.label(text="Triggers at Z=0.1 crossings")
        col.label(text="Faster crossings = louder")


def register():
    bpy.types.Scene.vse_event_sound_settings = PointerProperty(type=VSE_PG_EventSoundSettings)


def unregister():
    del bpy.types.Scene.vse_event_sound_settings
