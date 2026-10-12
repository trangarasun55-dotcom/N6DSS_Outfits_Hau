"""Structured Gemini comments, validation, cache and deterministic fallbacks."""

import json
import os
import unittest
from unittest.mock import Mock, patch

from api import llm_explain


REQUEST = {
    "gender": "Nữ",
    "activity": "Đi học",
    "temperature": 22,
    "temperature_source": "live",
    "styles": ["Casual"],
    "colors": ["Đen"],
    "formality": 35,
    "rain_probability": 45,
    "schedule_summary": "07:30 Thiết kế tại A1",
}
RESULT = {
    "outfits": [
        {
            "id": 1,
            "name": "Casual – Đi học",
            "score": 8.1,
            "score_low": 7.5,
            "score_high": 8.7,
            "confidence_level": "Cao",
            "items": [
                {
                    "name": "Áo sơ mi trắng",
                    "score": 8.1,
                    "temperature_range": {"min": 18.0, "max": 28.0},
                    "characteristics": {"warmth": 2.5, "breathability": 4.0},
                }
            ],
            "explanation": "Giải thích theo quy tắc.",
        }
    ]
}
THREE_RESULT = {
    "outfits": [
        {
            "id": index,
            "name": names[index - 1],
            "score": scores[index - 1],
            "score_low": scores[index - 1] - 0.5,
            "score_high": scores[index - 1] + 0.5,
            "confidence_level": "Cao",
            "temp_score": 90,
            "activity_score": 80,
            "style_score": 70,
            "match_score": 82,
            "items": [
                {
                    "name": item_names[index - 1],
                    "score": scores[index - 1],
                    "temperature_range": {"min": 18, "max": 30},
                    "characteristics": {
                        "warmth": 2.5,
                        "breathability": 4,
                        "mobility": 4,
                        "formality": 3.5,
                    },
                }
            ],
            "explanation": f"Lời giải thích quy tắc số {index}.",
        }
        for index in range(1, 4)
        for names in [["Casual – Đi học #1", "Casual – Đi học #2", "Casual – Đi học #3"]]
        for scores in [[8.1, 7.8, 7.5]]
        for item_names in [["Áo sơ mi trắng", "Áo len mỏng", "Áo khoác dáng ngắn"]]
    ]
}


def _structured_payload():
    return {
        "explanations": [
            {
                "rank": 1,
                "headline": "Phương án sáng gọn",
                "why_suitable": "Áo sơ mi trắng dành cho Đi học, điểm model 8.1/10; độ thoáng khí có mức 4/5.",
                "weather_fit": "Đi học ở 22°C nằm trong khoảng nhiệt của món áo.",
                "caution": "Độ tin cậy của bộ này là Cao.",
                "tip": "Có thể phối áo sơ mi trắng theo lựa chọn gọn nhẹ.",
            },
            {
                "rank": 2,
                "headline": "Lựa chọn mềm mại",
                "why_suitable": "Áo len mỏng hợp Đi học; điểm model 7.8/10 và mức vận động là 4/5.",
                "weather_fit": "Ở 22°C, khoảng nhiệt của bộ cho phép lựa chọn này.",
                "caution": "Mức tin cậy hiện tại là Cao.",
                "tip": "Thử lấy áo len mỏng làm món bắt đầu phối.",
            },
            {
                "rank": 3,
                "headline": "Tổ hợp có điểm nhấn",
                "why_suitable": "Áo khoác dáng ngắn phù hợp Đi học; điểm model 7.5/10, độ chỉn chu là 3.5/5.",
                "weather_fit": "Nhiệt độ 22°C nằm trong giới hạn đã dùng để chọn món.",
                "caution": "Kết quả được đánh giá với độ tin cậy Cao.",
                "tip": "Chọn áo khoác dáng ngắn làm điểm khởi đầu của cách phối.",
            },
        ]
    }


def _client_mock(responses):
    client = Mock()
    client.models.generate_content.side_effect = [
        Mock(text=json.dumps(response, ensure_ascii=False)) for response in responses
    ]
    context_client = Mock()
    context_client.__enter__ = Mock(return_value=client)
    context_client.__exit__ = Mock(return_value=False)
    return client, context_client


