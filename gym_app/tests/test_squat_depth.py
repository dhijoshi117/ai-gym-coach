from math import cos, radians, sin
from types import SimpleNamespace
from unittest import TestCase

from detectors.squat import SquatDetector


def landmarks_for_angle(angle):
    landmarks = [SimpleNamespace(x=.5, y=.5, visibility=.99) for _ in range(33)]
    for hip, ankle in ((23, 27), (24, 28)):
        landmarks[hip].x = .6
        landmarks[ankle].x += .1 * cos(radians(angle))
        landmarks[ankle].y += .1 * sin(radians(angle))
    return landmarks


class SquatDepthTest(TestCase):
    def test_full_rep_does_not_get_shallow_cue_on_ascent(self):
        detector = SquatDetector()
        results = [detector.process(landmarks_for_angle(a)) for a in (175, 130, 85, 120, 175, 175)]
        self.assertEqual([r["reps"] for r in results], [0, 0, 0, 0, 1, 1])
        self.assertNotIn("TOO HIGH", [r["depth_status"] for r in results])
        self.assertEqual(results[-1]["depth_status"], "GOOD DEPTH")

    def test_shallow_attempt_warns_on_return_without_counting(self):
        detector = SquatDetector()
        results = [detector.process(landmarks_for_angle(a)) for a in (175, 130, 120, 175)]
        self.assertEqual(results[-2]["depth_status"], "IN PROGRESS")
        self.assertEqual(results[-1]["depth_status"], "TOO HIGH")
        self.assertEqual(results[-1]["reps"], 0)

    def test_pose_loss_discards_unfinished_attempt(self):
        detector = SquatDetector()
        detector.process(landmarks_for_angle(85))
        detector.on_pose_lost()
        result = detector.process(landmarks_for_angle(175))
        self.assertEqual(result["depth_status"], "STANDING")
        self.assertEqual(result["reps"], 0)
