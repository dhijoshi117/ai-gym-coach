import streamlit as st
import os
import time
from functools import partial
from pathlib import Path
import pandas as pd
from services.auth.login_wall import render_login_wall
from services.state.session_defaults import initial_session_defaults
from services.config.workout_config import EXERCISE_OPTIONS, METRICS_FIELDS
from services.ui.style_loader import load_css, inject_local_font, inject_webrtc_styles
from services.persistence.exercise_repository import init_db
from streamlit_webrtc import webrtc_streamer, WebRtcMode
from services.vision.exercise_video_processor import VideoProcessorClass
from services.tracking.metrics import sync_metrics_update
from services.persistence.exercise_repository import get_users_exercises
from groq import Groq
from services.coaching.llm import LLMCoach
from services.coaching.tts import TextToSpeech
from services.coaching.voice_pipeline import VoicePipeline, publish_feedback


APP_DIR = Path(__file__).resolve().parent


def render_coach_feedback():
    state = st.session_state
    if state.get("coach_feedback"):
        st.caption(f"Coach · {state.coach_feedback}")
    if state.get("voice_error"):
        st.warning(state.voice_error)
    if state.get("audio_to_play"):
        st.audio(
            state.audio_to_play,
            format="audio/mp3",
            autoplay=state.pop("audio_autoplay_pending", False),
        )


@st.fragment(run_every=0.5)
def render_live_progress(context):
    sync_metrics_update(context)
    if not st.session_state.workout_started:
        st.rerun()

    render_coach_feedback()

    exercise = st.session_state.get("exercise_type")
    total_reps = st.session_state.get("reps")
    current_set_reps = st.session_state.get("current_set_reps")
    reps_per_set = st.session_state.get("reps_per_set")
    sets_completed = st.session_state.get("sets_completed")
    target_sets = st.session_state.get("target_sets")

    st.subheader("Progress")
    total, current, sets = st.columns(3)
    total.metric("Total Reps", total_reps)
    current.metric("Current Set Reps", f"{current_set_reps} / {reps_per_set}")
    sets.metric("Sets Completed", f"{sets_completed} / {target_sets}")

    st.divider()

    if exercise == "Squats":
        st.subheader("Squat Metrics")
        st.metric("Knee Angle", f"{st.session_state.knee_angle}°")
        st.metric("Back Angle", f"{st.session_state.back_angle}°")
        st.metric("Depth Status", st.session_state.depth_status)

    elif exercise == "Push-ups":
        st.subheader("Push-up Metrics")
        st.metric("Elbow Angle", f"{st.session_state.elbow_angle}°")
        st.metric("Body Alignment", st.session_state.body_alignment)
        st.metric("Hip Position", st.session_state.hip_status)

    elif exercise == "Biceps Curls (Dumbbell)":
        st.subheader("Curl Metrics")
        st.metric("Elbow Angle", f"{st.session_state.elbow_angle}°")
        st.metric("Shoulder Stability", st.session_state.shoulder_status)
        st.metric("Swing Detection", st.session_state.swing_status)

    elif exercise == "Shoulder Press":
        st.subheader("Shoulder Press Metrics")
        st.metric("Elbow Angle", f"{st.session_state.elbow_angle}°")
        st.metric("Arm Extension", st.session_state.extension_status)
        st.metric("Back Arch", st.session_state.back_arch_status)

    elif exercise == "Lunges":
        st.subheader("Lunge Metrics")
        st.metric("Front Knee Angle", f"{st.session_state.front_knee_angle}°")
        st.metric("Torso Angle", f"{st.session_state.torso_angle}°")
        st.metric("Balance Status", st.session_state.balance_status)


def start_workout():
    plan_exercise = st.session_state.plan_exercise
    plan_sets = st.session_state.plan_sets
    plan_reps = st.session_state.plan_reps
    st.session_state.exercise_type = plan_exercise
    st.session_state.target_sets = int(plan_sets)
    st.session_state.reps_per_set = int(plan_reps)
    st.session_state.reps = 0
    st.session_state.sets_completed = 0
    st.session_state.current_set_reps = 0
    st.session_state.processor_reps = 0
    st.session_state.active_processor = None
    st.session_state.workout_number += 1
    st.session_state.workout_summary = ""
    clear_coach_feedback()
    for key, default in METRICS_FIELDS[plan_exercise].items():
        st.session_state[key] = default
    st.session_state.workout_started = True
    st.session_state.set_cycle_started_at = time.monotonic()
    publish_feedback("workout_started", plan_exercise, {})


def end_workout():
    st.session_state.workout_started = False
    st.session_state.active_processor = None
    st.session_state.workout_summary = "Workout ended. Completed sets are in your history."
    clear_coach_feedback()


