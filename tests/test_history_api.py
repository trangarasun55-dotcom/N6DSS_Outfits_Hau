"""HTTP validation and ownership checks for persisted recommendations."""

import os
import sqlite3
import tempfile
from contextlib import closing
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient

from api import main


class HistoryApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_patch = patch.dict(
            os.environ,
            {
                "DB_PATH": str(Path(self.temp_dir.name) / "api.db"),
                "GEMINI_API_KEY": "",
                "SECRET_KEY": "history-test-secret",
            },
        )
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(self.temp_dir.cleanup)
        self.client = TestClient(main.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        registered = self.client.post(
            "/auth/register",
            json={
                "email": "history-user@example.test",
                "password": "History-User-Password-42!",
                "display_name": "History User",
            },
        )
        self.user_id = registered.json()["user"]["id"]
        self.result = {
            "outfits": [
                {
                    "id": 1,
                    "name": "Casual – Đi học",
                    "score": 8.2,
                    "match_score": 82,
                    "items": [{"id": "shirt-1", "name": "Áo sơ mi"}],
                    "explanation": "Giải thích theo quy tắc.",
                }
            ]
        }

    def test_recommendation_is_saved_and_scoped_to_user(self):
        with (
            patch("api.main.build_recommendations", return_value=self.result.copy()),
        ):
            response = self.client.post(
                "/recommend",
                headers={"X-User-Id": self.user_id},
                json={
                    "gender": "Nữ",
                    "activity": "Đi học",
                    "temperature": 22,
                },
            )
        self.assertEqual(response.status_code, 200)
        request_id = response.json()["request_id"]
        self.assertEqual(response.json()["outfits"][0]["explanation_source"], "rules")
        self.assertEqual(
            response.json()["outfits"][0]["explanation_llm"],
            "Giải thích theo quy tắc.",
        )
        history = self.client.get("/history")
        self.assertEqual(history.status_code, 200)
        self.assertEqual(
            history.json()["items"],
            [],
        )
        self.assertEqual(
            self.client.get("/history?type=all").status_code,
            422,
        )
        with closing(sqlite3.connect(Path(self.temp_dir.name) / "api.db")) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM recommendation_requests WHERE id = ?",
                    (request_id,),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM recommendation_items WHERE request_id = ?",
                    (request_id,),
                ).fetchone()[0],
                1,
            )
            self.assertIn(
                3,
                {
                    row[0]
                    for row in connection.execute("SELECT version FROM schema_migrations")
                },
            )

    def test_history_requires_authenticated_session(self):
        self.client.post("/auth/logout")
        self.assertEqual(self.client.get("/history").status_code, 401)
        self.assertEqual(
            self.client.get("/history", headers={"X-User-Id": str(uuid4())}).status_code,
            401,
        )
        self.client.post(
            "/auth/login",
            json={
                "email": "history-user@example.test",
                "password": "History-User-Password-42!",
            },
        )
        recommendation = self.client.post(
            "/recommend",
            json={"gender": "Nữ", "activity": "Đi học", "temperature": 22},
        )
        self.assertEqual(recommendation.status_code, 200)
        self.assertIn("request_id", recommendation.json())

    def test_feedback_is_validated_and_owner_scoped(self):
        request_id = main.save_recommendation(
            UUID(self.user_id),
            {"activity": "Đi học", "temperature": 22},
            self.result.copy(),
        )
        payload = {
            "request_id": request_id,
            "outfit_id": 1,
            "action": "worn",
            "note": "  Đã mặc hôm nay  ",
        }
        saved = self.client.post(
            "/feedback", headers={"X-User-Id": self.user_id}, json=payload
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()["status"], "saved")
        self.assertEqual(
            self.client.post(
                "/feedback",
                headers={"X-User-Id": str(uuid4())},
                json=payload,
            ).status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/feedback",
                headers={"X-User-Id": self.user_id},
                json={**payload, "action": "invalid"},
            ).status_code,
            422,
        )


if __name__ == "__main__":
    unittest.main()
