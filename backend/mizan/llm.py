"""Thin wrapper over any OpenAI-compatible chat endpoint.

Works with Gemini (OpenAI-compatible endpoint), Groq, OpenAI and a local Ollama
server, so "API model vs local model" is just a config change. Adds retries,
token/cost accounting and robust JSON parsing.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from .config import get_settings

T = TypeVar("T", bound=BaseModel)


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    calls: int = 0
    seconds: float = 0.0

    def add(self, other: "Usage") -> None:
        self.tokens_in += other.tokens_in
        self.tokens_out += other.tokens_out
        self.calls += other.calls
        self.seconds += other.seconds

    def cost(self, price_in: float, price_out: float) -> float:
        return self.tokens_in / 1e6 * price_in + self.tokens_out / 1e6 * price_out


@dataclass
class LLMReply:
    content: str
    tool_calls: list[dict] = field(default_factory=list)   # [{"id","name","arguments"(dict)}]
    usage: Usage = field(default_factory=Usage)
    raw_message: Optional[dict] = None


class LLM:
    def __init__(self, base_url: str | None = None, api_key: str | None = None,
                 model: str | None = None, price_in: float | None = None,
                 price_out: float | None = None) -> None:
        from openai import OpenAI
        s = get_settings()
        self.model = model or s.llm_model
        self.price_in = s.price_in_per_m if price_in is None else price_in
        self.price_out = s.price_out_per_m if price_out is None else price_out
        self.client = OpenAI(base_url=base_url or s.llm_base_url,
                             api_key=api_key or s.llm_api_key or "not-needed",
                             timeout=s.llm_timeout_s, max_retries=s.llm_max_retries)
        self.total = Usage()

    def chat(self, messages: list[dict], tools: list[dict] | None = None,
             temperature: float = 0.0, max_tokens: int = 1500, json_mode: bool = False) -> LLMReply:
        kwargs: dict[str, Any] = dict(model=self.model, messages=messages,
                                      temperature=temperature, max_tokens=max_tokens)
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        t0 = time.perf_counter()
        resp = self.client.chat.completions.create(**kwargs)
        dt = time.perf_counter() - t0
        msg = resp.choices[0].message
        u = Usage(tokens_in=getattr(resp.usage, "prompt_tokens", 0) or 0,
                  tokens_out=getattr(resp.usage, "completion_tokens", 0) or 0,
                  calls=1, seconds=dt)
        self.total.add(u)
        calls = []
        for tc in msg.tool_calls or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc.function.arguments}
            calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})
        raw = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            # Keep every field the provider returned, not just id/name/arguments.
            # Gemini 3.x attaches a "thought signature" (extra_content) to each tool
            # call and rejects the next request with HTTP 400 if it is not sent back.
            raw["tool_calls"] = [tc.model_dump(exclude_none=True) for tc in msg.tool_calls]
            for tc in raw["tool_calls"]:
                tc.setdefault("type", "function")
        return LLMReply(content=msg.content or "", tool_calls=calls, usage=u, raw_message=raw)

    def structured(self, messages: list[dict], schema: Type[T], retries: int = 2,
                   max_tokens: int = 2000) -> tuple[Optional[T], Usage, Optional[str]]:
        """Ask for JSON matching `schema`; validate with Pydantic; on failure send the
        validation error back and retry. Returns (object|None, usage, error)."""
        usage = Usage()
        msgs = list(messages)
        err = None
        for _ in range(retries + 1):
            reply = self.chat(msgs, json_mode=True, max_tokens=max_tokens)
            usage.add(reply.usage)
            try:
                return schema.model_validate(extract_json(reply.content)), usage, None
            except (ValidationError, ValueError) as e:
                err = str(e)[:800]
                msgs = msgs + [{"role": "assistant", "content": reply.content},
                               {"role": "user", "content": f"That JSON was invalid: {err}\n"
                                                           "Return ONLY corrected JSON."}]
        return None, usage, err


def extract_json(text: str) -> Any:
    """Parse JSON even if the model wrapped it in ```json fences or added prose."""
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = min([i for i in (text.find("{"), text.find("[")) if i != -1], default=-1)
        end = max(text.rfind("}"), text.rfind("]"))
        if start == -1 or end <= start:
            raise ValueError("no JSON object found in model output")
        return json.loads(text[start:end + 1])
