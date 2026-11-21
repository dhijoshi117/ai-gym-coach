from math import cos, radians, sin
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from detectors.biceps_curl import BicepsCurlDetector
from detectors.lunges import LungesDetector
from detectors.pushup import PushUpDetector
from detectors.shoulder_press import ShoulderPressDetector
from detectors.squat import SquatDetector
from services.coaching.voice_pipeline import VoicePipeline
from services.tracking.metrics import sync_metrics_update


class State(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class WorkoutTest(TestCase):
    def setUp(self):
        self.state = State(
            exercise_type="Squats", target_sets=2, reps_per_set=3, reps=0,
            user_id=1, sets_completed=0, current_set_reps=0, active_processor=None,
            processor_reps=0, set_cycle_started_at=0, workout_started=True,
        )
        self.context = SimpleNamespace(
            video_processor=Mock(), state=SimpleNamespace(playing=True),
        )

    def sync(self, reps, pose_detected=True):
        self.context.video_processor.get_latest_metrics.return_value = {
            "reps": reps, "pose_detected": pose_detected, "depth_status": "TOO HIGH",
        }
        sync_metrics_update(self.context)

    @patch("services.tracking.metrics.publish_feedback")
    @patch("services.tracking.metrics.add_exercise")
    def test_counts_across_reconnect_and_caps_at_target(self, save, feedback):
        with patch("services.tracking.metrics.st.session_state", self.state):
            self.sync(3)
            self.sync(3)
            self.context.video_processor = Mock()
            self.sync(5)
            self.sync(8)
        self.assertEqual((self.state.reps, self.state.sets_completed), (6, 2))
        self.assertFalse(self.state.workout_started)
        self.assertEqual([call.args[2:4] for call in save.call_args_list], [(3, 1), (3, 1)])
        self.assertEqual(feedback.call_args.args[0], "workout_completed")

    @patch("services.tracking.metrics.publish_feedback")
    @patch("services.tracking.metrics.add_exercise")
    def test_missing_pose_clears_cues_and_preserves_progress(self, save, feedback):
        with patch("services.tracking.metrics.st.session_state", self.state):
            self.sync(2)
            self.sync(2, pose_detected=False)
        self.assertEqual(self.state.reps, 2)
        self.assertEqual(self.state.depth_status, "N/A")
        self.assertEqual(feedback.call_args.args[0], "no_pose_detected")
        save.assert_not_called()

    @patch("services.tracking.metrics.publish_feedback")
    @patch("services.tracking.metrics.add_exercise")
    def test_persistence_progress_advances_before_optional_feedback(self, save, feedback):
        feedback.side_effect = [RuntimeError("voice unavailable"), None]
        with patch("services.tracking.metrics.st.session_state", self.state):
            with self.assertRaises(RuntimeError):
                self.sync(3)
            self.sync(3)
        save.assert_called_once()
        self.assertEqual(self.state.sets_completed, 1)


class VoiceTest(TestCase):
    def test_groq_failure_speaks_default_cue(self):
        llm = Mock()
        llm.give_feedback.side_effect = TimeoutError()
        tts = Mock()
        tts.speak.return_value = b"fallback mp3"
        pipeline = VoicePipeline(llm, tts)
        with self.assertLogs("services.coaching.voice_pipeline", level="WARNING"):
            self.assertEqual(
                pipeline.process_event("set_completed", None, "Set complete."),
                (b"fallback mp3", "Set complete."),
            )
        tts.speak.assert_called_once_with("Set complete.")

    def test_tts_failure_keeps_generated_text(self):
        llm, tts = Mock(), Mock()
        llm.give_feedback.return_value = "Great work!"
        tts.speak.side_effect = TimeoutError()
        with self.assertLogs("services.coaching.voice_pipeline", level="WARNING"):
            self.assertEqual(
                VoicePipeline(llm, tts).process_event("set_completed", None, "Set complete."),
                (None, "Great work!"),
            )


class DetectorTest(TestCase):
    def test_full_cycles_count_once_and_reset(self):
        knees = ((23, 25, 27), (24, 26, 28))
        elbows = ((11, 13, 15), (12, 14, 16))
        for detector, angles, joints in (
            (SquatDetector(), (175, 80, 175), knees),
            (PushUpDetector(), (175, 80, 175), elbows),
            (BicepsCurlDetector(), (175, 40, 175), elbows),
            (ShoulderPressDetector(), (80, 175, 80), elbows),
            (LungesDetector(), (175, 80, 175), knees),
        ):
            with self.subTest(detector=type(detector).__name__):
                counts = []
                for angle in (*angles, angles[-1]):
                    landmarks = [
                        SimpleNamespace(x=0.5, y=0.5, visibility=0.99)
                        for _ in range(33)
                    ]
                    for first, _, last in joints:
                        landmarks[first].x = 0.6
                        landmarks[last].x += 0.1 * cos(radians(angle))
                        landmarks[last].y += 0.1 * sin(radians(angle))
                    counts.append(detector.process(landmarks)["reps"])
                self.assertEqual(counts, [0, 0, 1, 1])
                detector.reset()
                self.assertEqual(detector.reps, 0)
