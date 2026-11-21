from unittest import TestCase
from unittest.mock import patch

from services.persistence import exercise_repository as history


class GuestHistoryTest(TestCase):
    @patch.object(history, "_get_connection")
    def test_guest_histories_are_isolated_and_never_use_sqlite(self, connection):
        first_session, second_session = {}, {}
        with patch.object(history.st, "session_state", first_session):
            history.add_exercise(None, "Squats", 3, 1, 10)
            history.add_exercise(None, "Squats", 4, 1, 12)
            row, = history.get_users_exercises(None)
            self.assertEqual((row["reps"], row["sets"], row["time"]), (7, 2, 22))
        with patch.object(history.st, "session_state", second_session):
            self.assertEqual(history.get_users_exercises(None), [])
        connection.assert_not_called()
