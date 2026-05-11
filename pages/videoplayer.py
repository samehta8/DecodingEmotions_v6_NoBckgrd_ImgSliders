"""
Video player page - Main rating interface.
Displays videos with customizable rating scales and optional metadata/pitch visualization.
"""
import streamlit as st
import streamlit.components.v1 as components
import os
import pandas as pd
import random
import base64
from io import BytesIO

from utils.config_loader import load_rating_scales
from utils.data_persistence import save_rating, get_rated_videos_for_user
from utils.video_rating_display import display_video_rating_interface
from utils.gdrive_manager import get_all_video_filenames, get_video_path
from utils.gsheets_manager import append_rating_to_gsheets
from utils.device_detection import get_device_info_cached

def stratified_sample_videos(videos_to_rate, df_metadata, number_of_videos, strat_config):
    """
    Perform hierarchical stratified sampling of videos based on metadata variables.

    Priority-based approach: First variable has highest priority in ensuring balance,
    then within each first-level stratum, second variable is applied, and so on.

    Args:
        videos_to_rate: List of video filenames (e.g., ['event_001.mp4', ...])
        df_metadata: DataFrame with metadata including 'id' column matching video IDs
        number_of_videos: Target number of videos to select (None = all available)
        strat_config: List of stratification configs, each with 'variable', 'levels', 'proportions'

    Returns:
        List of selected video filenames (shuffled)
    """
    # If no stratification config or empty, use simple random sampling
    if not strat_config or len(strat_config) == 0:
        if number_of_videos and number_of_videos < len(videos_to_rate):
            selected = random.sample(videos_to_rate, number_of_videos)
            random.shuffle(selected)
            return selected
        else:
            random.shuffle(videos_to_rate)
            return videos_to_rate

    # Get event IDs from video filenames
    event_ids = [v.replace('.mp4', '') for v in videos_to_rate]

    # Filter metadata to only available videos
    df = df_metadata[df_metadata['id'].isin(event_ids)].copy()

    if df.empty:
        print("[WARNING] No metadata found for available videos")
        return videos_to_rate

    # Determine target count
    target = number_of_videos if number_of_videos else len(df)
    target = min(target, len(df))  # Cap at available

    # Apply hierarchical stratification
    selected_ids = _stratified_sample_recursive(df, strat_config, target, 0)

    # Convert back to video filenames
    selected_videos = [vid_id + '.mp4' for vid_id in selected_ids]

    # Shuffle to randomize presentation order within strata
    random.shuffle(selected_videos)

    return selected_videos


def _stratified_sample_recursive(df, strat_config, target_count, level):
    """
    Recursively apply stratification by each variable in hierarchy.

    Args:
        df: DataFrame of available videos at this level
        strat_config: Full stratification configuration
        target_count: Number of videos to select at this level
        level: Current stratification level (0-indexed)

    Returns:
        List of selected video IDs
    """
    # Base case: no more stratification levels
    if level >= len(strat_config):
        # Sample randomly from remaining videos
        if target_count and target_count < len(df):
            sampled = df.sample(n=target_count, replace=False)
            return sampled['id'].tolist()
        else:
            return df['id'].tolist()

    # Get current stratification variable configuration
    var_config = strat_config[level]
    variable = var_config.get('variable')
    levels_list = var_config.get('levels', [])
    proportions = var_config.get('proportions', [])

    # Validate configuration
    if not variable or not levels_list or not proportions:
        print(f"[WARNING] Invalid stratification config at level {level}: {var_config}")
        return df['id'].tolist()[:target_count] if target_count else df['id'].tolist()

    if len(levels_list) != len(proportions):
        print(f"[WARNING] Levels and proportions length mismatch for '{variable}'")
        return df['id'].tolist()[:target_count] if target_count else df['id'].tolist()

    if abs(sum(proportions) - 1.0) > 0.01:
        print(f"[WARNING] Proportions for '{variable}' don't sum to 1.0: {sum(proportions)}")

    # Check if variable exists in metadata
    if variable not in df.columns:
        print(f"[WARNING] Variable '{variable}' not found in metadata. Skipping stratification.")
        return df['id'].tolist()[:target_count] if target_count else df['id'].tolist()

    # Filter to only specified levels
    df_filtered = df[df[variable].isin(levels_list)]

    if len(df_filtered) == 0:
        print(f"[WARNING] No videos found for '{variable}' with levels {levels_list}")
        # Fallback: return from unfiltered
        return df['id'].tolist()[:target_count] if target_count else df['id'].tolist()

    # Calculate target counts per level and sample
    selected_ids = []

    for i, level_value in enumerate(levels_list):
        level_df = df_filtered[df_filtered[variable] == level_value]

        if len(level_df) == 0:
            print(f"[INFO] No videos for {variable}={level_value}, skipping")
            continue

        # Calculate target count for this level based on proportion
        level_target = int(round(target_count * proportions[i])) if target_count else None

        # If too few videos available, take all
        if level_target and len(level_df) < level_target:
            print(f"[INFO] {variable}={level_value}: requested {level_target}, only {len(level_df)} available. Taking all.")
            level_target = len(level_df)

        # Recursively stratify by next variable within this stratum
        level_selected = _stratified_sample_recursive(level_df, strat_config, level_target, level + 1)
        selected_ids.extend(level_selected)

    return selected_ids

