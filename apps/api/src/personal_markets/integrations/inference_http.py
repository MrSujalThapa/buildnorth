"""Native protocol adapters; exactly one HTTP attempt, no credentials in returned objects.

Retries, authentication scope and billing belong to InferenceRouter. SDK implicit
retries are deliberately avoided. HTTP errors never include upstream bodies.
"""

from __future__ import annotations

import copy
import json
import time
from typing import Any, Literal

import httpx
from jsonschema import Draft202012Validator, ValidationError

from personal_markets.core.errors import (
    InferenceOutputError,
    PermanentProviderError,
    ProviderAuthenticationError,
    ProviderRateLimitedError,
    SemanticProviderError,
    TransientProviderError,
)
from personal_markets.integrations.inference_catalog import resolve_capability
from personal_markets.ports import InferenceRequest, InferenceResponse, ToolCall

CompletionKind = Literal["structured", "text", "tools"]
BASE_URLS = {
    "openai": "https://api.openai.com/v1/",
    "anthropic": "https://api.anthropic.com/v1/",
    "spur": "https://ai.spuric.com/v1/",
}


def provider_error(provider: str, status: int) -> Exception:
    if status in {401, 403}:
        return ProviderAuthenticationError(
            f"{provider} authentication failed. Replace or validate your key."
        )
    if status == 429:
        return ProviderRateLimitedError(
            f"{provider} quota or rate limit reached. Check provider billing."
        )
    if status >= 500 or status in {408, 409}:
        return TransientProviderError(f"{provider} is temporarily unavailable. Retry later.")
    return PermanentProviderError(
        f"{provider} rejected the request. Check model access and settings."
    )