class LlmExplainTests(unittest.TestCase):
    def setUp(self):
        with llm_explain._cache_lock:
            llm_explain._cache.clear()

    def test_missing_api_key_returns_rules_fallback(self):
        result = json.loads(json.dumps(RESULT))
        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            llm_explain.add_explanations(result, REQUEST)
        self.assertEqual(result["outfits"][0]["explanation_llm"], "Giải thích theo quy tắc.")
        self.assertEqual(result["outfits"][0]["explanation_source"], "rules")
        self.assertIn("chưa cấu hình GEMINI_API_KEY", result["outfits"][0]["explanation_notice"])

    def test_three_structured_explanations_are_validated_and_cached(self):
        result = json.loads(json.dumps(THREE_RESULT))
        client, context_client = _client_mock([_structured_payload()])
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "gemini-test"}),
            patch("api.llm_explain.genai.Client", return_value=context_client) as client_factory,
        ):
            llm_explain.add_explanations(result, REQUEST)
            second = json.loads(json.dumps(THREE_RESULT))
            llm_explain.add_explanations(second, REQUEST)
        self.assertTrue(all(item["explanation_source"] == "gemini" for item in result["outfits"]))
        self.assertTrue(all(item["comment_source"] == "gemini" for item in result["outfits"]))
        self.assertTrue(all(item["explanation_structured"] for item in result["outfits"]))
        self.assertEqual(len({item["explanation_llm"] for item in result["outfits"]}), 3)
        self.assertEqual(client_factory.call_count, 1)
        client.models.generate_content.assert_called_once()
        config = client.models.generate_content.call_args.kwargs["config"]
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertGreaterEqual(
            client_factory.call_args.kwargs["http_options"].timeout, 10_000
        )

    def test_unavailable_model_switches_to_fallback_model(self):
        result = json.loads(json.dumps(THREE_RESULT))
        client = Mock()

        class ModelGone(Exception):
            code = 404

        client.models.generate_content.side_effect = [
            ModelGone("model not found"),
            Mock(text=json.dumps(_structured_payload(), ensure_ascii=False)),
        ]
        context_client = Mock()
        context_client.__enter__ = Mock(return_value=client)
        context_client.__exit__ = Mock(return_value=False)
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key", "GEMINI_MODEL": "model-da-ngung"}),
            patch("api.llm_explain.genai.Client", return_value=context_client),
        ):
            llm_explain.add_explanations(result, REQUEST)
        used = [call.kwargs["model"] for call in client.models.generate_content.call_args_list]
        self.assertEqual(used[0], "model-da-ngung")
        self.assertEqual(used[1], llm_explain.FALLBACK_MODELS[0])
        self.assertTrue(all(item["explanation_source"] == "gemini" for item in result["outfits"]))

    def test_rounded_score_is_accepted_but_invented_number_is_rejected(self):
        result = json.loads(json.dumps(THREE_RESULT))
        result["outfits"][0]["score"] = 8.1234
        payload = _structured_payload()
        payload["explanations"][0]["why_suitable"] = (
            "Áo sơ mi trắng dành cho Đi học, điểm model 8.12/10; độ thoáng khí có mức 4/5."
        )
        llm_explain._validate_generated(
            {int(entry["rank"]): entry for entry in payload["explanations"]},
            REQUEST,
            result["outfits"],
        )
        payload["explanations"][0]["why_suitable"] += " Giảm giá 37%."
        with self.assertRaises(ValueError):
            llm_explain._validate_generated(
                {int(entry["rank"]): entry for entry in payload["explanations"]},
                REQUEST,
                result["outfits"],
            )

    def test_invalid_output_is_retried_once_then_falls_back(self):
        result = json.loads(json.dumps(THREE_RESULT))
        duplicate = _structured_payload()
        duplicate_entry = duplicate["explanations"][0].copy()
        duplicate_entry["rank"] = 2
        duplicate_entry["why_suitable"] = duplicate_entry["why_suitable"].replace(
            "Áo sơ mi trắng", "Áo len mỏng"
        ).replace("8.1", "7.8")
        duplicate_entry["tip"] = duplicate_entry["tip"].replace(
            "Áo sơ mi trắng", "Áo len mỏng"
        )
        duplicate["explanations"][1] = duplicate_entry
        client, context_client = _client_mock([duplicate, duplicate])
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch("api.llm_explain.genai.Client", return_value=context_client),
        ):
            llm_explain.add_explanations(result, REQUEST)
        self.assertEqual(client.models.generate_content.call_count, 2)
        self.assertTrue(all(item["explanation_source"] == "rules" for item in result["outfits"]))
        self.assertTrue(
            all("kiểm tra dữ kiện" in item["explanation_notice"] for item in result["outfits"])
        )

    def test_gemini_service_error_or_quota_uses_fallback_without_leaking_error(self):
        for error in (RuntimeError("service unavailable"), RuntimeError("quota exhausted")):
            result = json.loads(json.dumps(THREE_RESULT))
            context_client = Mock()
            context_client.__enter__ = Mock(side_effect=error)
            context_client.__exit__ = Mock(return_value=False)
            with (
                patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
                patch("api.llm_explain.genai.Client", return_value=context_client),
            ):
                llm_explain.add_explanations(result, REQUEST)
            self.assertTrue(all(item["explanation_source"] == "rules" for item in result["outfits"]))
            self.assertTrue(all(item["explanation_llm"] for item in result["outfits"]))
            self.assertEqual(
                len({item["explanation_llm"] for item in result["outfits"]}), 3
            )
            self.assertTrue(
                all(
                    "điểm model" in item["explanation_structured"]["why_suitable"].casefold()
                    and "xếp hạng" in item["explanation_structured"]["why_suitable"].casefold()
                    and "nhiệt độ" in item["explanation_structured"]["weather_fit"].casefold()
                    and "Khoảng điểm model" in item["explanation_structured"]["caution"]
                    for item in result["outfits"]
                )
            )

    def test_malformed_json_falls_back(self):
        result = json.loads(json.dumps(THREE_RESULT))
        client, context_client = _client_mock([{}])
        client.models.generate_content.side_effect = [Mock(text="{bad json"), Mock(text="{still bad")]
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-key"}),
            patch("api.llm_explain.genai.Client", return_value=context_client),
        ):
            llm_explain.add_explanations(result, REQUEST)
        self.assertEqual(client.models.generate_content.call_count, 2)
        self.assertTrue(all(item["explanation_source"] == "rules" for item in result["outfits"]))


if __name__ == "__main__":
    unittest.main()