def display_video_with_mode(video_file_path, playback_mode='loop', video_width=None, enable_auto_advance=False):
    """
    Display video with specified playback mode.

    Parameters:
    - video_file_path: Path to the local video file
    - playback_mode: 'loop' or 'once'
        - 'loop': Autoplay, loop enabled, controls visible
        - 'once': Autoplay, no loop, no controls (plays once only)
    - video_width: Width of video in pixels (for centered display) or percentage string
    - enable_auto_advance: If True, trigger Streamlit rerun when video ends
    """
    if not os.path.exists(video_file_path):
        st.error(f"Video file not found: {video_file_path}")
        return

    if playback_mode == 'loop':
        # Loop mode: autoplay with controls and looping
        if video_width:
            # Centered with specified width
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.video(video_file_path, autoplay=True, loop=True)
        else:
            st.video(video_file_path, autoplay=True, loop=True)

    elif playback_mode == 'once':
        # Once mode: autoplay without controls, no loop, plays once only
        # Read video file and encode as base64
        with open(video_file_path, 'rb') as f:
            video_bytes = f.read()
        video_base64 = base64.b64encode(video_bytes).decode()

        # Determine width style
        if video_width:
            if isinstance(video_width, str) and '%' in video_width:
                width_style = f"width: {video_width};"
            else:
                width_style = f"width: {video_width}px;"
        else:
            width_style = "max-width: 100%;"

        # JavaScript to detect video end and trigger Streamlit rerun
        auto_advance_script = ""
        if enable_auto_advance:
            auto_advance_script = """
            video.addEventListener('ended', function() {
                console.log('Video ended, triggering rerun...');
                // Set a flag in sessionStorage to indicate video ended
                window.parent.sessionStorage.setItem('video_ended', 'true');
                // Trigger Streamlit to rerun by sending a custom event
                window.parent.postMessage({type: 'streamlit:setComponentValue', value: 'ended'}, '*');
            });
            """

        # Create HTML5 video player without controls
        # Use object-fit: contain to ensure video is never cropped
        video_html = f"""
        <div style="width: 100%; height: 100vh; display: flex; align-items: center; justify-content: center; background: transparent;">
            <video
                id="main-video"
                autoplay
                muted
                style="{width_style} max-height: 85vh; height: auto; object-fit: contain;"
                onended="this.pause();"
            >
                <source src="data:video/mp4;base64,{video_base64}" type="video/mp4">
                Your browser does not support the video tag.
            </video>
        </div>
        <style>
            video::-webkit-media-controls {{
                display: none !important;
            }}
            video::-webkit-media-controls-enclosure {{
                display: none !important;
            }}
        </style>
        <script>
            const video = document.getElementById('main-video');
            {auto_advance_script}
        </script>
        """
        components.html(video_html, height=700)

    else:
        # Fallback to default
        st.video(video_file_path)

def show():
    """Display the video player screen."""
    user = st.session_state.user
    config = st.session_state.config

    if not config:
        st.error("Configuration not loaded. Please restart the application.")
        return

    # Initialize video player state
    if 'video_initialized' not in st.session_state:
        initialize_video_player(config)

    # Check if there are videos to rate
    if not st.session_state.get('videos_to_rate'):
        st.session_state.page = 'completion'
        st.rerun()
        return

    # Load current video
    current_video_index = st.session_state.get('current_video_index', 0)
    videos = st.session_state.videos_to_rate

    if current_video_index >= len(videos):
        st.session_state.page = 'completion'
        st.rerun()
        return

    current_video = videos[current_video_index]
    action_id = os.path.splitext(current_video)[0]

    # Get display mode from config
    display_mode = config['settings'].get('display_mode', 'combined')

    if display_mode == 'separate':
        # Two-screen flow: video screen -> rating screen
        # Initialize screen state for current video if not exists
        if 'current_screen' not in st.session_state:
            st.session_state.current_screen = 'video'

        # Check if video ended (from JavaScript event)
        if st.session_state.current_screen == 'video':
            # Auto-advance to rating screen after a short delay
            # Using a button for manual advance as fallback
            display_video_screen(action_id, current_video, config)
        else:
            # Display rating screen
            display_rating_screen(action_id, current_video, config)
    else:
        # Combined mode: video and ratings side-by-side (original behavior)
        display_rating_interface(action_id, current_video, config)

