"""
Adapter for Anthropic Message Batches API.

Wraps client.beta.messages.batches.* for batch processing at 50% discount.
Used during off-hours/sleep mode for non-urgent daemon-generated drafts.
"""

import os
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BatchRequest:
    """A single request to include in a batch."""

    __slots__ = ("custom_id", "model", "system_prompt", "user_prompt",
                 "max_tokens", "temperature")

    def __init__(
        self,
        custom_id: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 512,
        temperature: float = 0.5,
    ):
        self.custom_id = custom_id
        self.model = model
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        self.max_tokens = max_tokens
        self.temperature = temperature


class BatchResult:
    """Result from a completed batch request."""

    __slots__ = ("custom_id", "status", "content", "input_tokens",
                 "output_tokens", "error")

    def __init__(
        self,
        custom_id: str,
        status: str,
        content: str = "",
        input_tokens: int = 0,
        output_tokens: int = 0,
        error: str = "",
    ):
        self.custom_id = custom_id
        self.status = status  # succeeded / errored / canceled / expired
        self.content = content
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.error = error


class ClaudeBatchAdapter:
    """Thin wrapper around Anthropic Message Batches API."""

    def __init__(self, api_key: str = None):
        import anthropic
        # Audit HIGH-6 (2026-04-25): explicit 60 s timeout (cf. claude_adapter).
        self._client = anthropic.Anthropic(
            api_key=api_key or os.getenv("ANTHROPIC_API_KEY"),
            timeout=60.0,
        )

    def submit_batch(self, requests: list[BatchRequest]) -> Optional[str]:
        """
        Submit a batch of requests to the Anthropic API.

        Args:
            requests: List of BatchRequest objects.

        Returns:
            Batch ID string, or None on failure.
        """
        if not requests:
            return None

        try:
            from anthropic.types.message_create_params import MessageCreateParamsNonStreaming
            from anthropic.types.beta.messages.batch_create_params import Request

            api_requests = []
            for req in requests:
                # Use cache_control on system prompt for stacked discounts
                system_block = [
                    {
                        "type": "text",
                        "text": req.system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]

                params = MessageCreateParamsNonStreaming(
                    model=req.model,
                    max_tokens=req.max_tokens,
                    system=system_block,
                    messages=[{"role": "user", "content": req.user_prompt}],
                    temperature=req.temperature,
                )

                api_requests.append(Request(
                    custom_id=req.custom_id,
                    params=params,
                ))

            batch = self._client.beta.messages.batches.create(requests=api_requests)
            logger.info(
                f"Batch submitted: {batch.id} ({len(requests)} requests)"
            )
            return batch.id

        except Exception as e:
            logger.error(f"Batch submission failed: {e}", exc_info=True)
            return None

    def get_batch_status(self, batch_id: str) -> Optional[dict]:
        """
        Poll batch status.

        Returns:
            Dict with 'status', 'succeeded', 'errored', 'processing',
            'expired', 'canceled' counts, or None on failure.
        """
        try:
            batch = self._client.beta.messages.batches.retrieve(batch_id)
            return {
                "status": batch.processing_status,
                "succeeded": batch.request_counts.succeeded,
                "errored": batch.request_counts.errored,
                "processing": batch.request_counts.processing,
                "expired": batch.request_counts.expired,
                "canceled": batch.request_counts.canceled,
                "ended_at": batch.ended_at,
            }
        except Exception as e:
            logger.error(f"Batch status check failed for {batch_id}: {e}")
            return None

    def get_batch_results(self, batch_id: str) -> list[BatchResult]:
        """
        Retrieve results from a completed batch.

        Returns:
            List of BatchResult objects.
        """
        results = []
        try:
            for result in self._client.beta.messages.batches.results(batch_id):
                custom_id = result.custom_id

                if result.result.type == "succeeded":
                    msg = result.result.message
                    content = ""
                    if msg.content and hasattr(msg.content[0], "text"):
                        content = msg.content[0].text

                    results.append(BatchResult(
                        custom_id=custom_id,
                        status="succeeded",
                        content=content,
                        input_tokens=msg.usage.input_tokens if msg.usage else 0,
                        output_tokens=msg.usage.output_tokens if msg.usage else 0,
                    ))

                elif result.result.type == "errored":
                    error_msg = str(result.result.error) if result.result.error else "Unknown error"
                    results.append(BatchResult(
                        custom_id=custom_id,
                        status="errored",
                        error=error_msg,
                    ))

                elif result.result.type == "expired":
                    results.append(BatchResult(
                        custom_id=custom_id,
                        status="expired",
                        error="Request expired (24h timeout)",
                    ))

                elif result.result.type == "canceled":
                    results.append(BatchResult(
                        custom_id=custom_id,
                        status="canceled",
                    ))

            logger.info(
                f"Batch {batch_id}: {len(results)} results retrieved "
                f"({sum(1 for r in results if r.status == 'succeeded')} succeeded)"
            )

        except Exception as e:
            logger.error(f"Batch result retrieval failed for {batch_id}: {e}", exc_info=True)

        return results

    def cancel_batch(self, batch_id: str) -> bool:
        """Cancel an in-progress batch."""
        try:
            self._client.beta.messages.batches.cancel(batch_id)
            logger.info(f"Batch {batch_id} canceled")
            return True
        except Exception as e:
            logger.warning(f"Batch cancel failed for {batch_id}: {e}")
            return False
