"""One small interface over DeepSeek, Anthropic and OpenAI.

Every provider exposes `complete_json(system, user, schema_name, schema)` and returns
`(raw_text, usage)`. Transient failures are retried with backoff here; everything else
is raised as CoachError with a readable message.
"""
import os
import random
import time
from dataclasses import dataclass

from coach.config import load_config


class CoachError(Exception):
    """An error the UI can show to the user as-is."""


class EmptyOrTruncated(Exception):
    """The model returned no usable content; the caller may retry with feedback."""


TRANSIENT_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


def _readable_status_error(provider: str, status: int, message: str) -> str:
    if status in (401, 403):
        return (f"{provider} rejected the API key (HTTP {status}). Check the key in your .env file.")
    if status == 402:
        return f"{provider} says the account balance is insufficient (HTTP 402). Top up the account and try again."
    if status == 404:
        return f"{provider} could not find the model (HTTP 404). Check the model name in config.yaml. Details: {message}"
    if status in (400, 422):
        return f"{provider} rejected the request as invalid (HTTP {status}). Details: {message}"
    return f"{provider} returned HTTP {status}. Details: {message}"


@dataclass
class Provider:
    name: str
    model: str
    max_tokens: int
    timeout: float
    retries: int
    backoff: float

    def complete_json(self, system: str, user: str, schema_name: str, schema: dict) -> tuple[str, Usage]:
        attempt = 0
        while True:
            try:
                return self._call(system, user, schema_name, schema)
            except Exception as exc:  # noqa: BLE001 - classified below
                status = self._status_of(exc)
                transient = self._is_transient(exc, status)
                if transient and attempt < self.retries:
                    delay = self.backoff * (2 ** attempt) + random.uniform(0, 1)
                    time.sleep(delay)
                    attempt += 1
                    continue
                if isinstance(exc, EmptyOrTruncated):
                    raise
                if transient:
                    raise CoachError(
                        f"{self.name} is not responding right now (gave up after {attempt + 1} tries). "
                        f"Please try again in a minute. Details: {exc}"
                    ) from exc
                if status is not None:
                    raise CoachError(_readable_status_error(self.name, status, str(exc))) from exc
                raise CoachError(f"Unexpected error from {self.name}: {exc}") from exc

    # Subclasses implement these.
    def _call(self, system, user, schema_name, schema):  # pragma: no cover
        raise NotImplementedError

    def _status_of(self, exc) -> int | None:
        return getattr(exc, "status_code", None)

    def _is_transient(self, exc, status) -> bool:
        if status in TRANSIENT_STATUS:
            return True
        return type(exc).__name__ in {"APIConnectionError", "APITimeoutError"}


class DeepSeekProvider(Provider):
    """DeepSeek via its OpenAI-compatible API, JSON mode, thinking disabled (chat behaviour)."""

    def __init__(self, cfg, req, api_key):
        super().__init__("DeepSeek", cfg["model"], cfg["max_tokens"], req["timeout_seconds"],
                         req["transient_retries"], req["backoff_base_seconds"])
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, base_url=cfg["base_url"], timeout=self.timeout, max_retries=0)

    def _call(self, system, user, schema_name, schema):
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            max_tokens=self.max_tokens,
            extra_body={"thinking": {"type": "disabled"}},
        )
        choice = resp.choices[0]
        text = (choice.message.content or "").strip()
        if choice.finish_reason == "length":
            raise EmptyOrTruncated("the reply was cut off at max_tokens before the JSON was complete")
        if not text:
            raise EmptyOrTruncated("the reply was empty")
        u = resp.usage
        return text, Usage(getattr(u, "prompt_tokens", 0) or 0, getattr(u, "completion_tokens", 0) or 0)


class AnthropicProvider(Provider):
    """Claude Messages API with schema-enforced structured output (output_config.format)."""

    def __init__(self, cfg, req, api_key):
        super().__init__("Anthropic", cfg["model"], cfg["max_tokens"], req["timeout_seconds"],
                         req["transient_retries"], req["backoff_base_seconds"])
        import anthropic
        self.client = anthropic.Anthropic(api_key=api_key, timeout=self.timeout, max_retries=0)

    def _call(self, system, user, schema_name, schema):
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        if resp.stop_reason == "max_tokens":
            raise EmptyOrTruncated("the reply was cut off at max_tokens before the JSON was complete")
        if resp.stop_reason == "refusal":
            raise CoachError("Claude declined this request. Try rewording your prompt.")
        text = "".join(b.text for b in resp.content if b.type == "text").strip()
        if not text:
            raise EmptyOrTruncated("the reply was empty")
        return text, Usage(resp.usage.input_tokens, resp.usage.output_tokens)


class OpenAIProvider(Provider):
    """OpenAI Responses API with strict JSON Schema structured output."""

    def __init__(self, cfg, req, api_key):
        super().__init__("OpenAI", cfg["model"], cfg["max_tokens"], req["timeout_seconds"],
                         req["transient_retries"], req["backoff_base_seconds"])
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key, timeout=self.timeout, max_retries=0)

    def _call(self, system, user, schema_name, schema):
        resp = self.client.responses.create(
            model=self.model,
            instructions=system,
            input=user,
            max_output_tokens=self.max_tokens,
            text={"format": {"type": "json_schema", "name": schema_name, "strict": True, "schema": schema}},
        )
        if resp.status == "incomplete":
            reason = getattr(resp.incomplete_details, "reason", "unknown")
            raise EmptyOrTruncated(f"the reply was incomplete ({reason})")
        for item in resp.output:
            if item.type == "message":
                for part in item.content:
                    if part.type == "refusal":
                        raise CoachError(f"OpenAI declined this request: {part.refusal}")
        text = (resp.output_text or "").strip()
        if not text:
            raise EmptyOrTruncated("the reply was empty")
        return text, Usage(resp.usage.input_tokens, resp.usage.output_tokens)


_CLASSES = {"deepseek": DeepSeekProvider, "anthropic": AnthropicProvider, "openai": OpenAIProvider}


def get_provider(name: str) -> Provider:
    config = load_config()
    if name not in _CLASSES:
        raise CoachError(f"Unknown PROVIDER '{name}'. Use one of: {', '.join(_CLASSES)}.")
    cfg = config["providers"][name]
    api_key = os.getenv(cfg["api_key_env"], "").strip()
    if not api_key:
        raise CoachError(f"No API key found. Add {cfg['api_key_env']}=... to your .env file (see .env.example).")
    return _CLASSES[name](cfg, config["request"], api_key)