def display_video_screen(action_id, video_filename, config):
    """Display only the video (centered, no ratings)."""
    video_path = st.session_state.video_path
    metadata = st.session_state.metadata
    rating_scales = st.session_state.rating_scales

    # Add custom CSS to eliminate vertical spacing
    st.markdown("""
        <style>
        .stApp > div:first-child {
            padding-top: 0rem;
        }
        div[data-testid="stVerticalBlock"] > div {
            gap: 0rem;
        }
        .element-container {
            margin: 0rem;
            padding: 0rem;
        }
        .stMarkdown {
            margin: 0rem;
            padding: 0rem;
        }
        [data-testid="stHorizontalBlock"] {
            gap: 0rem;
        }
        </style>
    """, unsafe_allow_html=True)

    # Display video info
    #current_index = st.session_state.get('current_video_index', 0) + 1
    #total_videos = len(st.session_state.videos_to_rate)
    #st.info(f"🎬 **Video {current_index} of {total_videos}**. Watch the video carefully.")

    # Use shared display function in video-only mode
    display_video_rating_interface(
        video_filename=video_filename,
        video_path=video_path,
        config=config,
        rating_scales=rating_scales,
        key_prefix="scale_",
        action_id=action_id,
        metadata=metadata,
        header_content=None,
        display_video_func=display_video_with_mode,
        display_mode='video_only'
    )

    # Manual advance button
    col1, col2, col3 = st.columns([1, 1, 1])

    with col2:
        if st.button("Continue to Rating ▶️", use_container_width=True, type="primary", key="advance_to_rating"):
            st.session_state.current_screen = 'rating'
            st.rerun()


def display_rating_screen(action_id, video_filename, config):
    """Display only the rating scales (no video)."""
    user = st.session_state.user
    rating_scales = st.session_state.rating_scales
    video_path = st.session_state.video_path

    # Display rating info
    current_index = st.session_state.get('current_video_index', 0) + 1
    total_videos = len(st.session_state.videos_to_rate)
    #    st.info(f"📊 **Rating {current_index} of {total_videos}**. Please rate the video you just watched.")

    # Use shared display function in rating-only mode
    scale_values = display_video_rating_interface(
        video_filename=video_filename,
        video_path=video_path,
        config=config,
        rating_scales=rating_scales,
        key_prefix="scale_",
        action_id=action_id,
        metadata=None,
        header_content=None,
        display_video_func=display_video_with_mode,
        display_mode='rating_only'
    )

    # Navigation buttons
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        if st.button("◀️ Back to Video", use_container_width=True):
            st.session_state.current_screen = 'video'
            st.rerun()

    with col3:
        if st.button("Submit Rating ▶️", use_container_width=True, type="primary"):
            # Validate ratings
            validation_errors = _validate_ratings(scale_values)

            if validation_errors:
                st.error("⚠️ Please complete the required ratings:")
                for error in validation_errors:
                    st.warning(error)
                st.stop()

            # Save rating
            if save_rating(user.user_id, action_id, scale_values):
                st.success("✅ Rating saved successfully!")

                # Also save to Google Sheets
                try:
                    rating_data = {'user_id': user.user_id, 'action_id': action_id, **scale_values}
                    append_rating_to_gsheets(rating_data)
                except Exception as e:
                    print(f"[WARNING] GSheets save failed: {e}")

                # Track win/loss prediction for this session (for completion screen)
                win_loss_prediction = scale_values.get('Win or Loss')
                if win_loss_prediction is not None:
                    if 'session_ratings' not in st.session_state:
                        st.session_state.session_ratings = {}
                    st.session_state.session_ratings[action_id] = win_loss_prediction

                # Move to next video
                st.session_state.current_video_index += 1
                st.session_state.current_screen = 'video'  # Reset to video screen for next video
                st.session_state.confirm_back = False

                # Small delay to show success message
                import time
                time.sleep(0.5)

                # Clear and move to next video
                st.rerun()
            else:
                st.error("❌ Failed to save rating. Please try again.")


