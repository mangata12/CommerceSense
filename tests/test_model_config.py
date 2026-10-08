import os
import unittest
from unittest.mock import patch

from model_config import PROVIDERS, resolve_model_settings, create_chat_model, safe_error


class ModelConfigurationTests(unittest.TestCase):
    def test_session_key_precedes_environment_without_process_mutation(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "environment-key"}):
            settings = resolve_model_settings("DeepSeek", "deepseek-chat", "session-key")
            self.assertEqual(settings.api_key, "session-key")
            self.assertEqual(os.environ["DEEPSEEK_API_KEY"], "environment-key")
            self.assertNotIn("session-key", repr(settings))
            self.assertEqual(resolve_model_settings("DeepSeek", "deepseek-chat").api_key, "environment-key")

    def test_missing_configuration_is_checked_at_model_call(self):
        with patch.dict(os.environ, {variable: "" for variable, _ in PROVIDERS.values()}):
            with self.assertRaisesRegex(ValueError, "调用模型前"):
                resolve_model_settings("DeepSeek", "deepseek-chat")
        with self.assertRaisesRegex(ValueError, "模型名称"):
            resolve_model_settings("DeepSeek", "", "session-key")

    def test_actual_provider_constructors_accept_explicit_key_timeout_and_retry(self):
        for provider, (_, name) in PROVIDERS.items():
            with self.subTest(provider=provider):
                model = create_chat_model(resolve_model_settings(provider, name, "test-session-key"))
                self.assertEqual(model.max_retries, 1)
                if provider in {"DeepSeek", "OpenAI"}:
                    self.assertEqual(model.request_timeout, 45)
                    self.assertEqual(model.openai_api_key.get_secret_value(), "test-session-key")
                elif provider == "Google Gemini":
                    self.assertEqual(model.timeout, 45)
                    self.assertEqual(model.google_api_key.get_secret_value(), "test-session-key")
                else:
                    self.assertEqual(model.default_request_timeout, 45)
                    self.assertEqual(model.anthropic_api_key.get_secret_value(), "test-session-key")

    def test_error_redacts_session_and_environment_keys(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "environment-secret"}):
            result = safe_error("session-secret environment-secret Authorization: Bearer token", ("session-secret",))
        self.assertNotIn("session-secret", result)
        self.assertNotIn("environment-secret", result)
        self.assertNotIn("Bearer token", result)


if __name__ == "__main__":
    unittest.main()
