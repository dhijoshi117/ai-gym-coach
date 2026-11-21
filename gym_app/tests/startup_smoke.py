"""Check Linux native imports, a model frame, and the Streamlit guest UI."""
from pathlib import Path
import os

import av
import numpy as np
from streamlit.testing.v1 import AppTest

from services.vision.exercise_video_processor import VideoProcessorClass


def main():
    os.environ.pop("GYM_COACH_MODE", None)
    app_path = Path(__file__).resolve().parents[1] / "main.py"
    app = AppTest.from_file(str(app_path), default_timeout=30).run()
    assert not app.exception, app.exception
    assert any("Guest session" in caption.value for caption in app.sidebar.caption)
    assert app.button(key="start_session_button").label == "Start Workout"

    processor = VideoProcessorClass()
    frame = av.VideoFrame.from_ndarray(np.zeros((240, 320, 3), dtype=np.uint8), format="bgr24")
    result = processor.recv(frame)
    assert (result.width, result.height) == (320, 240)
    assert processor.get_latest_metrics() == {"pose_detected": False, "reps": 0}


if __name__ == "__main__":
    main()
