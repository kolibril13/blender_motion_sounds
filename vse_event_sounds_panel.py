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
import math
import random
from bpy.types import Panel, PropertyGroup, Operator
from bpy.props import PointerProperty, StringProperty, FloatProperty, EnumProperty, BoolProperty


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
    
    # Crossing speed volume settings
    speed_volume_softer: FloatProperty(
        name="Softer",
        description="Volume for the slowest Z-crossings",
        default=0.3,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    
    speed_volume_louder: FloatProperty(
        name="Louder",
        description="Volume for the fastest Z-crossings",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    
    # Camera distance volume settings
    camera_volume_softer: FloatProperty(
        name="Softer",
        description="Volume for bones farthest from camera",
        default=0.3,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    
    camera_volume_louder: FloatProperty(
        name="Louder",
        description="Volume for bones nearest to camera",
        default=1.0,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
    )
    
    # Randomize volume settings
    use_volume_randomness: BoolProperty(
        name="Randomize Volume",
        description="Add random variation to the final volume",
        default=True,
    )
    
    volume_randomness: FloatProperty(
        name="Amount",
        description="Random variation amount (0 = no variation, 1 = can reduce to 0)",
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
    
    z_crossing_threshold: FloatProperty(
        name="Z Threshold",
        description="Z height at which crossings are detected",
        default=0.1,
        soft_min=-10.0,
        soft_max=10.0,
        unit='LENGTH',
    )
    
    use_speed_volume: BoolProperty(
        name="Crossing Speed → Volume",
        description="Louder volume for faster Z-crossings",
        default=True,
    )
    
    use_camera_volume_pan: BoolProperty(
        name="Camera Distance → Volume & Pan",
        description="Volume from camera distance and stereo pan from horizontal angle in camera view",
        default=False,
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


def get_bone_color_index(bone_name, bone_color_map):
    """Get a consistent color index for a bone name.
    
    Bones are assigned colors in the order they first appear.
    Each unique bone gets a different color (cycling through 9 colors).
    
    Args:
        bone_name: The name of the bone
        bone_color_map: A dict mapping bone names to color indices (modified in place)
    
    Returns:
        Color index (1-9) for use with Blender's COLOR_01 through COLOR_09
    """
    if bone_name not in bone_color_map:
        # Assign next available color index (1-9, cycling)
        next_index = (len(bone_color_map) % 9) + 1
        bone_color_map[bone_name] = next_index
    
    return bone_color_map[bone_name]


def apply_strip_color_by_bone(strip, bone_name, bone_color_map):
    """Apply a color tag to a strip based on the bone name.
    
    Each unique bone gets a consistent color across all its strips.
    """
    # Blender 4.0+ uses color_tag (enum) with COLOR_01 through COLOR_09
    if hasattr(strip, 'color_tag'):
        tag_index = get_bone_color_index(bone_name, bone_color_map)
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
            # Check bone selection state directly from the pose bone
            # In Blender 5.0+, select was moved from Bone to PoseBone
            # Also avoids using bpy.context.selected_pose_bones which is
            # unavailable when the operator is invoked from a sidebar panel
            for pose_bone in armature_obj.pose.bones:
                if pose_bone.select:
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
        use_speed = settings.use_speed_volume
        use_camera = settings.use_camera_volume_pan
        
        # Validate camera if camera volume & pan is enabled
        camera_obj = None
        if use_camera:
            camera_obj = context.scene.camera
            if not camera_obj:
                self.report({'ERROR'}, "No active camera in scene. Set a camera or disable Camera Distance → Volume & Pan.")
                return {'CANCELLED'}
        
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
        threshold = settings.z_crossing_threshold
        
        # Store position data for camera-based volume & pan calculations
        crossing_positions = {}  # frame -> (bone_world_pos, camera_matrix)
        
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
                            if use_camera:
                                crossing_positions[frame] = (
                                    tail_world.copy(),
                                    camera_obj.matrix_world.copy(),
                                )
                
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
        
        # Compute camera distance normalization and horizontal FOV for pan
        if use_camera:
            distances = []
            for frame in crossing_frames:
                bone_pos, cam_matrix = crossing_positions[frame]
                cam_pos = cam_matrix.translation
                distance = (bone_pos - cam_pos).length
                distances.append(distance)
            max_distance = max(distances) if distances else 1.0
            min_distance = min(distances) if distances else 0.0
            distance_range = max_distance - min_distance if max_distance > min_distance else 1.0
            
            # Compute horizontal FOV for pan normalization
            cam_data = camera_obj.data
            render = context.scene.render
            aspect_x = render.resolution_x * render.pixel_aspect_x
            aspect_y = render.resolution_y * render.pixel_aspect_y
            if cam_data.sensor_fit == 'VERTICAL':
                h_fov = 2 * math.atan(math.tan(cam_data.angle / 2) * (aspect_x / aspect_y))
            elif cam_data.sensor_fit == 'HORIZONTAL':
                h_fov = cam_data.angle
            else:  # AUTO
                if aspect_x >= aspect_y:
                    h_fov = cam_data.angle
                else:
                    h_fov = 2 * math.atan(math.tan(cam_data.angle / 2) * (aspect_x / aspect_y))
            half_fov = h_fov / 2 if h_fov > 0 else math.radians(30)
        
        # Get the correct scene for the sequencer
        seq_scene = get_sequencer_scene(context)
        
        # Make sure we have a sequence editor
        if not seq_scene.sequence_editor:
            seq_scene.sequence_editor_create()
        
        sed = seq_scene.sequence_editor
        
        # Find the first completely empty channel for this import batch
        base_channel = find_next_available_channel(sed)
        
        # Insert sounds at crossing frames
        inserted_count = 0
        new_strips = []
        use_randomness = settings.use_volume_randomness
        volume_randomness = settings.volume_randomness
        
        # Track bone colors - each unique bone gets a consistent color
        bone_color_map = {}
        # Track which bone each strip belongs to (for reapplying colors after channel separation)
        strip_bone_map = {}
        
        for frame in crossing_frames:
            try:
                # Get the bone name that triggered this crossing
                crossing_speed, bone_name = crossing_data[frame]
                
                # Determine which sound file to use
                if selection_mode == 'RANDOM' and available_sound_files:
                    current_sound_path = os.path.join(sound_folder, random.choice(available_sound_files))
                else:
                    current_sound_path = sound_path
                
                # Calculate volume from each active effect, then combine
                pan = 0.0
                volume = 1.0
                
                if use_speed:
                    # Speed: faster crossing → louder
                    if speed_range > 0:
                        speed_factor = (crossing_speed - min_speed) / speed_range
                    else:
                        speed_factor = 1.0
                    speed_vol = settings.speed_volume_softer + speed_factor * (settings.speed_volume_louder - settings.speed_volume_softer)
                    volume *= speed_vol
                
                if use_camera:
                    # Camera distance: closer → louder
                    bone_pos, cam_matrix = crossing_positions[frame]
                    cam_pos = cam_matrix.translation
                    distance = (bone_pos - cam_pos).length
                    if distance_range > 0:
                        camera_factor = 1.0 - (distance - min_distance) / distance_range
                    else:
                        camera_factor = 1.0
                    cam_vol = settings.camera_volume_softer + camera_factor * (settings.camera_volume_louder - settings.camera_volume_softer)
                    volume *= cam_vol
                    
                    # Pan: project bone position into camera's local space
                    cam_inv = cam_matrix.inverted()
                    local_pos = cam_inv @ bone_pos
                    # In camera space: X = right, -Z = forward
                    depth = -local_pos.z
                    if depth > 0:
                        angle = math.atan2(local_pos.x, depth)
                        pan = max(-1.0, min(1.0, angle / half_fov))
                    else:
                        pan = 0.0
                
                # Apply random variation (if enabled)
                if use_randomness:
                    final_volume = get_random_volume(volume, volume_randomness)
                else:
                    final_volume = volume
                
                # Format name with volume (and pan info when camera is active)
                volume_percent = int(round(final_volume * 100))
                if use_camera:
                    if pan < -0.01:
                        pan_str = f"L{int(abs(pan) * 100)}"
                    elif pan > 0.01:
                        pan_str = f"R{int(abs(pan) * 100)}"
                    else:
                        pan_str = "C"
                    strip_display_name = f"{bone_name}_v{volume_percent}_{pan_str}"
                else:
                    strip_display_name = f"{bone_name}_v{volume_percent}"
                
                strip = add_sound_strip(
                    sed,
                    name=strip_display_name,
                    filepath=current_sound_path,
                    channel=base_channel,
                    frame_start=frame
                )
                
                # Apply color based on the bone name (each bone gets a unique color)
                apply_strip_color_by_bone(strip, bone_name, bone_color_map)
                
                # Track which bone this strip belongs to
                strip_bone_map[strip] = bone_name
                
                # Apply the calculated volume and pan
                if hasattr(strip, 'volume'):
                    strip.volume = final_volume
                if use_camera and hasattr(strip, 'pan'):
                    strip.pan = pan
                
                new_strips.append(strip)
                inserted_count += 1
            except Exception as e:
                self.report({'WARNING'}, f"Failed to add strip at frame {frame}: {e}")
        
        # Separate overlapping strips onto different channels (starting from base_channel)
        if new_strips:
            separate_overlapping_strips(new_strips, base_channel)
            # Reapply bone-based colors after channel separation (strips may have moved)
            for strip in new_strips:
                if strip in strip_bone_map:
                    apply_strip_color_by_bone(strip, strip_bone_map[strip], bone_color_map)
        
        self.report({'INFO'}, f"Added {inserted_count} sounds at Z-crossing frames (channel {base_channel}+)")
        return {'FINISHED'}


class VSE_OT_RenderAudio(Operator):
    """Render the scene's audio to a sound file (same as Render > Render Audio)"""
    bl_idname = "vse_event.render_audio"
    bl_label = "Render Audio"
    bl_options = {'REGISTER'}

    def execute(self, context):
        # Invoke the built-in mixdown operator with its file dialog
        bpy.ops.sound.mixdown('INVOKE_DEFAULT')
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


class VSE_OT_UseDefaultSounds(Operator):
    """Use the bundled CC0-licensed default sound files"""
    bl_idname = "vse_event.use_default_sounds"
    bl_label = "Use Default (CC0)"
    bl_options = {'REGISTER'}
    
    def execute(self, context):
        # Get the path to the bundled sounds folder
        addon_dir = os.path.dirname(os.path.realpath(__file__))
        sounds_folder = os.path.join(addon_dir, "sounds")
        
        if os.path.isdir(sounds_folder):
            context.scene.vse_event_sound_settings.sound_folder = sounds_folder
            self.report({'INFO'}, f"Using default sounds from: {sounds_folder}")
            return {'FINISHED'}
        else:
            self.report({'ERROR'}, "Default sounds folder not found")
            return {'CANCELLED'}


class VSE_PT_MotionSoundsPanel(Panel):
    """Main panel in the N-panel of the 3D Viewport"""
    bl_label = "Motion Sounds"
    bl_idname = "VSE_PT_motion_sounds_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Sounds"

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
        
        row = col.row(align=True)
        row.operator(
            "vse_event.use_default_sounds",
            text="Use Default (CC0)",
            icon='PACKAGE'
        )
        row.operator(
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


class VSE_PT_SpeedVolumePanel(Panel):
    """Sub-panel to enable crossing-speed based volume"""
    bl_label = "Crossing Speed → Volume"
    bl_idname = "VSE_PT_speed_volume_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Sounds"
    bl_parent_id = "VSE_PT_motion_sounds_panel"
    bl_order = 1

    def draw_header(self, context):
        settings = context.scene.vse_event_sound_settings
        self.layout.prop(settings, "use_speed_volume", text="")

    def draw(self, context):
        layout = self.layout
        settings = context.scene.vse_event_sound_settings
        layout.active = settings.use_speed_volume

        col = layout.column(align=True)
        col.prop(settings, "speed_volume_softer", text="Softer (slowest)", slider=True)
        col.prop(settings, "speed_volume_louder", text="Louder (fastest)", slider=True)


class VSE_PT_CameraVolumePanPanel(Panel):
    """Sub-panel to enable camera-distance based volume and stereo pan"""
    bl_label = "Camera Distance → Volume & Pan"
    bl_idname = "VSE_PT_camera_volume_pan_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Sounds"
    bl_parent_id = "VSE_PT_motion_sounds_panel"
    bl_order = 2

    def draw_header(self, context):
        settings = context.scene.vse_event_sound_settings
        self.layout.prop(settings, "use_camera_volume_pan", text="")

    def draw(self, context):
        layout = self.layout
        settings = context.scene.vse_event_sound_settings
        layout.active = settings.use_camera_volume_pan

        col = layout.column(align=True)
        col.prop(settings, "camera_volume_softer", text="Softer (farthest)", slider=True)
        col.prop(settings, "camera_volume_louder", text="Louder (nearest)", slider=True)
        col.separator()
        col.label(text="Pan follows camera angle", icon='INFO')


class VSE_PT_RandomizeVolumePanel(Panel):
    """Sub-panel to enable random volume variation"""
    bl_label = "Randomize Volume"
    bl_idname = "VSE_PT_randomize_volume_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Sounds"
    bl_parent_id = "VSE_PT_motion_sounds_panel"
    bl_order = 3

    def draw_header(self, context):
        settings = context.scene.vse_event_sound_settings
        self.layout.prop(settings, "use_volume_randomness", text="")

    def draw(self, context):
        layout = self.layout
        settings = context.scene.vse_event_sound_settings
        layout.active = settings.use_volume_randomness

        col = layout.column(align=True)
        col.prop(settings, "volume_randomness", text="Amount", slider=True)


class VSE_PT_ZCrossingPanel(Panel):
    """Sub-panel for Z-crossing sound triggers"""
    bl_label = "Trigger on Z-Crossing"
    bl_idname = "VSE_PT_z_crossing_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Sounds"
    bl_parent_id = "VSE_PT_motion_sounds_panel"
    bl_order = 4

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
        
        # Z threshold
        col.prop(settings, "z_crossing_threshold", text="Z Threshold")
        
        layout.separator()
        
        # Main button
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator(
            VSE_OT_AddSoundsAtZCrossings.bl_idname,
            text="Add Sounds at Crossings",
            icon='ADD'
        )


class VSE_PT_RenderAudioPanel(Panel):
    """Sub-panel with a Render Audio button"""
    bl_label = "Render Audio"
    bl_idname = "VSE_PT_render_audio_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Sounds"
    bl_parent_id = "VSE_PT_motion_sounds_panel"
    bl_options = {'DEFAULT_CLOSED'}
    bl_order = 5

    def draw(self, context):
        layout = self.layout
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator(
            VSE_OT_RenderAudio.bl_idname,
            text="Render Audio",
            icon='FILE_SOUND'
        )


def register():
    bpy.types.Scene.vse_event_sound_settings = PointerProperty(type=VSE_PG_EventSoundSettings)


def unregister():
    del bpy.types.Scene.vse_event_sound_settings