def clear_coach_feedback():
    for key in ("audio_to_play", "audio_autoplay_pending", "coach_feedback", "voice_error"):
        st.session_state.pop(key, None)


def main():
    st.set_page_config(
        page_icon="🏋️‍♀️",
        page_title="AI Real-time GYM Coach",
        initial_sidebar_state="expanded",
        layout="centered"
    )

    load_css(APP_DIR / "static" / "style.css")
    inject_local_font(APP_DIR / "static" / "AdobeClean.otf", "AdobeClean")

    local_history = os.environ.get("GYM_COACH_MODE") == "local"
    if local_history:
        init_db()
        if not render_login_wall():
            return
    else:
        st.session_state.user_id = None

    initial_session_defaults()

    if "voice_pipeline" not in st.session_state:
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            try:
                api_key = st.secrets.get("GROQ_API_KEY")
            except FileNotFoundError:
                pass

        st.session_state.voice_pipeline = (
            VoicePipeline(LLMCoach(Groq(api_key=api_key, timeout=5.0, max_retries=0)), TextToSpeech())
            if api_key else None
        )

    workout_started = st.session_state.get("workout_started", False)
    
    with st.sidebar:
        st.title("🏋️‍♂️ Apna AI Coach")

        if local_history:
            st.caption(f"Local profile · {st.session_state.username}")
        else:
            st.caption("Guest session · history lasts until you reload or close this tab.")

        st.divider()

        st.subheader("Workout Plan")

        if st.session_state.voice_pipeline:
            st.toggle("AI voice coaching", key="voice_enabled", disabled=workout_started)
            if st.session_state.voice_enabled and not workout_started:
                if st.button("Test voice", width="stretch"):
                    clear_coach_feedback()
                    publish_feedback("voice_test", "", {})
        else:
            st.caption("Text coaching is active. A Groq API key enables optional voice.")

        if not workout_started:
            st.selectbox("Exercise", options=EXERCISE_OPTIONS, key="plan_exercise")

            st.number_input("Sets", min_value=1, max_value=50, key="plan_sets", step=1)

            st.number_input("Reps per Set", min_value=1, max_value=50, key="plan_reps", step=1)

            st.markdown("")

            st.button("Start Workout", width="stretch", key="start_session_button", on_click=start_workout)
        else:
            exercise = st.session_state.get("exercise_type")
            sets = st.session_state.get("target_sets")
            reps = st.session_state.get("reps_per_set")

            st.info(f"**{exercise}** -- {sets} Sets / {reps} Reps")

            st.button("End Workout", width="stretch", key="end_session_button", on_click=end_workout)

    st.title("AI Real-time GYM Coach")
    st.caption("Live pose tracking, rep counting, and form feedback")
    if not local_history:
        st.caption("When you start the camera, video is processed by the app server. The app saves workout totals only.")
 
    if st.session_state.workout_summary:
        st.success(st.session_state.workout_summary)

    if not workout_started:
        render_coach_feedback()
        if not st.session_state.workout_summary:
            st.info("Choose an exercise, sets, and reps in the sidebar. Then start your workout and turn on the camera.")
    else:
        context = webrtc_streamer(
            key=f"exercise-analysis-{st.session_state.workout_number}",
            mode=WebRtcMode.SENDRECV,
            video_processor_factory=partial(
                VideoProcessorClass, exercise_type=st.session_state.exercise_type
            ),
            rtc_configuration={"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]},
            media_stream_constraints={
                "video": True,
                "audio": False
            },
            async_processing=True
        )

        render_live_progress(context)
        inject_webrtc_styles()

    st.divider()

    st.subheader("Workout History")

    user_id = st.session_state.get("user_id", 0)

    if user_id is None or isinstance(user_id, int):
        history_rows = get_users_exercises(user_id)

        arr = [
            {
                "Exercise": row['exercise_name'],
                "Reps": row['reps'],
                "Sets": row['sets'],
                "Time (sec)": row['time'],
                "Date": row['created_at']
            }
            for row in history_rows
        ]

        df = pd.DataFrame(arr)

        if not df.empty:
            df["Date"] = pd.to_datetime(df["Date"]).dt.date
            agg_df = df.groupby(["Exercise", "Date"]).agg({
                "Reps": 'sum',
                "Sets": "sum",
                "Time (sec)": "sum"
            }).reset_index()
            agg_df = agg_df.sort_values(["Date", "Exercise"], ascending=[False, True])
            st.dataframe(
                agg_df[["Date", "Exercise", "Sets", "Reps", "Time (sec)"]],
                hide_index=True,
                width="stretch",
                column_config={"Time (sec)": st.column_config.NumberColumn(format="%.1f")},
            )
        else:
            st.info("No workout history found.")


if __name__ == "__main__":
    main()
    