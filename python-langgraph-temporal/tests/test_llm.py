import unittest
from unittest.mock import patch

import config
from activities.llm import _chat_model


class ChatModelTests(unittest.TestCase):
    def test_openai_uses_responses_api(self) -> None:
        model = object()

        with (
            patch.object(config, "LLM_PROVIDER", "openai"),
            patch.object(config, "OPENAI_MODEL", "gpt-5.6-sol"),
            patch("activities.llm.ChatOpenAI", return_value=model) as chat_openai,
        ):
            result = _chat_model()

        self.assertIs(result, model)
        chat_openai.assert_called_once_with(
            model="gpt-5.6-sol",
            use_responses_api=True,
            max_retries=0,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
