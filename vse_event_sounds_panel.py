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
import wave
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
    
    z_crossing_threshold: FloatProperty(
        name="Z Threshold",
        description="Z height at which crossings are detected",
        default=0.1,
        soft_min=-10.0,
        soft_max=10.0,
        unit='LENGTH',
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


# ── Shared helpers ───────────────────────────────────────────────────────────

def get_bones_for_collection(armature_obj, bone_collection_name):
    """Get list of bone names that belong to the specified bone collection."""
    armature_data = armature_obj.data
    bone_names = []

    if bone_collection_name == 'ALL':
        return [bone.name for bone in armature_obj.pose.bones]

    if bone_collection_name == 'SELECTED':
        selected_pose_bones = bpy.context.selected_pose_bones
        if selected_pose_bones:
            for pose_bone in selected_pose_bones:
                if pose_bone.id_data.name == armature_data.name:
                    bone_names.append(pose_bone.name)
        return bone_names

    # Blender 4.0+ uses bone collections
    if hasattr(armature_data, 'collections'):
        for bcol in armature_data.collections:
            if bcol.name == bone_collection_name:
                for bone in armature_data.bones:
                    if hasattr(bone, 'collections') and bcol in bone.collections.values():
                        bone_names.append(bone.name)
                    elif hasattr(bcol, 'bones'):
                        if bone.name in [b.name for b in bcol.bones]:
                            bone_names.append(bone.name)
                break

    return bone_names


def detect_z_crossings(scene, armature_obj, pose_bones, threshold, direction, frame_start, frame_end):
    """Detect bone Z-crossings across the timeline.

    Returns:
        dict: frame -> (crossing_speed, bone_name) for the fastest crossing per frame
    """
    crossing_data = {}
    prev_z = {bone.name: None for bone in pose_bones}

    for frame in range(frame_start, frame_end + 1):
        scene.frame_set(frame)
        world_matrix = armature_obj.matrix_world

        for pose_bone in pose_bones:
            tail_world = world_matrix @ pose_bone.tail
            world_z = tail_world.z
            bone_prev_z = prev_z[pose_bone.name]

            if bone_prev_z is not None:
                if direction == 'BOTH':
                    crossed = (bone_prev_z < threshold and world_z >= threshold) or \
                              (bone_prev_z > threshold and world_z <= threshold)
                elif direction == 'UP':
                    crossed = bone_prev_z < threshold and world_z >= threshold
                else:  # DOWN
                    crossed = bone_prev_z > threshold and world_z <= threshold

                if crossed:
                    crossing_speed = abs(world_z - bone_prev_z)
                    if frame not in crossing_data or crossing_speed > crossing_data[frame][0]:
                        crossing_data[frame] = (crossing_speed, pose_bone.name)

            prev_z[pose_bone.name] = world_z

    return crossing_data


# ── DaVinci Resolve integration ─────────────────────────────────────────────

RESOLVE_MODULES = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"
RESOLVE_LIB     = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion"


def get_audio_duration_seconds(filepath):
    """Get audio file duration in seconds using the wave module for WAV files."""
    ext = os.path.splitext(filepath)[1].lower()
    if ext == '.wav':
        try:
            with wave.open(filepath, 'r') as wf:
                return wf.getnframes() / wf.getframerate()
        except Exception:
            pass
    # Fallback: try Blender's audio backend for non-WAV files
    try:
        import aud
        length = aud.Sound(filepath).length
        if length > 0:
            return length
    except Exception:
        pass
    # Fallback for non-WAV or on error: assume 1 second
    return 1.0


def connect_to_davinci_resolve():
    """Connect to a running DaVinci Resolve instance.

    Returns:
        tuple: (resolve, project, timeline, media_pool)

    Raises:
        RuntimeError: If connection fails at any step
    """
    import sys as _sys

    if RESOLVE_MODULES not in _sys.path:
        _sys.path.append(RESOLVE_MODULES)
    os.environ["RESOLVE_SCRIPT_API"] = RESOLVE_MODULES
    os.environ["RESOLVE_SCRIPT_LIB"] = RESOLVE_LIB

    try:
        import DaVinciResolveScript as dvr_script
    except ImportError:
        raise RuntimeError(
            "Could not import DaVinci Resolve scripting module. "
            "Make sure DaVinci Resolve is installed."
        )

    resolve = dvr_script.scriptapp("Resolve")
    if resolve is None:
        raise RuntimeError("Could not connect to DaVinci Resolve. Is it running?")

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject()
    if project is None:
        raise RuntimeError("No project open in DaVinci Resolve")

    media_pool = project.GetMediaPool()

    timeline = project.GetCurrentTimeline()
    if timeline is None:
        timeline = media_pool.CreateEmptyTimeline("BlenderMotionSounds")

    return resolve, project, timeline, media_pool


def find_next_available_audio_track(timeline):
    """Find the next audio track above all existing audio clips in Resolve.

    Mirrors find_next_available_channel() behaviour for the Blender VSE.
    """
    audio_track_count = timeline.GetTrackCount("audio")
    if audio_track_count == 0:
        return 1

    max_used_track = 0
    for track_idx in range(1, audio_track_count + 1):
        items = timeline.GetItemListInTrack("audio", track_idx)
        if items:
            max_used_track = track_idx

    return max_used_track + 1


def _iter_resolve_collection(items):
    """Iterate Resolve API collections that may be list/tuple/dict."""
    if not items:
        return []
    if isinstance(items, dict):
        return items.values()
    return items


def get_resolve_clip_file_path(clip):
    """Get normalized source file path for a Resolve media clip, if available."""
    clip_path = ""
    try:
        clip_path = clip.GetClipProperty("File Path")
    except Exception:
        clip_path = ""

    if isinstance(clip_path, dict):
        clip_path = clip_path.get("File Path", "")

    if not clip_path:
        try:
            props = clip.GetClipProperty()
            if isinstance(props, dict):
                clip_path = props.get("File Path", "")
        except Exception:
            clip_path = ""

    return os.path.realpath(clip_path) if clip_path else ""


def build_resolve_media_pool_lookup(root_folder):
    """Build media pool lookups keyed by path/name/stem across all folders."""
    clip_by_path = {}
    clip_by_name = {}
    clip_by_stem = {}

    def _scan(folder):
        for clip in _iter_resolve_collection(folder.GetClipList()):
            try:
                clip_name = clip.GetName()
            except Exception:
                continue

            if clip_name:
                clip_by_name.setdefault(clip_name, clip)
                clip_by_stem.setdefault(os.path.splitext(clip_name)[0], clip)

            clip_path = get_resolve_clip_file_path(clip)
            if clip_path:
                clip_by_path.setdefault(clip_path, clip)

        for sub in _iter_resolve_collection(folder.GetSubFolderList()):
            _scan(sub)

    _scan(root_folder)
    return clip_by_path, clip_by_name, clip_by_stem


def find_resolve_media_clip(sound_path, clip_by_path, clip_by_name, clip_by_stem):
    """Resolve a source sound path to a Resolve MediaPoolItem."""
    norm_path = os.path.realpath(sound_path)
    media_clip = clip_by_path.get(norm_path)
    if media_clip is not None:
        return media_clip

    sound_filename = os.path.basename(norm_path)
    media_clip = clip_by_name.get(sound_filename)
    if media_clip is not None:
        return media_clip

    sound_stem = os.path.splitext(sound_filename)[0]
    media_clip = clip_by_stem.get(sound_stem)
    if media_clip is not None:
        return media_clip

    for cname, cobj in clip_by_name.items():
        if sound_filename in cname or cname in sound_filename:
            return cobj

    return None


class VSE_OT_ImportOneSoundToDaVinciResolve(Operator):
    """Import one selected sound and place it directly on Resolve timeline."""
    bl_idname = "vse_event.import_one_sound_to_davinci_resolve"
    bl_label = "Import One Sound"
    bl_options = {'REGISTER'}

    def execute(self, context):
        settings = context.scene.vse_event_sound_settings

        # Resolve selected sound file from Blender UI
        sound_folder = bpy.path.abspath(settings.sound_folder)
        if not sound_folder or not os.path.isdir(sound_folder):
            self.report({'ERROR'}, "Select a valid sound folder first")
            return {'CANCELLED'}

        sound_filename = settings.sound_file
        if not sound_filename or sound_filename == 'NONE':
            self.report({'ERROR'}, "Select one sound file first")
            return {'CANCELLED'}

        sound_path = os.path.realpath(os.path.join(sound_folder, sound_filename))
        if not os.path.isfile(sound_path):
            self.report({'ERROR'}, f"Selected sound file not found: {sound_path}")
            return {'CANCELLED'}

        # Connect to Resolve
        try:
            resolve, project, timeline, media_pool = connect_to_davinci_resolve()
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # Import one sound by full path
        root_folder = media_pool.GetRootFolder()
        media_pool.SetCurrentFolder(root_folder)
        imported_clips = media_pool.ImportMedia([sound_path])

        clip_by_path, clip_by_name, clip_by_stem = build_resolve_media_pool_lookup(root_folder)
        imported_clip = find_resolve_media_clip(sound_path, clip_by_path, clip_by_name, clip_by_stem)

        if imported_clip is None:
            self.report({'ERROR'}, f"Failed to import selected sound: {sound_path}")
            return {'CANCELLED'}

        imported_name = imported_clip.GetName()
        import_count = len(imported_clips) if imported_clips else 0

        # Place directly on timeline (same simple placement style as the script)
        resolve_fps = float(timeline.GetSetting("timelineFrameRate") or 24.0)
        start_frame = timeline.GetStartFrame()
        record_frame = start_frame + int(resolve_fps)  # +1 second
        track_index = 1

        # Ensure at least one audio track exists
        current_track_count = timeline.GetTrackCount("audio")
        for _ in range(max(0, track_index - current_track_count)):
            timeline.AddTrack("audio")

        clip_info = {
            "mediaPoolItem": imported_clip,
            "recordFrame": record_frame,
            "trackIndex": track_index,
            "mediaType": 2,  # Audio
        }
        placed = media_pool.AppendToTimeline([clip_info])
        if not placed:
            self.report(
                {'WARNING'},
                f"Imported '{imported_name}' but failed to place it on timeline (frame {record_frame}, track {track_index})"
            )
            return {'FINISHED'}

        self.report(
            {'INFO'},
            f"Imported '{imported_name}' and placed on timeline at frame {record_frame}, track {track_index} (new imports: {import_count})"
        )
        return {'FINISHED'}


class ResolvePlacementStrip:
    """Lightweight strip-like object for Resolve track assignment.

    We feed these through separate_overlapping_strips() so Resolve and VSE
    use the exact same overlap/channel separation logic.
    """
    def __init__(self, frame_start, frame_end):
        self.frame_final_start = frame_start
        self.frame_final_end = frame_end
        self.channel = 0


def compute_resolve_track_assignments_with_vse_logic(clip_data, base_track=1):
    """Assign Resolve tracks using the same logic as VSE channel separation.

    Args:
        clip_data: list of (frame, duration_frames) tuples
        base_track: starting track index (1-based)

    Returns:
        list of track indices corresponding to clip_data order
    """
    mock_strips = [
        ResolvePlacementStrip(frame, frame + duration_frames)
        for frame, duration_frames in clip_data
    ]
    separate_overlapping_strips(mock_strips, base_track)
    return [strip.channel for strip in mock_strips]


class VSE_OT_AddSoundsAtZCrossings(Operator):
    """Scan timeline for bones crossing Z threshold and add sounds at those frames"""
    bl_idname = "vse_event.add_sounds_at_z_crossings"
    bl_label = "Add Sounds at Z Crossings"
    bl_options = {'REGISTER', 'UNDO'}
    
    def get_bones_in_collection(self, armature_obj, bone_collection_name):
        """Get list of bone names that belong to the specified bone collection."""
        return get_bones_for_collection(armature_obj, bone_collection_name)
    
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
        crossing_data = detect_z_crossings(
            scene, armature_obj, pose_bones,
            settings.z_crossing_threshold, direction,
            frame_start, frame_end
        )
        
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
                    name=f"{bone_name}_volume{volume_percent}",
                    filepath=current_sound_path,
                    channel=base_channel,
                    frame_start=frame
                )
                
                # Apply color based on the bone name (each bone gets a unique color)
                apply_strip_color_by_bone(strip, bone_name, bone_color_map)
                
                # Track which bone this strip belongs to
                strip_bone_map[strip] = bone_name
                
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
            # Reapply bone-based colors after channel separation (strips may have moved)
            for strip in new_strips:
                if strip in strip_bone_map:
                    apply_strip_color_by_bone(strip, strip_bone_map[strip], bone_color_map)
        
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


