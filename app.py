import streamlit as st
import speech_recognition as sr
import re
import mysql.connector
from datetime import datetime
from sqlalchemy import text
import pandas as pd
import time

# ---------------------------------
# PAGE CONFIG
# ---------------------------------

st.set_page_config(
    page_title="Voice Attendance System",
    page_icon="🎙️",
    layout="wide",
)

# ---------------------------------
# DATABASE CONNECTION
# ---------------------------------

@st.cache_resource
def init_connection():
    """Initializes a connection to the MySQL database using Streamlit's secrets."""
    try:
        return st.connection("mysql", type='sql')
    except mysql.connector.Error as e:
        st.error(f"Failed to connect to MySQL: {e}")
        st.stop()

# Get the connection
conn = init_connection()

# ---------------------------------
# CORE FUNCTIONS
# ---------------------------------

@st.cache_data(ttl=60)
def fetch_data(query, params=None):
    """
    Fetches data from the database using the provided query and parameters.
    Uses the connection's engine directly with pandas.
    """
    if params is None:
        params = {}
    df = pd.read_sql(text(query), conn.engine, params=params)
    return df

def listen_for_voice():
    """
    Listens for voice input from the user's microphone.
    """
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        
        # --- LOUDNESS FIX ---
        # Increased duration from 0.5s to 1.0s to get a better
        # sample of ambient noise, making the mic more sensitive.
        recognizer.adjust_for_ambient_noise(source, duration=1.0)
        # --- END OF FIX ---
        
        try:
            # Increased phrase time limit to give user more time
            audio_data = recognizer.listen(source, timeout=5, phrase_time_limit=7)
            # Recognize speech using Google Web Speech API, optimized for Indian-English
            text = recognizer.recognize_google(audio_data, language="en-IN")
            return "success", text
        except sr.WaitTimeoutError:
            return "error", "Listening timed out. Please try again."
        except sr.UnknownValueError:
            return "error", "Sorry, I could not understand. Please speak clearly."
        except sr.RequestError as e:
            return "error", f"Could not request results; {e}"
        except Exception as e:
            return "error", f"An unknown error occurred: {e}"

def parse_attendance(text):
    """
    Parses the text to find student name and class using regex.
    """
    # --- "3A" FIX ---
    # Updated regex: ([\w\s-]+)$
    # This will now capture letters (a-z), numbers (0-9), spaces,
    # and hyphens in the class name (e.g., "3a", "10-B", " nursery").
    match = re.search(r"my name is (.*?) class ([\w\s-]+)$", text, re.IGNORECASE)
    # --- END OF FIX ---
    
    if match:
        name = match.group(1).strip().title()
        # .strip() will clean up " 3a " to "3a"
        class_name = match.group(2).strip()
        return name, class_name
    else:
        return None, None

def mark_attendance(name, class_name):
    """
    Inserts the attendance record into the database.
    """
    today_date = datetime.now().date()
    current_time = datetime.now().time()
    
    insert_query = """
    INSERT INTO attendance_records (student_name, class_name, date, time)
    VALUES (:name, :class, :date, :time)
    """
    
    try:
        with conn.session as s:
            s.execute(
                text(insert_query),
                {
                    "name": name,
                    "class": class_name,
                    "date": today_date,
                    "time": current_time
                }
            )
            s.commit()
        return "success", f"Attendance marked for {name}, Class {class_name}."
    
    except mysql.connector.Error as e:
        if e.errno == 1062:
            return "warning", f"{name} has already marked attendance for today."
        else:
            return "error", f"Database error: {e}"
    except Exception as e:
        if "Duplicate entry" in str(e):
            return "warning", f"{name} has already marked attendance for today."
        return "error", f"An unexpected error occurred: {e}"

# ---------------------------------
# SESSION STATE INITIALIZATION
# ---------------------------------

if 'listening_mode' not in st.session_state:
    st.session_state.listening_mode = False

# ---------------------------------
# STREAMLIT UI
# ---------------------------------

