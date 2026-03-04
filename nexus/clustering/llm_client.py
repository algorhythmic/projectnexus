"""Async Anthropic Claude client for topic clustering."""

import asyncio
from dataclasses import dataclass, field

import anthropic

from nexus.core.config import Settings
from nexus.core.logging import LoggerMixin


@dataclass
class ClaudeResponse:
    """Structured response from a Claude API call."""

    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float


class ClaudeClient(LoggerMixin):
    """Async Anthropic Claude client with retry and cost tracking."""

    # Sonnet pricing per 1M tokens
    _INPUT_COST_PER_M = 3.0
    _OUTPUT_COST_PER_M = 15.0

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY is required for clustering. "
                "Set it in .env or as an environment variable."
            )
        self._settings = settings
        self._client = anthropic.AsyncAnthropic(
            api_key=settings.anthropic_api_key
        )
        self._total_cost: float = 0.0
        self._total_requests: int = 0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0

    async def complete(self, system: str, user: str) -> ClaudeResponse:
        """Send a prompt to Claude and return structured response.

        Retries on rate limit and server errors with exponential backoff.
        Raises immediately on authentication errors.
        """
        max_retries = 3
        delay = 1.0

        for attempt in range(max_retries + 1):
            try:
                response = await self._client.messages.create(
                    model=self._settings.clustering_model,
                    max_tokens=self._settings.clustering_max_tokens,
                    temperature=self._settings.clustering_temperature,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )

                content = response.content[0].text
                input_tokens = response.usage.input_tokens
                output_tokens = response.usage.output_tokens
                cost = self._estimate_cost(input_tokens, output_tokens)

                self._total_cost += cost
                self._total_requests += 1
                self._total_input_tokens += input_tokens
                self._total_output_tokens += output_tokens

                self.logger.info(
                    "llm_call_complete",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=round(cost, 4),
                )

                return ClaudeResponse(
                    content=content,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost_usd=cost,
                )

            except anthropic.AuthenticationError:
                raise
            except (anthropic.RateLimitError, anthropic.InternalServerError) as e:
                if attempt == max_retries:
                    raise
                self.logger.warning(
                    "llm_retry",
                    attempt=attempt + 1,
                    delay=delay,
                    error=str(e),
                )
                await asyncio.sleep(delay)
                delay *= 2

    def get_cost_summary(self) -> dict:
        """Return cumulative cost tracking data."""
        return {
            "total_cost_usd": round(self._total_cost, 4),
            "total_requests": self._total_requests,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
        }

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens / 1_000_000 * self._INPUT_COST_PER_M
            + output_tokens / 1_000_000 * self._OUTPUT_COST_PER_M
        )

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.close()