class VSE_OT_SendSoundsToDaVinciResolve(Operator):
    """Send Z-crossing sounds directly to a DaVinci Resolve timeline"""
    bl_idname = "vse_event.send_sounds_to_davinci_resolve"
    bl_label = "Send to DaVinci Resolve"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        settings = context.scene.vse_event_sound_settings
        armature_name = settings.z_crossing_armature
        direction = settings.z_crossing_direction

        # ── Validate armature ───────────────────────────────────────────
        if armature_name == 'NONE' or armature_name not in bpy.data.objects:
            self.report({'ERROR'}, "Please select a valid armature")
            return {'CANCELLED'}

        armature_obj = bpy.data.objects[armature_name]
        if armature_obj.type != 'ARMATURE':
            self.report({'ERROR'}, f"'{armature_name}' is not an armature")
            return {'CANCELLED'}

        # ── Validate sound files ────────────────────────────────────────
        sound_folder = bpy.path.abspath(settings.sound_folder)
        selection_mode = settings.sound_selection_mode
        if not sound_folder or not os.path.isdir(sound_folder):
            self.report({'ERROR'}, "Select a valid sound folder first")
            return {'CANCELLED'}

        available_sound_files = get_sound_files_from_folder(sound_folder)
        if not available_sound_files:
            self.report({'ERROR'}, f"No sound files found in folder: {sound_folder}")
            return {'CANCELLED'}

        sound_path = None
        if selection_mode == 'SINGLE':
            sound_filename = settings.sound_file
            if not sound_filename or sound_filename == 'NONE':
                self.report({'ERROR'}, "Select one sound file first")
                return {'CANCELLED'}
            sound_path = os.path.realpath(os.path.join(sound_folder, sound_filename))
            if not os.path.isfile(sound_path):
                self.report({'ERROR'}, f"Selected sound file not found: {sound_path}")
                return {'CANCELLED'}

        # ── Get bones to monitor ────────────────────────────────────────
        scene = context.scene
        frame_start = scene.frame_start
        frame_end = scene.frame_end
        original_frame = scene.frame_current

        bone_collection_name = settings.z_crossing_bone_collection
        bone_names = get_bones_for_collection(armature_obj, bone_collection_name)

        if not bone_names:
            if bone_collection_name == 'SELECTED':
                self.report({'ERROR'}, "No bones selected. Select bones in Pose Mode first.")
            else:
                self.report({'ERROR'}, f"No bones found in bone collection '{bone_collection_name}'")
            return {'CANCELLED'}

        pose_bones = [armature_obj.pose.bones[name] for name in bone_names
                      if name in armature_obj.pose.bones]
        if not pose_bones:
            self.report({'ERROR'}, "No valid pose bones found")
            return {'CANCELLED'}

        # ── Detect Z-crossings ──────────────────────────────────────────
        crossing_data = detect_z_crossings(
            scene, armature_obj, pose_bones,
            settings.z_crossing_threshold, direction,
            frame_start, frame_end
        )
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

        # ── Normalize speeds ────────────────────────────────────────────
        crossing_frames = sorted(crossing_data.keys())
        speeds = [crossing_data[f][0] for f in crossing_frames]
        max_speed = max(speeds) if speeds else 1.0
        min_speed = min(speeds) if speeds else 0.0
        speed_range = max_speed - min_speed if max_speed > min_speed else 1.0

        # ── Connect to DaVinci Resolve ──────────────────────────────────
        try:
            resolve, project, timeline, media_pool = connect_to_davinci_resolve()
        except RuntimeError as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        self.report({'INFO'}, f"Connected to DaVinci Resolve project: {project.GetName()}")

        # ── Frame-rate conversion setup ─────────────────────────────────
        try:
            resolve_fps = float(timeline.GetSetting("timelineFrameRate") or 24.0)
        except (TypeError, ValueError):
            resolve_fps = 24.0
        resolve_start = timeline.GetStartFrame()
        blender_fps = scene.render.fps / scene.render.fps_base

        # ── Collect unique sound file paths (absolute) ─────────────────
        if selection_mode == 'SINGLE':
            all_sound_paths = [sound_path]
        else:
            all_sound_paths = [
                os.path.realpath(os.path.join(sound_folder, f))
                for f in available_sound_files
            ]

        # Deduplicate while preserving order
        all_sound_paths = [
            p for p in dict.fromkeys(all_sound_paths)
            if p and os.path.isfile(p)
        ]
        if not all_sound_paths:
            self.report({'ERROR'}, "No sound files resolved for DaVinci Resolve import")
            return {'CANCELLED'}

        # ── Import sound files into Resolve media pool ──────────────────
        # Set root folder as the active folder for imports
        root_folder = media_pool.GetRootFolder()
        media_pool.SetCurrentFolder(root_folder)

        imported_clips = media_pool.ImportMedia(all_sound_paths)

        # Build lookup from imported clips first
        clip_by_path = {}
        clip_by_name = {}
        clip_by_stem = {}
        if imported_clips:
            for clip in _iter_resolve_collection(imported_clips):
                clip_name = clip.GetName()
                if clip_name:
                    clip_by_name.setdefault(clip_name, clip)
                    clip_by_stem.setdefault(os.path.splitext(clip_name)[0], clip)
                clip_path = get_resolve_clip_file_path(clip)
                if clip_path:
                    clip_by_path.setdefault(clip_path, clip)

        # Also scan full media pool (covers already-imported clips and bins)
        pool_by_path, pool_by_name, pool_by_stem = build_resolve_media_pool_lookup(root_folder)
        for key, val in pool_by_path.items():
            clip_by_path.setdefault(key, val)
        for key, val in pool_by_name.items():
            clip_by_name.setdefault(key, val)
        for key, val in pool_by_stem.items():
            clip_by_stem.setdefault(key, val)

        # Pre-resolve requested files to media items
        resolved_sound_clips = {
            sp: find_resolve_media_clip(sp, clip_by_path, clip_by_name, clip_by_stem)
            for sp in all_sound_paths
        }

        usable_sound_paths = [sp for sp, clip in resolved_sound_clips.items() if clip is not None]

        if not usable_sound_paths:
            paths_str = ", ".join(os.path.basename(p) for p in all_sound_paths[:5])
            if len(all_sound_paths) > 5:
                paths_str += ", ..."
            self.report({'ERROR'},
                        f"Failed to import sound files into DaVinci Resolve media pool: {paths_str}")
            return {'CANCELLED'}

        if selection_mode == 'SINGLE' and sound_path not in usable_sound_paths:
            self.report({'ERROR'}, f"Selected sound could not be resolved in Resolve: {sound_path}")
            return {'CANCELLED'}

        # ── Cache audio durations for track assignment ──────────────────
        sound_durations = {}
        for fp in usable_sound_paths:
            sound_durations[fp] = get_audio_duration_seconds(fp)

        # ── Build placement list ────────────────────────────────────────
        volume_slowest = settings.volume_slowest
        volume_fastest = settings.volume_fastest
        volume_randomness = settings.volume_randomness

        placements = []  # (resolve_frame, dur_frames, sound_path, bone_name, volume)

        for frame in crossing_frames:
            crossing_speed, bone_name = crossing_data[frame]

            # Pick sound file
            if selection_mode == 'RANDOM':
                current_sound_path = random.choice(usable_sound_paths)
            else:
                current_sound_path = sound_path

            # Speed-based volume
            if speed_range > 0:
                normalized_speed = (crossing_speed - min_speed) / speed_range
            else:
                normalized_speed = 1.0
            base_volume = volume_slowest + (normalized_speed * (volume_fastest - volume_slowest))
            final_volume = get_random_volume(base_volume, volume_randomness)

            # Convert Blender frame -> Resolve frame
            seconds_from_start = (frame - frame_start) / blender_fps
            resolve_frame = resolve_start + int(seconds_from_start * resolve_fps)

            # Clip duration in Resolve frames
            dur_sec = sound_durations.get(current_sound_path, 1.0)
            dur_frames = max(1, int(dur_sec * resolve_fps))

            placements.append((resolve_frame, dur_frames, current_sound_path, bone_name, final_volume))

        # ── Pre-compute track assignments (exact VSE overlap logic) ─
        base_track = find_next_available_audio_track(timeline)
        clip_frame_data = [(p[0], p[1]) for p in placements]
        track_assignments = compute_resolve_track_assignments_with_vse_logic(
            clip_frame_data, base_track
        )

        # Ensure enough audio tracks exist in Resolve
        max_track_needed = max(track_assignments) if track_assignments else base_track
        current_track_count = timeline.GetTrackCount("audio")
        for _ in range(max(0, max_track_needed - current_track_count)):
            timeline.AddTrack("audio")

        # ── Place clips on Resolve timeline ─────────────────────────────
        placed_count = 0
        for i, (resolve_frame, dur_frames, snd_path, bone_name, volume) in enumerate(placements):
            track_index = track_assignments[i]
            volume_percent = int(round(volume * 100))

            snd_key = os.path.realpath(snd_path)
            media_clip = resolved_sound_clips.get(snd_key)
            if media_clip is None:
                media_clip = find_resolve_media_clip(
                    snd_key, clip_by_path, clip_by_name, clip_by_stem
                )
                if media_clip is not None:
                    resolved_sound_clips[snd_key] = media_clip

            if media_clip is None:
                snd_filename = os.path.basename(snd_key)
                self.report({'WARNING'}, f"Could not find imported clip for {snd_filename}")
                continue

            clip_info = {
                "mediaPoolItem": media_clip,
                "recordFrame": resolve_frame,
                "trackIndex": track_index,
                "mediaType": 2,  # Audio
            }

            result = media_pool.AppendToTimeline([clip_info])
            if result:
                placed_count += 1
            else:
                self.report({'WARNING'},
                            f"Failed to place {bone_name}_vol{volume_percent} "
                            f"at frame {resolve_frame}, track {track_index}")

        self.report({'INFO'},
                     f"Sent {placed_count}/{len(placements)} sounds to DaVinci Resolve "
                     f"(tracks {base_track}-{max_track_needed})")
        return {'FINISHED'}


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
        
        layout.separator()
        
        # Volume settings
        col = layout.column(align=True)
        col.label(text="Volume (Speed-Based):", icon='SPEAKER')
        col.prop(settings, "volume_slowest", text="Slowest", slider=True)
        col.prop(settings, "volume_fastest", text="Fastest", slider=True)
        
        col.separator()
        col.prop(settings, "volume_randomness", text="Volume Randomness", slider=True)


