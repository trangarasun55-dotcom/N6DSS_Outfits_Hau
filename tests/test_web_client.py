"""Flask test_client coverage for every public UI route and API outages."""
import io
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from web import app as web_app


def api_response(payload, status=200):
    response = Mock()
    response.status_code = status
    response.json.return_value = payload
    response.raise_for_status.return_value = None
    return response


INFO = {"categories": {"Hoàn cảnh": ["Đi học", "Xưởng/Công trình", "Vẽ ngoại cảnh", "Thuyết trình"],
                        "Phong cách": ["Casual", "Smart Casual", "Sporty", "Streetwear", "Minimalist", "Artsy"],
                        "Giới tính": ["Nam", "Nữ", "Unisex"], "Màu giao diện": ["Đen", "Trắng", "Xám", "Be", "Nâu đất", "Navy"]}}
RESULT = {"outfits": [{"name": "Casual - Đi học", "score": 8.1, "match_score": 81,
                       "items": [{"name": "Áo mẫu", "category": "Áo", "color": "Đen", "style": "Casual", "score": 8.1}],
                       "breakdown": [{"name": "Áo mẫu", "category": "Áo"}], "temp_score": 90,
                       "activity_score": 80, "style_score": 85, "explanation": "Phù hợp điều kiện."}]}


