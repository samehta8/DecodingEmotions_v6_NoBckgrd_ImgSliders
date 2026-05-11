"""
Questionnaire page - Collect demographic and experience information.
Dynamically builds form based on config/questionnaire_fields.yaml.
"""
import streamlit as st
from utils.config_loader import load_questionnaire_fields
from utils.data_persistence import save_user_data, get_all_existing_user_ids
from utils.gsheets_manager import append_user_to_gsheets

def show():
    """Display the questionnaire screen."""
    # Check if consent has been given
    if not st.session_state.get('consent_given', False):
        st.warning("⚠️ You must provide consent before accessing the questionnaire.")
        if st.button("Go to Consent Page"):
            st.session_state.page = 'consent'
            st.rerun()
        return

    user = st.session_state.user
    config = st.session_state.config

    # Load questionnaire fields
    if 'questionnaire_fields' not in st.session_state:
        st.session_state.questionnaire_fields = load_questionnaire_fields(config)

    fields = st.session_state.questionnaire_fields

    # Check if user has confirmed their ID
    if st.session_state.get('user_id_confirmed', False):
        # Show confirmation panel
        show_confirmation_panel()
    else:
        # Show main questionnaire form
        show_questionnaire_form(fields)

def show_questionnaire_form(fields):
    """Display the main questionnaire form."""
    user = st.session_state.user

    st.title("📋 Questionnaire")
    st.markdown("Please provide the following information:")
    st.markdown("---")

    # Create form
    with st.form("questionnaire_form"):
        # Process fields and group related ones
        processed_groups = set()

        for field_config in fields:
            field_type = field_config.get('type', 'text')
            field_name = field_config.get('field_name', '')
            title = field_config.get('title', '')
            hint_text = field_config.get('hint_text', '')
            group = field_config.get('group', None)

            # Skip if already processed as part of a group
            if group and group in processed_groups:
                continue

            if field_type == 'multiple_choice':
                # Multiple choice field
                options = field_config.get('options', [])
                required = field_config.get('required_to_proceed', False)
                if title:
                    st.markdown(f"**{title}** {'*(required)*' if required else ''}")

                selected = st.radio(
                    label=title if not title else "Select one:",
                    options=options,
                    key=f"field_{field_name}",
                    horizontal=True,
                    label_visibility="collapsed" if title else "visible"
                )

                # Store value
                user.set_field_value(field_name, selected)

            elif field_type in ('text', 'numeric'):
                # Handle grouped fields (e.g., birthday)
                if group:
                    # Find all fields in this group
                    group_fields = [f for f in fields if f.get('group') == group]

                    # Get title from first field with a title
                    group_title = next((f.get('title') for f in group_fields if f.get('title')), '')

                    # Check if any field in the group is required
                    group_required = any(f.get('required_to_proceed', False) for f in group_fields)

                    if group_title:
                        st.markdown(f"**{group_title}** {'*(required)*' if group_required else ''}")

                    # Create columns for group fields
                    cols = st.columns(len(group_fields))

                    for idx, gf in enumerate(group_fields):
                        gf_name = gf.get('field_name', '')
                        gf_hint = gf.get('hint_text', '')
                        gf_type = gf.get('type', 'text')
                        max_len = gf.get('max_length', None)

                        with cols[idx]:
                            if gf_type == 'numeric':
                                value = st.number_input(
                                    label=gf_hint,
                                    key=f"field_{gf_name}",
                                    min_value=0,
                                    step=1,
                                    value=None,
                                    label_visibility="collapsed",
                                    placeholder=gf_hint
                                )
                            else:
                                value = st.text_input(
                                    label=gf_hint,
                                    key=f"field_{gf_name}",
                                    max_chars=max_len,
                                    placeholder=gf_hint,
                                    label_visibility="collapsed"
                                )

                            # Store value
                            if value is not None:
                                user.set_field_value(gf_name, value)

                    processed_groups.add(group)

                else:
                    # Single field (not grouped)
                    max_len = field_config.get('max_length', None)
                    required = field_config.get('required_to_proceed', False)

                    # Display title as bold markdown if it exists (same as multiple choice)
                    if title:
                        st.markdown(f"**{title}** {'*(required)*' if required else ''}")

                    if field_type == 'numeric':
                        value = st.number_input(
                            label=title if title else hint_text,
                            key=f"field_{field_name}",
                            min_value=0,
                            step=1,
                            value=None,
                            placeholder=hint_text,
                            label_visibility="collapsed" if title else "visible"
                        )
                    else:
                        value = st.text_input(
                            label=title if title else hint_text,
                            key=f"field_{field_name}",
                            max_chars=max_len,
                            placeholder=hint_text,
                            label_visibility="collapsed" if title else "visible"
                        )

                    # Store value
                    if value is not None:
                        user.set_field_value(field_name, value)

            st.markdown("")  # Add spacing between fields

        # Form submission buttons
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 1])

        with col1:
            back_button = st.form_submit_button("◀️ Back", use_container_width=True)

        with col3:
            next_button = st.form_submit_button("Generate User ID ▶️", use_container_width=True, type="primary")

    # Handle form submission
    if back_button:
        st.session_state.page = 'consent'
        st.rerun()

    if next_button:
        # Validate that required fields are filled
        missing_fields = []

        # Check all fields marked as required_to_proceed
        for field_config in fields:
            if field_config.get('required_to_proceed', False):
                field_name = field_config.get('field_name', '')
                field_value = user.data.get(field_name)
                field_title = field_config.get('title', field_config.get('hint_text', field_name))

                # Check if field is empty, None, or empty string
                # For numeric fields, 0 is a valid value, so we check for None or empty string only
                if field_value is None or field_value == '':
                    missing_fields.append(field_title)

        if missing_fields:
            st.error(f"⚠️ Please fill in the following required fields: {', '.join(missing_fields)}")
        else:
            # Generate random user ID
            try:
                existing_ids = get_all_existing_user_ids()
                user.generate_random_user_id(existing_ids)
                # Show confirmation panel
                st.session_state.user_id_confirmed = True
                st.rerun()
            except Exception as e:
                st.error(f"⚠️ Failed to generate user ID: {e}")
                print(f"[ERROR] User ID generation failed: {e}")

def show_confirmation_panel():
    """Display the user ID confirmation panel."""
    user = st.session_state.user

    st.title("✅ User ID Generated")

    st.markdown("### Your User ID has been generated:")

    # Display user ID prominently
    st.markdown(f"# `{user.user_id}`")

    st.warning("""
    **⚠️ IMPORTANT: Please memorize or write down your User ID!**

    You will need this ID if you want to continue rating videos in a future session.
    This ID is the only way to link your ratings across sessions.
    """)

    st.markdown("---")

    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        if st.button("◀️ Back to Form", use_container_width=True):
            st.session_state.user_id_confirmed = False
            st.rerun()

    with col3:
        if st.button("Understood. Proceed ▶️", use_container_width=True, type="primary"):
            # Save user data and proceed
            if save_user_data(user):
                # Also save to Google Sheets
                try:
                    append_user_to_gsheets(user.to_dict())
                except Exception as e:
                    print(f"[WARNING] GSheets user save failed: {e}")

                # Check if familiarization is enabled
                config = st.session_state.config
                enable_familiarization = config.get('settings', {}).get('enable_familiarization', True)

                if enable_familiarization:
                    st.session_state.page = 'pre_familiarization'
                else:
                    st.session_state.page = 'videoplayer'

                st.rerun()
            else:
                st.error("Failed to save user data. Please try again.")