def initialize_video_player(config):
    """Initialize video player state - load videos, metadata, and rating scales."""
    user = st.session_state.user

    # Initialize session ratings tracker (for completion screen)
    # Stores {video_id: win_or_loss_prediction} for current session only
    if 'session_ratings' not in st.session_state:
        st.session_state.session_ratings = {}

    # Detect and cache device information (once per session)
    # This will be attached to each rating submitted
    device_info = get_device_info_cached()

    # Load rating scales (now returns dict with scales, groups, and requirements)
    rating_data = load_rating_scales(config)
    st.session_state.rating_scales = rating_data['scales']
    st.session_state.rating_groups = rating_data['groups']
    st.session_state.group_requirements = rating_data['group_requirements']

    # Track which scales are required individually (not in a group)
    st.session_state.required_scales = [
        scale.get('title') for scale in st.session_state.rating_scales
        if scale.get('required_to_proceed', True) and not scale.get('group')
    ]

    # Get configuration
    metadata_path = config['paths']['metadata_path']
    video_path = config['paths']['video_path']
    min_ratings_per_video = config['settings']['min_ratings_per_video']

    # Get all video files from local filesystem
    try:
        all_videos = [f for f in os.listdir(video_path) if f.lower().endswith('.mp4')]
        st.session_state.video_path = video_path
        print(f"[INFO] Loaded {len(all_videos)} videos from {video_path}")
    except FileNotFoundError:
        st.error(f"Video directory not found: {video_path}")
        all_videos = []

    # Filter out videos already rated by this user
    videos_rated_by_user = get_rated_videos_for_user(user.user_id)
    unrated_videos = [v for v in all_videos if v.replace('.mp4', '') not in videos_rated_by_user]

    # Count total ratings per video and filter out fully-rated videos
    try:
        rated_files = os.listdir('user_ratings')
        rated_ids = [f.split('_')[1].replace('.json', '') for f in rated_files if f.endswith('.json')]
        rating_counts = pd.Series(rated_ids).value_counts()
        videos_fully_rated = rating_counts[rating_counts >= min_ratings_per_video].index.tolist()
        videos_to_rate = [v for v in unrated_videos if v.replace('.mp4', '') not in videos_fully_rated]
    except Exception as e:
        print(f"[WARNING] Error filtering fully-rated videos: {e}")
        videos_to_rate = unrated_videos

    # Load FULL metadata (keep all rows for completion screen)
    df_metadata_full = pd.DataFrame()
    df_metadata_filtered = pd.DataFrame()
    try:
        # Detect file type and load metadata accordingly
        if metadata_path.endswith('.duckdb'):
            # Load from DuckDB (lazy import to avoid binary conflicts on Streamlit Cloud)
            import duckdb
            conn = duckdb.connect(metadata_path, read_only=True)
            df_metadata_full = conn.execute("SELECT * FROM events").fetchdf()
            conn.close()
        elif metadata_path.endswith('.csv'):
            # Load FULL CSV (don't filter yet - needed for completion screen)
            df_metadata_full = pd.read_csv(metadata_path)
        else:
            print(f"[WARNING] Unsupported metadata file type: {metadata_path}")
            df_metadata_full = pd.DataFrame()

        # Create filtered version for stratification (only videos available to rate)
        if videos_to_rate and not df_metadata_full.empty:
            event_ids = [v.replace('.mp4', '') for v in videos_to_rate]
            df_metadata_filtered = df_metadata_full[df_metadata_full['id'].isin(event_ids)]
        else:
            df_metadata_filtered = df_metadata_full.copy()

    except Exception as e:
        print(f"[WARNING] Failed to load metadata: {e}")
        df_metadata_full = pd.DataFrame()
        df_metadata_filtered = pd.DataFrame()

    # Apply stratified sampling or simple random sampling
    # Use FILTERED metadata for stratification (only available videos)
    number_of_videos = config['settings'].get('number_of_videos', None)
    strat_config = config['settings'].get('variables_for_stratification', [])

    if strat_config and len(strat_config) > 0:
        # Use stratified sampling
        print(f"[INFO] Applying stratified sampling with {len(strat_config)} variable(s)")
        videos_to_rate = stratified_sample_videos(
            videos_to_rate,
            df_metadata_filtered,
            number_of_videos,
            strat_config
        )
    else:
        # Use simple random sampling
        if number_of_videos and number_of_videos < len(videos_to_rate):
            videos_to_rate = random.sample(videos_to_rate, number_of_videos)
        random.shuffle(videos_to_rate)

    # Store in session state
    st.session_state.videos_to_rate = videos_to_rate
    st.session_state.current_video_index = 0
    # Note: video_path or gdrive_folder_id already set above based on video_source

    # Store FULL metadata (all rows from CSV) - needed for completion screen
    st.session_state.metadata = df_metadata_full
    st.session_state.video_initialized = True