st.title("🎙️ Voice-Based Attendance System")

tab1, tab2 = st.tabs(["**Mark Attendance (Kiosk Mode)**", "**📊 Dashboard**"])

# -----------------
# TAB 1: MARK ATTENDANCE
# -----------------
with tab1:
    st.header("Speak to Mark Attendance")
    st.write("Click **'Start Session'** to begin. The app will automatically listen for the next student after each entry.")

    col1, col2 = st.columns(2)
    
    if col1.button("Start Attendance Session", type="primary", use_container_width=True):
        st.session_state.listening_mode = True
        st.rerun()

    if col2.button("Stop Session", use_container_width=True):
        st.session_state.listening_mode = False
        st.rerun()

    if st.session_state.listening_mode:
        st.markdown("---")
        
        with st.spinner("🎙️ **LISTENING...** Please speak your name and class."):
            status, message = listen_for_voice()
        
        if status == "success":
            st.write(f"**You said:** *'{message}'*")
            
            with st.spinner("Processing..."):
                name, class_name = parse_attendance(message)
                
                if name and class_name:
                    st.write(f"**Recognized:** Name: `{name}`, Class: `{class_name}`")
                    insert_status, insert_message = mark_attendance(name, class_name)
                    
                    if insert_status == "success":
                        st.success(insert_message)
                        st.balloons()
                    elif insert_status == "warning":
                        st.warning(insert_message)
                    else:
                        st.error(insert_message)
                else:
                    st.error("Could not extract name and class. Please follow the format: 'My name is [Name], class [Class]'.")
        
        elif status == "error":
            st.error(message)

        st.write("Getting ready for the next student...")
        time.sleep(2) # Wait 2 seconds for the user to read the message
        st.rerun()

    else:
        st.info("Session is stopped. Click 'Start' to begin.")


# -----------------
# TAB 2: DASHBOARD
# -----------------
with tab2:
    st.header("Attendance Dashboard")
    
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        today_query = "SELECT * FROM attendance_records WHERE date = :today ORDER BY time DESC"
        today_df = fetch_data(today_query, params={"today": today_str})
        
        classes_df = fetch_data("SELECT DISTINCT class_name FROM attendance_records ORDER BY class_name")
        class_list = ["All"] + list(classes_df['class_name'])

    except Exception as e:
        st.error(f"Failed to load dashboard data: {e}")
        st.stop()

    st.subheader("Filters")
    col1_dash, col2_dash = st.columns(2)
    
    with col1_dash:
        selected_date = st.date_input("Select Date", value=datetime.now().date())
    
    with col2_dash:
        selected_class = st.selectbox("Filter by Class", options=class_list)

    if not today_df.empty:
        filtered_df = today_df.copy()
        
        if selected_date == datetime.now().date():
            filtered_df = today_df
        else:
            filtered_df = fetch_data(
                "SELECT * FROM attendance_records WHERE date = :selected ORDER BY time DESC",
                params={"selected": selected_date.strftime("%Y-%m-%d")}
            )

        if selected_class != "All":
            filtered_df = filtered_df[filtered_df['class_name'] == selected_class]
            
    else:
        filtered_df = pd.DataFrame(columns=['student_name', 'class_name', 'date', 'time'])

    st.markdown("---")
    
    st.metric("Total Students Present Today", value=len(today_df))
    
    st.subheader(f"Attendance Records for {selected_date.strftime('%B %d, %Y')}")
    
    if filtered_df.empty:
        st.info("No attendance records found for the selected filters.")
    else:
        st.dataframe(
            filtered_df[['student_name', 'class_name', 'date', 'time']],
            use_container_width=True
        )

    st.markdown("---")
    st.subheader("Today's Attendance by Class")
    
    if today_df.empty:
        st.info("No data to display in charts.")
    else:
        class_counts = today_df['class_name'].value_counts().reset_index()
        class_counts.columns = ['class_name', 'count']
        
        st.bar_chart(class_counts, x='class_name', y='count')