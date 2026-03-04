"""Tests for the Claude LLM client."""

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.clustering.llm_client import ClaudeClient
from nexus.core.config import Settings


def _test_settings(**overrides) -> Settings:
    defaults = {
        "anthropic_api_key": "test-key-123",
        "clustering_model": "claude-sonnet-4-20250514",
        "clustering_temperature": 0.1,
        "clustering_max_tokens": 4096,
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _mock_response(content: str = "test", input_tokens: int = 100, output_tokens: int = 50):
    """Build a mock Anthropic response object."""
    resp = MagicMock()
    resp.content = [MagicMock(text=content)]
    resp.usage = MagicMock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


class TestClaudeClient:
    def test_missing_api_key_raises(self):
        """Empty API key raises ValueError."""
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            ClaudeClient(_test_settings(anthropic_api_key=""))

    @patch("nexus.clustering.llm_client.anthropic.AsyncAnthropic")
    async def test_complete_success(self, mock_cls):
        """Successful API call returns ClaudeResponse."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response('{"clusters": []}', 200, 100)
        )
        mock_client.close = AsyncMock()
        mock_cls.return_value = mock_client

        client = ClaudeClient(_test_settings())
        response = await client.complete("system", "user")

        assert response.content == '{"clusters": []}'
        assert response.input_tokens == 200
        assert response.output_tokens == 100
        assert response.cost_usd > 0
        await client.close()

    @patch("nexus.clustering.llm_client.anthropic.AsyncAnthropic")
    async def test_cost_tracking(self, mock_cls):
        """Multiple calls accumulate cost."""
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_mock_response("ok", 1000, 500)
        )
        mock_client.close = AsyncMock()
        mock_cls.return_value = mock_client

        client = ClaudeClient(_test_settings())
        await client.complete("s", "u")
        await client.complete("s", "u")

        summary = client.get_cost_summary()
        assert summary["total_requests"] == 2
        assert summary["total_input_tokens"] == 2000
        assert summary["total_output_tokens"] == 1000
        assert summary["total_cost_usd"] > 0
        await client.close()

    @patch("nexus.clustering.llm_client.anthropic.AsyncAnthropic")
    async def test_rate_limit_retry(self, mock_cls):
        """RateLimitError triggers retry then succeeds."""
        import anthropic as anth

        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.headers = {}

        rate_error = anth.RateLimitError(
            message="rate limited",
            response=mock_resp,
            body=None,
        )
        mock_client.messages.create = AsyncMock(
            side_effect=[rate_error, _mock_response("retry ok")]
        )
        mock_client.close = AsyncMock()
        mock_cls.return_value = mock_client

        client = ClaudeClient(_test_settings())
        response = await client.complete("s", "u")
        assert response.content == "retry ok"
        assert mock_client.messages.create.call_count == 2
        await client.close()

    @patch("nexus.clustering.llm_client.anthropic.AsyncAnthropic")
    async def test_auth_error_not_retried(self, mock_cls):
        """AuthenticationError raises immediately, no retry."""
        import anthropic as anth

        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {}

        mock_client.messages.create = AsyncMock(
            side_effect=anth.AuthenticationError(
                message="bad key",
                response=mock_resp,
                body=None,
            )
        )
        mock_client.close = AsyncMock()
        mock_cls.return_value = mock_client

        client = ClaudeClient(_test_settings())
        with pytest.raises(anth.AuthenticationError):
            await client.complete("s", "u")
        assert mock_client.messages.create.call_count == 1
        await client.close()
