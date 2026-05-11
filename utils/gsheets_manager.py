"""
Google Sheets manager for data persistence.
Handles connections and write operations to Google Sheets.
"""
import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# Global connection cache
_gsheets_connection = None
_gspread_client = None

def get_gsheets_connection():
    """
    Get or create a cached Google Sheets connection.

    Returns:
        GSheetsConnection object or None if connection fails
    """
    global _gsheets_connection

    if _gsheets_connection is None:
        try:
            _gsheets_connection = st.connection("gsheets", type=GSheetsConnection)
            print("[INFO] Google Sheets connection established")
        except Exception as e:
            print(f"[ERROR] Failed to create Google Sheets connection: {e}")
            return None

    return _gsheets_connection


def get_gspread_client():
    """
    Get or create a cached gspread client directly from secrets.
    This is used for advanced operations like append_row.

    Returns:
        gspread.Client object or None if connection fails
    """
    global _gspread_client

    if _gspread_client is None:
        try:
            # Get credentials from secrets
            credentials_dict = dict(st.secrets["connections"]["gsheets"])

            # Remove non-credential fields
            credentials_dict.pop("spreadsheet", None)

            # Define the required scopes
            scopes = [
                "https://www.googleapis.com/auth/spreadsheets",
                "https://www.googleapis.com/auth/drive"
            ]

            # Create credentials
            credentials = Credentials.from_service_account_info(
                credentials_dict,
                scopes=scopes
            )

            # Create gspread client
            _gspread_client = gspread.authorize(credentials)
            print("[INFO] gspread client created successfully")

        except Exception as e:
            print(f"[ERROR] Failed to create gspread client: {e}")
            import traceback
            traceback.print_exc()
            return None

    return _gspread_client