class VSE_PT_ZCrossingPanel(Panel):
    """Sub-panel for Z-crossing sound triggers"""
    bl_label = "Trigger on Z-Crossing"
    bl_idname = "VSE_PT_z_crossing_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Motion Sounds"
    bl_parent_id = "VSE_PT_motion_sounds_panel"

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
        
        # Main button – place sounds in Blender VSE
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator(
            VSE_OT_AddSoundsAtZCrossings.bl_idname,
            text="Add Sounds at Crossings",
            icon='ADD'
        )
        
        # Send sounds to DaVinci Resolve
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator(
            VSE_OT_SendSoundsToDaVinciResolve.bl_idname,
            text="Send to DaVinci Resolve",
            icon='EXPORT'
        )

        # Import one selected sound to DaVinci Resolve media pool
        row = layout.row(align=True)
        row.scale_y = 1.3
        row.operator(
            VSE_OT_ImportOneSoundToDaVinciResolve.bl_idname,
            text="Import One Sound",
            icon='IMPORT'
        )
        
        # Info
        box = layout.box()
        col = box.column(align=True)
        col.scale_y = 0.8
        col.label(text="Faster crossings = louder")


def register():
    bpy.types.Scene.vse_event_sound_settings = PointerProperty(type=VSE_PG_EventSoundSettings)


def unregister():
    del bpy.types.Scene.vse_event_sound_settings