class NativeInferenceAdapter:
    def __init__(
        self,
        provider: str,
        api_key: str,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        spur_base_url: str | None = None,
    ) -> None:
        self.provider = provider
        self._key = api_key
        self._transport = transport
        self._base = spur_base_url or BASE_URLS[provider]
        # Operator-only Spur URL must remain its official origin; users cannot set endpoints.
        if provider == "spur" and self._base.rstrip("/") != BASE_URLS[provider].rstrip("/"):
            raise SemanticProviderError("Unsupported Spur API origin")

    def _headers(self) -> dict[str, str]:
        if self.provider == "anthropic":
            return {"x-api-key": self._key, "anthropic-version": "2023-06-01"}
        return {"Authorization": f"Bearer {self._key}"}

    async def validate_key(self) -> None:
        # Non-generating authenticated request. Does not assert access to every model.
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=10, follow_redirects=False
            ) as client:
                response = await client.get(
                    self._base.rstrip("/") + "/models",
                    headers=self._headers(),
                    params={"limit": 1} if self.provider == "anthropic" else None,
                )
        except httpx.HTTPError:
            raise TransientProviderError(
                "Provider validation timed out or could not connect"
            ) from None
        if response.status_code != 200:
            raise provider_error(self.provider, response.status_code) from None

    async def list_models(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=15, follow_redirects=False
            ) as client:
                response = await client.get(
                    self._base.rstrip("/") + "/models",
                    headers=self._headers(),
                    params={"limit": 100} if self.provider == "anthropic" else None,
                )
        except httpx.HTTPError:
            raise TransientProviderError(
                "Provider model listing timed out or could not connect"
            ) from None
        if response.status_code in {401, 403}:
            raise provider_error(self.provider, response.status_code) from None
        if response.status_code != 200:
            raise provider_error(self.provider, response.status_code) from None
        try:
            payload = response.json()
        except ValueError:
            raise SemanticProviderError("Provider returned a malformed model list") from None
        if not isinstance(payload, (dict, list)):
            raise SemanticProviderError("Provider model list must be an object or array")
        return payload if isinstance(payload, dict) else {"data": payload}

    async def complete_structured(self, request: InferenceRequest) -> InferenceResponse:
        return await self.complete(request, "structured")

    async def complete_text(self, request: InferenceRequest) -> InferenceResponse:
        return await self.complete(request, "text")

    async def complete_tools(self, request: InferenceRequest) -> InferenceResponse:
        return await self.complete(request, "tools")

    async def complete(self, request: InferenceRequest, kind: CompletionKind) -> InferenceResponse:
        model = request.model or ""
        cap = resolve_capability(self.provider, model)
        if kind == "structured" and not cap.structured:
            raise SemanticProviderError(
                "Selected model does not support structured forecasting output"
            )
        if kind == "tools" and (not cap.tools or not request.tools):
            raise SemanticProviderError("Tool calling is unavailable for this model/request")
        limit = max(request.max_output_tokens or 1200, cap.minimum_output_tokens)
        serialized = json.dumps(request.input, sort_keys=True, default=str)
        path, body = self._payload(request, kind, serialized, limit)
        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=request.timeout_seconds or 45,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    self._base.rstrip("/") + "/" + path, headers=self._headers(), json=body
                )
        except httpx.HTTPError:
            raise TransientProviderError(
                f"{self.provider} timed out or could not connect"
            ) from None
        if response.status_code != 200:
            raise provider_error(self.provider, response.status_code) from None
        try:
            data = response.json()
        except ValueError:
            raise SemanticProviderError("Provider returned a malformed response") from None
        if not isinstance(data, dict):
            raise SemanticProviderError("Provider response must be an object")
        try:
            result = self._decode(data, request, kind)
        except (
            KeyError,
            IndexError,
            TypeError,
            ValueError,
            OverflowError,
            ValidationError,
            SemanticProviderError,
        ) as error:
            reason = "Provider returned malformed or schema-invalid output"
            if isinstance(error, ValidationError):
                path = "/".join(str(part) for part in error.absolute_path) or "root"
                reason = f"Provider output failed schema validation at {path} ({error.validator})"
                if error.validator == "additionalProperties" and isinstance(error.instance, dict):
                    allowed = set((error.schema or {}).get("properties") or {})
                    unexpected = sorted(str(key) for key in error.instance if key not in allowed)
                    reason += f": unexpected {', '.join(unexpected)[:200]}"
            elif isinstance(error, SemanticProviderError):
                reason = str(error)
            raw_usage = data.get("usage")
            usage = raw_usage if isinstance(raw_usage, dict) else {}
            input_key = "prompt_tokens" if self.provider == "spur" else "input_tokens"
            output_key = "completion_tokens" if self.provider == "spur" else "output_tokens"
            tokens = _reported_usage(usage, input_key, output_key)
            raise InferenceOutputError(reason, tokens, self.provider, request.model or "") from None
        result.latency_ms = int((time.perf_counter() - started) * 1000)
        result.estimated_cost_usd = cap.estimate(
            result.usage.get("input_tokens", 0), result.usage.get("output_tokens", 0)
        )
        if not result.usage_reported:
            result.estimated_cost_usd = None
        return result

    def _payload(
        self, request: InferenceRequest, kind: CompletionKind, content: str, limit: int
    ) -> tuple[str, dict[str, Any]]:
        schema = request.output_schema
        if self.provider == "openai":
            body: dict[str, Any] = {
                "model": request.model,
                "instructions": request.instructions,
                "input": content,
                "max_output_tokens": limit,
                "store": False,
                "reasoning": {"effort": "low"},
            }
            if kind == "structured":
                body["text"] = {
                    "format": {
                        "type": "json_schema",
                        "name": "agent_output",
                        "strict": True,
                        "schema": schema,
                    }
                }
            if kind == "tools":
                body["tools"] = [
                    {
                        "type": "function",
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                        "strict": True,
                    }
                    for t in request.tools
                ]
            return "responses", body
        if self.provider == "anthropic":
            body = {
                "model": request.model,
                "system": request.instructions,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": limit,
            }
            if kind == "structured":
                body["output_config"] = {
                    "format": {"type": "json_schema", "schema": anthropic_schema(schema)}
                }
            if kind == "tools":
                body["tools"] = [
                    {
                        "name": t.name,
                        "description": t.description,
                        "input_schema": anthropic_schema(t.input_schema),
                        "strict": True,
                    }
                    for t in request.tools
                ]
            return "messages", body
        instructions = request.instructions
        if kind == "structured":
            instructions += (
                "\nReturn only one JSON object matching this schema. "
                "Include every required property, including nullable/defaulted properties. "
                "Use null, false or empty arrays where appropriate. Never omit a required key.\n"
                "JSON schema:\n"
            ) + json.dumps(schema)
        body = {
            "model": request.model,
            "messages": [
                {"role": "system", "content": instructions},
                {"role": "user", "content": content},
            ],
            "max_tokens": limit,
            "thinking": {"type": "enabled"},
            "reasoning_effort": "low",
        }
        if kind == "structured":
            body["response_format"] = {"type": "json_object"}
        return "chat/completions", body

    def _decode(
        self, data: dict[str, Any], request: InferenceRequest, kind: CompletionKind
    ) -> InferenceResponse:
        raw_usage = data.get("usage")
        usage = raw_usage if isinstance(raw_usage, dict) else {}
        calls: list[ToolCall] = []
        if self.provider == "spur":
            choice = data["choices"][0]
            text_content = choice["message"].get("content") or ""
            tokens = {
                "input_tokens": int(usage.get("prompt_tokens", 0)),
                "output_tokens": int(usage.get("completion_tokens", 0)),
            }
            details = usage.get("completion_tokens_details")
            if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
                tokens["reasoning_tokens"] = details["reasoning_tokens"]
            truncated = choice.get("finish_reason") == "length"
        elif self.provider == "anthropic":
            blocks = data.get("content") or []
            text_content = "".join(b["text"] for b in blocks if b.get("type") == "text")
            calls = [
                ToolCall(id=b["id"], name=b["name"], arguments=b["input"])
                for b in blocks
                if b.get("type") == "tool_use"
            ]
            tokens = {
                "input_tokens": int(usage.get("input_tokens", 0)),
                "output_tokens": int(usage.get("output_tokens", 0)),
            }
            truncated = data.get("stop_reason") in {"max_tokens", "refusal"}
        else:
            blocks = data.get("output") or []
            text_content = "".join(
                c["text"]
                for b in blocks
                if b.get("type") == "message"
                for c in b.get("content", [])
                if c.get("type") == "output_text"
            )
            calls = [
                ToolCall(id=b["call_id"], name=b["name"], arguments=json.loads(b["arguments"]))
                for b in blocks
                if b.get("type") == "function_call"
            ]
            tokens = {
                "input_tokens": int(usage.get("input_tokens", 0)),
                "output_tokens": int(usage.get("output_tokens", 0)),
            }
            details = usage.get("output_tokens_details")
            if isinstance(details, dict) and isinstance(details.get("reasoning_tokens"), int):
                tokens["reasoning_tokens"] = details["reasoning_tokens"]
            truncated = data.get("status") in {"incomplete", "failed"}
        if truncated or (not text_content and not calls):
            raise SemanticProviderError(
                "Provider returned empty, refused or truncated output; check token limit"
            )
        output: dict[str, Any] = {}
        if kind == "structured":
            output = json.loads(text_content)
            if not isinstance(output, dict):
                raise ValueError
            if self.provider == "spur":
                output = _drop_undeclared_keys(output, request.output_schema)
            Draft202012Validator(request.output_schema).validate(output)
        if kind == "tools":
            tools = {tool.name: tool for tool in request.tools}
            for call in calls:
                if call.name not in tools:
                    raise ValueError
                Draft202012Validator(tools[call.name].input_schema).validate(call.arguments)
        return InferenceResponse(
            structured_output=output,
            provider=self.provider,
            model=request.model or "",
            usage=tokens,
            text=text_content,
            tool_calls=calls,
            request_id=data.get("id"),
            usage_reported=_reported_usage(
                usage,
                "prompt_tokens" if self.provider == "spur" else "input_tokens",
                "completion_tokens" if self.provider == "spur" else "output_tokens",
            )
            is not None,
        )