class WebClientTests(unittest.TestCase):
    def setUp(self):
        web_app.app.config.update(TESTING=True)
        self.client = web_app.app.test_client()
        web_app.OUTFIT_RESULTS.clear()
        with self.client.session_transaction() as sess:  # người dùng đã đăng nhập
            sess["api_auth_cookie"] = "test-cookie"
            sess["api_user"] = {"id": str(UUID(int=1)), "role": "user", "display_name": "Mai Linh", "gender": "Nữ"}
            sess["profile"] = {"name": "Mai Linh", "gender": "Nữ"}
        self.get_patch = patch("web.app.requests.get", return_value=api_response(INFO))
        self.mock_get = self.get_patch.start()
        self.addCleanup(self.get_patch.stop)
        self.post_patch = patch("web.app.requests.post", return_value=api_response(RESULT))
        self.mock_post = self.post_patch.start()
        self.addCleanup(self.post_patch.stop)

    def prepare_flow(self):
        self.client.post("/profile", data={"name": "Mai Linh", "year_label": "Sinh viên năm 3", "gender": "Nữ"})
        self.client.post("/activity", data={"activity": "Đi học", "gender": "Nữ", "temperature": "21", "temperature_source": "manual"})
        self.client.post("/style", data={"styles": ["Casual"], "colors": ["Đen"], "formality": "35", "temperature": "21"})

    def test_each_route_and_recommendation_flow(self):
        for path in ("/", "/outfit", "/history", "/profile", "/ui/model-info", "/ui/weather", "/style", "/results", "/detail/99"):
            with self.subTest(path=path):
                response = self.client.get(path, follow_redirects=(path == "/outfit"))
                self.assertIn(response.status_code, (200, 302, 404))
        self.assertEqual(self.client.post("/schedule", data={"day": "Thứ Hai", "class_time": "07:30", "subject": "Thiết kế", "room": "A1", "kind": "LT"}).status_code, 302)
        self.prepare_flow()
        self.assertEqual(self.client.get("/loading").status_code, 200)
        response = self.client.post("/loading")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.mock_post.call_args.kwargs["json"]["temperature"], 21.0)
        self.assertEqual(self.client.get("/results").status_code, 200)
        detail = self.client.get("/detail/1")
        self.assertEqual(detail.status_code, 200)
        self.assertIn(
            "Đang hiển thị giải thích theo quy tắc.",
            detail.get_data(as_text=True),
        )
        self.assertEqual(self.client.get("/ui/model-info").status_code, 200)

    def test_model_evaluation_page_is_not_accessible_by_direct_url(self):
        self.assertEqual(self.client.get("/model-evaluation").status_code, 404)
        self.assertEqual(self.client.get("/model_evaluation").status_code, 404)

    def test_static_assets_are_cached_and_result_cache_is_bounded(self):
        response = self.client.get("/static/css/tokens.css")
        self.assertEqual(response.status_code, 200)
        self.assertIn("max-age=3600", response.headers["Cache-Control"])
        for index in range(web_app.OUTFIT_RESULTS_MAX + 1):
            web_app.cache_outfit_result(str(index), {"outfits": []})
        self.assertEqual(len(web_app.OUTFIT_RESULTS), web_app.OUTFIT_RESULTS_MAX)
        self.assertNotIn("0", web_app.OUTFIT_RESULTS)
        self.assertIn(str(web_app.OUTFIT_RESULTS_MAX), web_app.OUTFIT_RESULTS)

    def test_valid_schedule_image_type_and_invalid_upload(self):
        invalid = self.client.post("/schedule", data={"schedule_mode": "upload", "schedule_image": (io.BytesIO(b"not image"), "bad.png", "image/png")}, content_type="multipart/form-data")
        self.assertEqual(invalid.status_code, 302)
        self.assertIn("schedule_error=format", invalid.location)

    def test_api_outage_is_friendly_and_manual_temperature_is_required(self):
        self.mock_get.side_effect = web_app.requests.ConnectionError("offline")
        self.assertEqual(self.client.get("/ui/model-info").status_code, 503)
        weather = self.client.get("/ui/weather")
        self.assertEqual(weather.status_code, 503)
        self.assertIn("thủ công", weather.get_json()["message"])
        home = self.client.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn("Không kết nối được API", home.get_data(as_text=True))
        bad = self.client.post("/activity", data={"activity": "Đi học", "gender": "Nữ", "temperature": "", "temperature_source": "live"})
        self.assertEqual(bad.status_code, 302)
        self.prepare_flow()
        self.mock_post.side_effect = web_app.requests.ConnectionError("offline")
        failed = self.client.post("/loading")
        self.assertEqual(failed.status_code, 503)
        self.assertIn("Không kết nối được API", failed.get_data(as_text=True))

    def test_invalid_activity_and_profile_input(self):
        self.assertEqual(self.client.post("/activity", data={"activity": "Không hợp lệ", "gender": "Nữ", "temperature": "21"}).status_code, 302)
        anonymous_profile = web_app.app.test_client().post("/profile", data={"display_name": "", "gender": "abc"})
        self.assertEqual(anonymous_profile.status_code, 302)
        self.assertIn("/login", anonymous_profile.location)

    def test_registration_requires_separate_login_and_logout_clears_session(self):
        client = web_app.app.test_client()
        response = client.post(
            "/register",
            data={"email": "student@example.test", "password": "long-enough-password", "display_name": "Sinh viên"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)
        with client.session_transaction() as web_session:
            self.assertNotIn("api_auth_cookie", web_session)
            self.assertNotIn("api_user", web_session)

        with client.session_transaction() as web_session:
            web_session["api_auth_cookie"] = "session-token"
            web_session["api_user"] = {"id": "user-id", "role": "user"}
        logout = client.post("/logout")
        self.assertEqual(logout.status_code, 302)
        self.assertIn("/login", logout.location)
        with client.session_transaction() as web_session:
            self.assertNotIn("api_auth_cookie", web_session)
            self.assertNotIn("api_user", web_session)

    def test_admin_navigation_and_route_are_role_gated(self):
        with self.client.session_transaction() as web_session:
            web_session["api_auth_cookie"] = "user-session"
            web_session["api_user"] = {"id": "user-id", "role": "user", "display_name": "Bạn"}
        user_home = self.client.get("/")
        self.assertNotIn("Quản trị", user_home.get_data(as_text=True))
        self.assertEqual(self.client.get("/admin").status_code, 403)

        with self.client.session_transaction() as web_session:
            web_session["api_user"] = {"id": "admin-id", "role": "admin", "display_name": "Quản trị viên"}
        admin_page = self.client.get("/admin")
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn("Quản trị", admin_page.get_data(as_text=True))

    def test_history_and_feedback_use_session_user_identity(self):
        user_id = "16a1c9e2-df04-46f3-94d2-dbe5c3608530"
        with self.client.session_transaction() as web_session:
            web_session["api_auth_cookie"] = "test-session-cookie"
            web_session["api_user"] = {"id": user_id, "role": "user", "display_name": "Sinh viên"}
        history_payload = {
            "items": [
                {
                    "event_id": "event-1",
                    "type": "viewed",
                    "request_item_id": 42,
                    "request_id": "f16a1c9e-2df0-46f3-94d2-dbe5c3608530",
                    "name": "Casual – Đi học",
                    "activity": "Đi học",
                    "temperature": 21.0,
                    "score": 8.2,
                    "score_low": 7.8,
                    "score_high": 8.6,
                    "confidence_level": "Cao",
                    "items": [{"name": "Áo sơ mi"}],
                    "created_at": "2026-10-10T00:00:00Z",
                    "finalized_at": None,
                    "feedback": None,
                }
            ]
        }
        self.mock_get.return_value = api_response(history_payload)
        response = self.client.get("/history")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Casual – Đi học", response.get_data(as_text=True))
        self.assertIn("7.8–8.6/10", response.get_data(as_text=True))
        self.assertIn("Độ tin cậy Cao", response.get_data(as_text=True))
        self.assertEqual(self.mock_get.call_args.kwargs["headers"]["X-User-Id"], user_id)
        UUID(user_id)

        feedback_response = self.client.post(
            "/feedback",
            data={
                "request_id": history_payload["items"][0]["request_id"],
                "outfit_id": "42",
                "action": "like",
                "note": "Hữu ích",
            },
        )
        self.assertEqual(feedback_response.status_code, 302)
        self.assertEqual(self.mock_post.call_args.kwargs["headers"]["X-User-Id"], user_id)
        self.assertEqual(self.mock_post.call_args.kwargs["json"]["action"], "like")

    def test_history_filters_and_authentication_gate(self):
        anonymous = web_app.app.test_client().get("/history")
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/login", anonymous.location)

        with self.client.session_transaction() as web_session:
            web_session["api_auth_cookie"] = "test-session-cookie"
            web_session["api_user"] = {"id": "test-user", "role": "user", "display_name": "Sinh viên"}
        response = self.client.get("/history?type=feedback&range=from-to&from=2026-10-01&to=2026-10-10")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Khoảng ngày", response.get_data(as_text=True))
        history_calls = [call for call in self.mock_get.call_args_list if call.args[0].endswith("/history")]
        self.assertEqual(history_calls[0].kwargs["params"]["type"], "feedback")
        self.assertEqual(history_calls[0].kwargs["params"]["from"], "2026-10-01")

    def test_profile_template_uses_api_profile_data(self):
        with self.client.session_transaction() as web_session:
            web_session["api_auth_cookie"] = "test-session-cookie"
            web_session["api_user"] = {"id": "test-user", "role": "user", "display_name": "Sinh viên"}
        profile = {"profile": {"display_name": "Mai Linh", "email": "mai@example.test", "gender": "Nữ"}}
        self.mock_get.side_effect = lambda url, **kwargs: api_response(
            profile if url.endswith("/profile") else {"items": [], "total": 0}
        )
        response = self.client.get("/profile")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Mai Linh", response.get_data(as_text=True))
        self.assertIn("Đổi mật khẩu", response.get_data(as_text=True))

    def test_running_api_through_flask_client(self):
        self.get_patch.stop()
        self.post_patch.stop()
        metadata = self.client.get("/ui/model-info")
        if metadata.status_code != 200:
            self.skipTest("FastAPI Bước 2 không chạy tại API_URL.")
        self.prepare_flow()
        response = self.client.post("/loading")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/results").status_code, 200)


class AuthGateTests(unittest.TestCase):
    """Chưa đăng nhập chỉ vào được trang đăng nhập/đăng ký; đăng xuất quay về trang đăng nhập."""

    PROTECTED = ("/", "/outfit", "/history", "/profile", "/admin", "/style", "/results", "/detail/1", "/loading")

    def setUp(self):
        web_app.app.config.update(TESTING=True)
        self.client = web_app.app.test_client()
        self.get_patch = patch("web.app.requests.get", return_value=api_response(INFO))
        self.get_patch.start()
        self.addCleanup(self.get_patch.stop)

    def login_response(self, role="user"):
        response = api_response({"user": {"id": str(UUID(int=2)), "role": role, "display_name": "Lan Anh", "gender": "Nữ"}})
        response.cookies = {"outfit_session": "token"}
        return response

    def test_anonymous_is_redirected_to_login_everywhere(self):
        for path in self.PROTECTED:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 302)
                self.assertIn("/login", response.location)
        self.assertEqual(self.client.get("/ui/model-info").status_code, 401)
        self.assertEqual(self.client.post("/ui/events/view", json={}).status_code, 401)

    def test_login_and_register_pages_are_standalone(self):
        for path, marker in (("/login", "Đăng nhập"), ("/register", "Tạo tài khoản")):
            with self.subTest(path=path):
                response = self.client.get(path)
                html = response.get_data(as_text=True)
                self.assertEqual(response.status_code, 200)
                self.assertIn(marker, html)
                self.assertNotIn("sidebar", html)
                self.assertNotIn("Đăng xuất", html)
                self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_login_logout_cycle(self):
        with patch("web.app.requests.post", return_value=self.login_response()):
            response = self.client.post("/login", data={"email": "a@b.vn", "password": "x" * 12})
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.location.endswith("/"))
        home = self.client.get("/")
        html = home.get_data(as_text=True)
        self.assertEqual(home.status_code, 200)
        self.assertIn("Đăng xuất", html)
        self.assertNotIn(">Đăng ký<", html)
        self.assertNotIn(">Đăng nhập<", html)
        with patch("web.app.requests.post", return_value=api_response({"status": "logged_out"})):
            logout = self.client.post("/logout")
        self.assertEqual(logout.status_code, 302)
        self.assertTrue(logout.location.endswith("/login"))
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertEqual(self.client.get("/history").status_code, 302)

    def test_admin_login_goes_to_dashboard(self):
        with patch("web.app.requests.post", return_value=self.login_response("admin")):
            response = self.client.post("/login", data={"email": "admin@x.vn", "password": "x" * 12})
        self.assertTrue(response.location.endswith("/admin"))

    def test_login_next_cannot_redirect_off_site(self):
        with patch("web.app.requests.post", return_value=self.login_response()):
            response = self.client.post("/login", data={"email": "a@b.vn", "password": "x" * 12, "next": "//evil.example"})
        self.assertTrue(response.location.endswith("/"))
        self.assertNotIn("evil", response.location)

    def test_wrong_password_and_offline_api_show_friendly_errors(self):
        bad = Mock()
        bad.status_code = 401
        bad.raise_for_status.side_effect = web_app.requests.HTTPError(response=bad)
        with patch("web.app.requests.post", return_value=bad):
            response = self.client.post("/login", data={"email": "a@b.vn", "password": "wrong"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("Email hoặc mật khẩu không đúng", response.get_data(as_text=True))
        with patch("web.app.requests.post", side_effect=web_app.requests.ConnectionError("offline")):
            response = self.client.post("/login", data={"email": "a@b.vn", "password": "x" * 12})
        self.assertEqual(response.status_code, 503)
        self.assertIn("Không kết nối được máy chủ xác thực", response.get_data(as_text=True))

    def test_expired_api_session_returns_to_login(self):
        with self.client.session_transaction() as sess:
            sess["api_auth_cookie"] = "stale"
            sess["api_user"] = {"id": str(UUID(int=3)), "role": "user", "display_name": "Cũ"}
        expired = Mock()
        expired.status_code = 401
        with patch("web.app.requests.get", return_value=expired):
            response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)  # hiện form, không lặp chuyển hướng
        self.assertEqual(self.client.get("/").status_code, 302)  # phiên web đã bị xóa


if __name__ == "__main__":
    unittest.main()
