"""LLMGatewayClient：复用 webdev-eval-agent 的 ErnieProvider 模式，支持重试和降级。"""
from __future__ import annotations

import json
import re
import time
from typing import Any, Optional

from ..config import (
    PROVIDER, ERNIE_ENDPOINT, ERNIE_TOKEN, ERNIE_MODEL,
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL,
    OPENAI_API_KEY, OPENAI_MODEL,
    LLM_TIMEOUT_SECONDS, LLM_MAX_RETRIES,
)

_MOCK_SUMMARY = (
    "【Mock模式】这是一条由 Mock 提供者生成的测试归因总结。"
    "该维度存在一定比例的评分偏差，建议核查 Rubric 边界定义是否清晰，"
    "并检查 Judge 模型在边界分值（0分/2分）的一致性。"
)


def _extract_json(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


class LLMGatewayClient:
    """
    统一 LLM 调用入口，优先 ERNIE → Anthropic → OpenAI → 无。
    judge_model='mock' 时跳过真实调用，直接返回固定测试数据。
    调用失败时重试；全部失败返回 None，调用方负责降级处理。
    API Key 不会出现在日志或返回值中。
    """

    def __init__(self, judge_model: str = ""):
        self.judge_model = judge_model or ""
        self.provider = PROVIDER
        self.available = self._detect_provider()

    def _is_mock(self) -> bool:
        return self.judge_model == "mock"

    def _detect_provider(self) -> Optional[str]:
        if self._is_mock():
            return "mock"
        if ERNIE_ENDPOINT and ERNIE_TOKEN:
            return "ernie"
        if ANTHROPIC_API_KEY and ANTHROPIC_API_KEY.startswith("sk-"):
            return "anthropic"
        if OPENAI_API_KEY and OPENAI_API_KEY.startswith("sk-"):
            return "openai"
        return None

    def chat(self, prompt: str, system: str = "") -> Optional[str]:
        """发送文本 prompt，返回 LLM 回复字符串；失败返回 None。"""
        if self._is_mock():
            return _MOCK_SUMMARY
        if not self.available:
            return None
        for attempt in range(LLM_MAX_RETRIES):
            try:
                return self._call(prompt, system)
            except Exception as e:
                if attempt == LLM_MAX_RETRIES - 1:
                    print(f"[LLM] 调用失败（已重试{LLM_MAX_RETRIES}次）: {type(e).__name__}")
                    return None
                time.sleep(2 ** attempt)
        return None

    def chat_json(self, prompt: str, system: str = "",
                  schema_keys: list[str] = None) -> Optional[dict]:
        """调用 LLM 并期望返回 JSON；失败或格式错误返回 None。"""
        if self._is_mock():
            mock_data = {k: f"mock_{k}" for k in (schema_keys or [])}
            mock_data.setdefault("summary", _MOCK_SUMMARY)
            return mock_data
        text = self.chat(prompt, system)
        if text is None:
            return None
        data = _extract_json(text)
        if data is None:
            return None
        if schema_keys:
            if not all(k in data for k in schema_keys):
                return None
        return data

    def _call(self, prompt: str, system: str) -> str:
        if self.available == "ernie":
            return self._call_ernie(prompt, system)
        if self.available == "anthropic":
            return self._call_anthropic(prompt, system)
        if self.available == "openai":
            return self._call_openai(prompt, system)
        raise RuntimeError("无可用 LLM")

    def _call_ernie(self, prompt: str, system: str) -> str:
        import requests
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": ERNIE_MODEL, "messages": messages, "max_tokens": 800}
        url = ERNIE_ENDPOINT.rstrip("/") + "/chat/completions"
        r = requests.post(url, json=payload,
                          headers={"Authorization": f"Bearer {ERNIE_TOKEN}"},
                          timeout=LLM_TIMEOUT_SECONDS)
        r.raise_for_status()
        data = r.json()
        return (data.get("result") or
                (data.get("choices") or [{}])[0].get("message", {}).get("content", ""))

    def _call_anthropic(self, prompt: str, system: str) -> str:
        from anthropic import Anthropic
        client = Anthropic(api_key=ANTHROPIC_API_KEY)
        kwargs: dict[str, Any] = {"model": ANTHROPIC_MODEL, "max_tokens": 800,
                                   "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        msg = client.messages.create(**kwargs)
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")

    def _call_openai(self, prompt: str, system: str) -> str:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        r = client.chat.completions.create(model=OPENAI_MODEL, max_tokens=800, messages=messages)
        return r.choices[0].message.content or ""
