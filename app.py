import streamlit as st
import speech_recognition as sr
import re
import mysql.connector
from datetime import datetime
from sqlalchemy import text
import pandas as pd
import time
from streamlit_webrtc import webrtc_streamer, WebRtcMode, AudioProcessorBase
import av

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

conn = init_connection()

# ---------------------------------
# CORE FUNCTIONS
# ---------------------------------

@st.cache_data(ttl=60)
def fetch_data(query, params=None):
    """Fetches data from the database using the provided query and parameters."""
    if params is None:
        params = {}
    df = pd.read_sql(text(query), conn.engine, params=params)
    return df


def parse_attendance(text):
    """Parses recognized speech for name and class."""
    match = re.search(r"my name is (.*?) class ([\w\s-]+)$", text, re.IGNORECASE)
    if match:
        name = match.group(1).strip().title()
        class_name = match.group(2).strip()
        return name, class_name
    return None, None


def mark_attendance(name, class_name):
    """Marks attendance in the database."""
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
        return "error", f"Unexpected error: {e}"


# ---------------------------------
# STREAMLIT-WEBRTC VOICE HANDLER
# ---------------------------------

class AudioProcessor(AudioProcessorBase):
    def __init__(self):
        self.recognizer = sr.Recognizer()
        self.transcript = ""

    def recv_audio(self, frame: av.AudioFrame) -> av.AudioFrame:
        audio = frame.to_ndarray()
        return frame


# ---------------------------------
# STREAMLIT UI
# ---------------------------------

st.title("🎙️ Voice-Based Attendance System")

tab1, tab2 = st.tabs(["**🎤 Mark Attendance (Mic)**", "**📊 Dashboard**"])

# -----------------
# TAB 1: MARK ATTENDANCE
# -----------------
with tab1:
    st.header("Speak to Mark Attendance")

    st.info("🎤 Click **Start Recording** below and say: *'My name is [Name], class [Class]'*")

    # 🎙️ Live mic recording using streamlit-webrtc
    webrtc_ctx = webrtc_streamer(
        key="speech",
        mode=WebRtcMode.SENDONLY,
        audio_receiver_size=256,
        media_stream_constraints={"audio": True, "video": False},
    )

    # Only show this section when user clicks start
    if webrtc_ctx.state.playing:
        st.markdown("---")
        st.write("🕒 **Listening... Please speak clearly.**")

        recognizer = sr.Recognizer()
        try:
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=1)
                audio_data = recognizer.listen(source, timeout=5, phrase_time_limit=7)
                text_result = recognizer.recognize_google(audio_data, language="en-IN")
                st.success(f"✅ You said: '{text_result}'")

                name, class_name = parse_attendance(text_result)
                if name and class_name:
                    status, msg = mark_attendance(name, class_name)
                    if status == "success":
                        st.success(msg)
                        st.balloons()
                    elif status == "warning":
                        st.warning(msg)
                    else:
                        st.error(msg)
                else:
                    st.warning("❌ Could not detect name or class. Please repeat clearly.")
        except Exception as e:
            st.error(f"🎧 Error capturing audio: {e}")

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
        st.dataframe(filtered_df[['student_name', 'class_name', 'date', 'time']], use_container_width=True)

    st.markdown("---")
    st.subheader("Today's Attendance by Class")

    if today_df.empty:
        st.info("No data to display in charts.")
    else:
        class_counts = today_df['class_name'].value_counts().reset_index()
        class_counts.columns = ['class_name', 'count']
        st.bar_chart(class_counts, x='class_name', y='count')