def _drop_undeclared_keys(value: Any, schema: dict[str, Any]) -> Any:
    """JSON mode does not enforce additionalProperties:false; drop extra keys recursively.

    Declared fields are left in place so type/required validation still applies.
    """
    if not isinstance(schema, dict):
        return value
    if isinstance(value, dict) and isinstance(schema.get("properties"), dict):
        declared = schema["properties"]
        if schema.get("additionalProperties") is False:
            value = {key: item for key, item in value.items() if key in declared}
        return {
            key: _drop_undeclared_keys(item, declared.get(key) or {}) for key, item in value.items()
        }
    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        return [_drop_undeclared_keys(item, schema["items"]) for item in value]
    return value


def _reported_usage(
    usage: dict[str, Any], input_key: str, output_key: str
) -> dict[str, int] | None:
    a, b = usage.get(input_key), usage.get(output_key)
    if (
        isinstance(a, int)
        and not isinstance(a, bool)
        and a >= 0
        and isinstance(b, int)
        and not isinstance(b, bool)
        and b >= 0
    ):
        return {"input_tokens": a, "output_tokens": b}
    return None


def anthropic_schema(original: dict[str, Any]) -> dict[str, Any]:
    """Transform Anthropic's documented grammar subset; validate original locally."""
    schema = copy.deepcopy(original)
    unsupported = {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "maxItems",
        "uniqueItems",
    }
    formats = {
        "date-time",
        "time",
        "date",
        "duration",
        "email",
        "hostname",
        "uri",
        "ipv4",
        "ipv6",
        "uuid",
    }

    def walk(node: dict[str, Any]) -> None:
        constraints = {key: node.pop(key) for key in unsupported if key in node}
        if node.get("minItems", 0) not in {0, 1}:
            constraints["minItems"] = node.pop("minItems")
        if "format" in node and node["format"] not in formats:
            constraints["format"] = node.pop("format")
        if constraints:
            node["description"] = (
                str(node.get("description") or "") + " Constraints: " + json.dumps(constraints)
            )
        for key in ("properties", "$defs", "definitions"):
            for child in node.get(key, {}).values():
                if isinstance(child, dict):
                    walk(child)
        if isinstance(node.get("items"), dict):
            walk(node["items"])
        for key in ("anyOf", "oneOf", "allOf"):
            for child in node.get(key, []):
                if isinstance(child, dict):
                    walk(child)

    walk(schema)
    return schema