def append_rating_to_gsheets(rating_data, worksheet="ratings_4c_images"):
    """
    Append a single rating row to Google Sheets using true append (no overwrite).

    Parameters:
        rating_data: Dictionary with rating information
        worksheet: Name of worksheet to write to (default: "ratings")

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get the gspread client for advanced operations
        gspread_client = get_gspread_client()
        if gspread_client is None:
            print("[WARNING] No gspread client available")
            return False

        # Add timestamp
        rating_data_with_timestamp = rating_data.copy()
        rating_data_with_timestamp['timestamp'] = datetime.now().isoformat()

        # Get spreadsheet URL from secrets
        spreadsheet_url = st.secrets["connections"]["gsheets"]["spreadsheet"]

        # Open the spreadsheet
        spreadsheet = gspread_client.open_by_url(spreadsheet_url)

        # Try to get the worksheet, create if it doesn't exist
        try:
            ws = spreadsheet.worksheet(worksheet)
        except Exception:
            # Worksheet doesn't exist, create it
            ws = spreadsheet.add_worksheet(title=worksheet, rows=1000, cols=26)
            print(f"[INFO] Created new worksheet: {worksheet}")

        # Check if this is the first row (header needed)
        existing_data = ws.get_all_values()

        if len(existing_data) == 0 or (len(existing_data) == 1 and not existing_data[0]):
            # Sheet is empty, write header first
            headers = list(rating_data_with_timestamp.keys())
            values = list(rating_data_with_timestamp.values())

            ws.append_row(headers, value_input_option='RAW')
            ws.append_row(values, value_input_option='USER_ENTERED')
            print(f"[INFO] Created headers and appended first rating to worksheet: {worksheet}")
        else:
            # Sheet has data, check if we need to add new columns
            existing_headers = existing_data[0]
            new_keys = set(rating_data_with_timestamp.keys())
            existing_keys = set(existing_headers)

            # If there are new columns, we need to update headers
            if new_keys != existing_keys:
                all_keys = existing_keys | new_keys
                # Create ordered list of all columns
                all_columns = existing_headers + [k for k in new_keys if k not in existing_keys]

                # Update header row
                ws.update('1:1', [all_columns], value_input_option='RAW')

                # Prepare row with values in correct column order
                row_values = [rating_data_with_timestamp.get(col, '') for col in all_columns]
            else:
                # Use existing column order
                row_values = [rating_data_with_timestamp.get(col, '') for col in existing_headers]

            # Append the new row
            ws.append_row(row_values, value_input_option='USER_ENTERED')
            print(f"[INFO] Rating appended to Google Sheets (worksheet: {worksheet})")

        return True

    except Exception as e:
        print(f"[ERROR] Failed to append rating to Google Sheets: {e}")
        import traceback
        traceback.print_exc()
        return False


def read_ratings_from_gsheets(worksheet="ratings_4c_images"):
    """
    Read all ratings from Google Sheets.

    Parameters:
        worksheet: Name of worksheet to read from (default: "ratings")

    Returns:
        DataFrame with all ratings, or empty DataFrame if failed
    """
    try:
        conn = get_gsheets_connection()
        if conn is None:
            return pd.DataFrame()

        df = conn.read(worksheet=worksheet)
        print(f"[INFO] Read {len(df)} ratings from Google Sheets")
        return df

    except Exception as e:
        print(f"[ERROR] Failed to read ratings from Google Sheets: {e}")
        return pd.DataFrame()


def get_rated_videos_for_user_from_gsheets(user_id, worksheet="ratings_4c_images"):
    """
    Get list of video IDs already rated by a specific user from Google Sheets (case-insensitive).

    Parameters:
        user_id: User identifier
        worksheet: Name of worksheet to read from (default: "ratings")

    Returns:
        List of action IDs
    """
    try:
        df = read_ratings_from_gsheets(worksheet=worksheet)

        if df.empty or 'user_id' not in df.columns or 'id' not in df.columns:
            return []

        # Filter by user_id (case-insensitive)
        user_id_lower = user_id.lower()
        df['user_id_lower'] = df['user_id'].astype(str).str.lower()
        user_ratings = df[df['user_id_lower'] == user_id_lower]

        # Get unique action IDs
        rated_ids = user_ratings['id'].unique().tolist()

        return rated_ids

    except Exception as e:
        print(f"[ERROR] Failed to get rated videos from Google Sheets: {e}")
        return []


def append_user_to_gsheets(user_data, worksheet="users_4c_images"):
    """
    Append a single user row to Google Sheets using true append (no overwrite).

    Parameters:
        user_data: Dictionary with user information
        worksheet: Name of worksheet to write to (default: "users")

    Returns:
        True if successful, False otherwise
    """
    try:
        # Get the gspread client for advanced operations
        gspread_client = get_gspread_client()
        if gspread_client is None:
            print("[WARNING] No gspread client available")
            return False

        # Add timestamp
        user_data_with_timestamp = user_data.copy()
        user_data_with_timestamp['timestamp'] = datetime.now().isoformat()

        # Get spreadsheet URL from secrets
        spreadsheet_url = st.secrets["connections"]["gsheets"]["spreadsheet"]

        # Open the spreadsheet
        spreadsheet = gspread_client.open_by_url(spreadsheet_url)

        # Try to get the worksheet, create if it doesn't exist
        try:
            ws = spreadsheet.worksheet(worksheet)
        except Exception:
            # Worksheet doesn't exist, create it
            ws = spreadsheet.add_worksheet(title=worksheet, rows=1000, cols=26)
            print(f"[INFO] Created new worksheet: {worksheet}")

        # Check if this is the first row (header needed)
        existing_data = ws.get_all_values()

        if len(existing_data) == 0 or (len(existing_data) == 1 and not existing_data[0]):
            # Sheet is empty, write header first
            headers = list(user_data_with_timestamp.keys())
            values = list(user_data_with_timestamp.values())

            ws.append_row(headers, value_input_option='RAW')
            ws.append_row(values, value_input_option='USER_ENTERED')
            print(f"[INFO] Created headers and appended first user to worksheet: {worksheet}")
        else:
            # Sheet has data, check if we need to add new columns
            existing_headers = existing_data[0]
            new_keys = set(user_data_with_timestamp.keys())
            existing_keys = set(existing_headers)

            # If there are new columns, we need to update headers
            if new_keys != existing_keys:
                all_keys = existing_keys | new_keys
                # Create ordered list of all columns
                all_columns = existing_headers + [k for k in new_keys if k not in existing_keys]

                # Update header row
                ws.update('1:1', [all_columns], value_input_option='RAW')

                # Prepare row with values in correct column order
                row_values = [user_data_with_timestamp.get(col, '') for col in all_columns]
            else:
                # Use existing column order
                row_values = [user_data_with_timestamp.get(col, '') for col in existing_headers]

            # Append the new row
            ws.append_row(row_values, value_input_option='USER_ENTERED')
            print(f"[INFO] User data appended to Google Sheets (worksheet: {worksheet})")

        return True

    except Exception as e:
        print(f"[ERROR] Failed to append user to Google Sheets: {e}")
        import traceback
        traceback.print_exc()
        return False


def read_users_from_gsheets(worksheet="users_4c_images"):
    """
    Read all users from Google Sheets.

    Parameters:
        worksheet: Name of worksheet to read from (default: "users")

    Returns:
        DataFrame with all users, or empty DataFrame if failed
    """
    try:
        conn = get_gsheets_connection()
        if conn is None:
            return pd.DataFrame()

        df = conn.read(worksheet=worksheet)
        print(f"[INFO] Read {len(df)} users from Google Sheets")
        return df

    except Exception as e:
        print(f"[ERROR] Failed to read users from Google Sheets: {e}")
        return pd.DataFrame()


def user_exists_in_gsheets(user_id, worksheet="users_4c_images"):
    """
    Check if a user exists in Google Sheets (case-insensitive).

    Parameters:
        user_id: User identifier to check
        worksheet: Name of worksheet to read from (default: "users")

    Returns:
        True if user exists, False otherwise
    """
    try:
        df = read_users_from_gsheets(worksheet=worksheet)

        if df.empty or 'user_id' not in df.columns:
            return False

        # Check if user_id exists (case-insensitive)
        user_id_lower = user_id.lower()
        df['user_id_lower'] = df['user_id'].astype(str).str.lower()
        return user_id_lower in df['user_id_lower'].values

    except Exception as e:
        print(f"[ERROR] Failed to check user existence in Google Sheets: {e}")
        return False


def get_all_user_ids_from_gsheets(worksheet="users_4c_images"):
    """
    Get all user IDs from Google Sheets.

    Parameters:
        worksheet: Name of worksheet to read from (default: "users")

    Returns:
        List of all user IDs
    """
    try:
        df = read_users_from_gsheets(worksheet=worksheet)

        if df.empty or 'user_id' not in df.columns:
            return []

        # Get all unique user IDs
        return df['user_id'].dropna().unique().tolist()

    except Exception as e:
        print(f"[ERROR] Failed to get all user IDs from Google Sheets: {e}")
        return []