def display_rating_interface(action_id, video_filename, config):
    """Display the main rating interface with video and scales."""
    user = st.session_state.user
    metadata = st.session_state.metadata
    rating_scales = st.session_state.rating_scales

    # Get video path from local filesystem
    video_path = st.session_state.video_path

    # Use shared display function
    scale_values = display_video_rating_interface(
        video_filename=video_filename,
        video_path=video_path,
        config=config,
        rating_scales=rating_scales,
        key_prefix="scale_",
        action_id=action_id,
        metadata=metadata,
        header_content=None,  # No header for main videoplayer
        display_video_func=display_video_with_mode
    )

    # Navigation and submission buttons
    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        if st.button("◀️ Back to Questionnaire", use_container_width=True):
            if st.session_state.get('confirm_back', False):
                st.session_state.page = 'questionnaire'
                st.session_state.user_id_confirmed = False
                st.session_state.video_initialized = False
                st.rerun()
            else:
                st.session_state.confirm_back = True
                st.warning("⚠️ Click again to confirm. Unsaved ratings will be lost.")

    with col3:
        if st.button("Submit Rating ▶️", use_container_width=True, type="primary"):
            # Validate ratings
            validation_errors = _validate_ratings(scale_values)

            if validation_errors:
                st.error("⚠️ Please complete the required ratings:")
                for error in validation_errors:
                    st.warning(error)
                st.stop()

            # Save rating
            if save_rating(user.user_id, action_id, scale_values):
                st.success("✅ Rating saved successfully!")

                # Also save to Google Sheets
                try:
                    rating_data = {'user_id': user.user_id, 'action_id': action_id, **scale_values}
                    append_rating_to_gsheets(rating_data)
                except Exception as e:
                    print(f"[WARNING] GSheets save failed: {e}")

                # Track win/loss prediction for this session (for completion screen)
                win_loss_prediction = scale_values.get('Win or Loss')
                if win_loss_prediction is not None:
                    if 'session_ratings' not in st.session_state:
                        st.session_state.session_ratings = {}
                    st.session_state.session_ratings[action_id] = win_loss_prediction

                # Move to next video
                st.session_state.current_video_index += 1
                st.session_state.confirm_back = False

                # Clear scale values for next video
                st.rerun()
            else:
                st.error("❌ Failed to save rating. Please try again.")

def _validate_ratings(scale_values):
    """
    Validate that all required ratings are provided.
    Checks both individual required scales and group requirements.

    Returns:
        List of error messages (empty if validation passes)
    """
    errors = []

    # Check individually required scales (not in groups)
    required_scales = st.session_state.get('required_scales', [])
    missing_scales = [
        title for title in required_scales
        if scale_values.get(title) is None or scale_values.get(title) == ''
    ]

    if missing_scales:
        errors.append(f"Required fields: {', '.join(missing_scales)}")

    # Check group requirements
    group_requirements = st.session_state.get('group_requirements', {})
    rating_scales = st.session_state.get('rating_scales', [])

    for group_id, group_info in group_requirements.items():
        required_count = group_info['number_of_ratings']
        error_msg = group_info.get('error_msg', '')
        group_title = group_info.get('title', group_id)

        # Find all scales in this group
        group_scales = [
            scale for scale in rating_scales
            if scale.get('group') == group_id
        ]

        # Count how many scales in this group have been changed
        changed_count = 0
        for scale in group_scales:
            title = scale.get('title')
            value = scale_values.get(title)

            # Check if value exists and is not empty
            if value is None or value == '':
                continue

            # For sliders, check if value has been changed from initial position
            if scale.get('type') == 'slider':
                initial_state = scale.get('initial_state', 'low')
                slider_min = scale.get('slider_min', 0)
                slider_max = scale.get('slider_max', 100)

                # Calculate initial value based on initial_state
                if initial_state == 'low':
                    initial_value = slider_min
                elif initial_state == 'high':
                    initial_value = slider_max
                else:  # center
                    initial_value = (slider_min + slider_max) / 2

                # Count as changed if value is different from initial
                if value != initial_value:
                    changed_count += 1
            else:
                # For discrete and text types, any non-empty value counts as changed
                changed_count += 1

        if changed_count < required_count:
            # Use custom error message if provided, otherwise use default
            if error_msg:
                errors.append(error_msg)
            else:
                errors.append(
                    f"Group '{group_title}': Please rate at least {required_count} emotions "
                    f"(currently {changed_count}/{required_count})"
                )

    return errors
