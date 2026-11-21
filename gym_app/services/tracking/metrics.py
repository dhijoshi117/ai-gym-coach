import sqlite3
import time

import streamlit as st

from services.coaching.voice_pipeline import publish_feedback
from services.config.workout_config import METRICS_FIELDS
from services.persistence.exercise_repository import add_exercise


def sync_metrics_update(context):
    state = st.session_state
    processor = context.video_processor
    if not state.workout_started or not context.state.playing or processor is None:
        return

    exercise = state.exercise_type
    latest_metrics = processor.get_latest_metrics()
    if not latest_metrics:
        return

    pose_detected = latest_metrics["pose_detected"]
    for key, default in METRICS_FIELDS[exercise].items():
        state[key] = latest_metrics.get(key, default) if pose_detected else default

    previous_reps = state.processor_reps if state.active_processor is processor else 0
    processor_reps = latest_metrics.get("reps", previous_reps)
    target_reps = state.target_sets * state.reps_per_set
    reps = min(state.reps + max(processor_reps - previous_reps, 0), target_reps)
    sets_completed, current_set_reps = divmod(reps, state.reps_per_set)
    newly_completed = sets_completed - state.sets_completed

    if newly_completed:
        now = time.monotonic()
        try:
            add_exercise(
                state.user_id, exercise, newly_completed * state.reps_per_set,
                newly_completed, now - state.set_cycle_started_at,
            )
        except sqlite3.Error:
            st.error("Couldn’t save this set. Tracking will retry while the camera is running.")
            return
        state.set_cycle_started_at = now

    state.active_processor = processor
    state.processor_reps = processor_reps
    state.reps = reps
    state.sets_completed = sets_completed
    state.current_set_reps = current_set_reps

    if reps == target_reps:
        state.workout_started = False
        set_label = "set" if sets_completed == 1 else "sets"
        rep_label = "rep" if reps == 1 else "reps"
        state.workout_summary = f"Workout complete · {sets_completed} {set_label} · {reps} {rep_label}"
        state.active_processor = None
        publish_feedback("workout_completed", exercise, latest_metrics)
    elif newly_completed:
        publish_feedback("set_completed", exercise, latest_metrics)
    elif not pose_detected:
        publish_feedback("no_pose_detected", exercise, {
            "issue": "Step into the camera frame so your joints are visible.",
        })
    else:
        publish_feedback("ongoing_form_check", exercise, latest_metrics)
