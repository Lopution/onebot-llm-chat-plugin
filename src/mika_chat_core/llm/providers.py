"""Provider adapters for multiple LLM API formats.

This module keeps mika_chat_core internal request format stable (OpenAI-style
messages/tools) and maps it to provider-native wire formats.
"""

from __future__ import annotations

from dataclasses import dataclass
import copy
import json
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse


@dataclass
class ProviderPreparedRequest:
    provider: str
    url: str
    headers: Dict[str, str]
    json_body: Dict[str, Any]
    params: Optional[Dict[str, str]] = None


def detect_provider_name(*, configured_provider: str, base_url: str) -> str:
    value = (configured_provider or "").strip().lower()
    if value in {"openai_compat", "anthropic", "google_genai"}:
        return value
    # Backward compatibility: unknown value falls back to openai compatible mode.
    return "openai_compat"


def is_google_openai_compat_endpoint(base_url: str) -> bool:
    parsed = urlparse(base_url or "")
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    return "generativelanguage.googleapis.com" in host and "/openai" in path


def build_provider_request(
    *,
    provider: str,
    base_url: str,
    model: str,
    api_key: str,
    request_body: Dict[str, Any],
    extra_headers: Optional[Dict[str, str]] = None,
    default_temperature: float,
) -> ProviderPreparedRequest:
    provider_name = detect_provider_name(configured_provider=provider, base_url=base_url)
    if provider_name == "anthropic":
        return _build_anthropic_request(
            base_url=base_url,
            model=model,
            api_key=api_key,
            request_body=request_body,
            extra_headers=extra_headers,
            default_temperature=default_temperature,
        )
    if provider_name == "google_genai":
        return _build_google_genai_request(
            base_url=base_url,
            model=model,
            api_key=api_key,
            request_body=request_body,
            extra_headers=extra_headers,
            default_temperature=default_temperature,
        )
    return _build_openai_compat_request(
        base_url=base_url,
        api_key=api_key,
        request_body=request_body,
        extra_headers=extra_headers,
        default_temperature=default_temperature,
    )


def parse_provider_response(
    *,
    provider: str,
    data: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[List[Dict[str, Any]]], Any, Any]:
    provider_name = detect_provider_name(configured_provider=provider, base_url="")
    if provider_name == "anthropic":
        return _parse_anthropic_response(data)
    if provider_name == "google_genai":
        return _parse_google_genai_response(data)
    return _parse_openai_compat_response(data)


def _normalize_openai_content(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, str):
        text = content.strip()
        return [{"type": "text", "text": text}] if text else []
    if not isinstance(content, list):
        return []
    parts: List[Dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        part_type = str(item.get("type") or "").strip().lower()
        if part_type == "text":
            text = str(item.get("text") or "").strip()
            if text:
                parts.append({"type": "text", "text": text})
            continue
        if part_type == "image_url":
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                url = str(image_url.get("url") or "").strip()
            else:
                url = str(image_url or "").strip()
            if url:
                parts.append({"type": "image_url", "url": url})
    return parts


def _data_url_to_inline_data(url: str) -> Optional[Dict[str, str]]:
    if not str(url or "").startswith("data:"):
        return None
    try:
        header, payload = str(url).split(",", 1)
        mime_type = "image/jpeg"
        if ";" in header and ":" in header:
            mime_type = header.split(":", 1)[1].split(";", 1)[0]
        return {"mime_type": mime_type, "data": payload}
    except Exception:
        return None


def _build_openai_compat_request(
    *,
    base_url: str,
    api_key: str,
    request_body: Dict[str, Any],
    extra_headers: Optional[Dict[str, str]],
    default_temperature: float,
) -> ProviderPreparedRequest:
    body = copy.deepcopy(request_body)
    if "temperature" not in body:
        body["temperature"] = default_temperature

    # Keep Google OpenAI endpoint behavior, but do not leak this field to other providers.
    if is_google_openai_compat_endpoint(base_url):
        body["safetySettings"] = [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
        ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for key, value in (extra_headers or {}).items():
        headers[str(key)] = str(value)

    return ProviderPreparedRequest(
        provider="openai_compat",
        url=f"{base_url.rstrip('/')}/chat/completions",
        headers=headers,
        json_body=body,
        params=None,
    )


def _build_anthropic_request(
    *,
    base_url: str,
    model: str,
    api_key: str,
    request_body: Dict[str, Any],
    extra_headers: Optional[Dict[str, str]],
    default_temperature: float,
) -> ProviderPreparedRequest:
    messages = list(request_body.get("messages") or [])
    system_chunks: List[str] = []
    converted_messages: List[Dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role == "system":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                system_chunks.append(content.strip())
            elif isinstance(content, list):
                for part in _normalize_openai_content(content):
                    if part.get("type") == "text":
                        system_chunks.append(str(part.get("text") or "").strip())
            continue

        if role == "tool":
            tool_name = str(message.get("name") or "tool").strip() or "tool"
            tool_result_content = str(message.get("content") or "")
            tool_use_id = str(message.get("tool_call_id") or "")
            converted_messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use_id,
                            "content": tool_result_content,
                            "is_error": False,
                        }
                    ],
                }
            )
            continue

        converted_role = "assistant" if role == "assistant" else "user"
        blocks: List[Dict[str, Any]] = []

        for part in _normalize_openai_content(message.get("content")):
            if part["type"] == "text":
                blocks.append({"type": "text", "text": part["text"]})
                continue
            inline = _data_url_to_inline_data(part["url"])
            if inline:
                blocks.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": inline["mime_type"],
                            "data": inline["data"],
                        },
                    }
                )
            else:
                blocks.append({"type": "text", "text": f"[image] {part['url']}"})

        if converted_role == "assistant":
            tool_calls = message.get("tool_calls")
            if isinstance(tool_calls, list):
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    function = call.get("function") or {}
                    function_name = str(function.get("name") or "").strip()
                    if not function_name:
                        continue
                    raw_arguments = function.get("arguments")
                    if isinstance(raw_arguments, str):
                        try:
                            arguments = json.loads(raw_arguments)
                        except Exception:
                            arguments = {"input": raw_arguments}
                    elif isinstance(raw_arguments, dict):
                        arguments = raw_arguments
                    else:
                        arguments = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": str(call.get("id") or ""),
                            "name": function_name,
                            "input": arguments,
                        }
                    )

        if blocks:
            converted_messages.append({"role": converted_role, "content": blocks})

    anthropic_tools: List[Dict[str, Any]] = []
    for tool in list(request_body.get("tools") or []):
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") or {}
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        anthropic_tools.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
            }
        )

    body: Dict[str, Any] = {
        "model": model,
        "max_tokens": int(request_body.get("max_tokens") or 1024),
        "temperature": request_body.get("temperature", default_temperature),
        "messages": converted_messages,
    }
    if system_chunks:
        body["system"] = "\n\n".join([chunk for chunk in system_chunks if chunk])
    if anthropic_tools:
        body["tools"] = anthropic_tools

    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    for key, value in (extra_headers or {}).items():
        headers[str(key)] = str(value)

    return ProviderPreparedRequest(
        provider="anthropic",
        url=f"{base_url.rstrip('/')}/messages",
        headers=headers,
        json_body=body,
        params=None,
    )


def _build_google_genai_request(
    *,
    base_url: str,
    model: str,
    api_key: str,
    request_body: Dict[str, Any],
    extra_headers: Optional[Dict[str, str]],
    default_temperature: float,
) -> ProviderPreparedRequest:
    messages = list(request_body.get("messages") or [])
    system_chunks: List[str] = []
    contents: List[Dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "").strip().lower()
        if role == "system":
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                system_chunks.append(content.strip())
            elif isinstance(content, list):
                for part in _normalize_openai_content(content):
                    if part.get("type") == "text":
                        system_chunks.append(str(part.get("text") or "").strip())
            continue

        genai_role = "model" if role == "assistant" else "user"
        parts: List[Dict[str, Any]] = []

        if role == "tool":
            tool_name = str(message.get("name") or "").strip() or "tool"
            parts.append(
                {
                    "functionResponse": {
                        "name": tool_name,
                        "response": {"content": str(message.get("content") or "")},
                    }
                }
            )
        else:
            for part in _normalize_openai_content(message.get("content")):
                if part["type"] == "text":
                    parts.append({"text": part["text"]})
                    continue
                inline = _data_url_to_inline_data(part["url"])
                if inline:
                    parts.append(
                        {
                            "inline_data": {
                                "mime_type": inline["mime_type"],
                                "data": inline["data"],
                            }
                        }
                    )
                else:
                    parts.append({"text": f"[image] {part['url']}"})

            if role == "assistant":
                tool_calls = message.get("tool_calls")
                if isinstance(tool_calls, list):
                    for call in tool_calls:
                        if not isinstance(call, dict):
                            continue
                        function = call.get("function") or {}
                        function_name = str(function.get("name") or "").strip()
                        if not function_name:
                            continue
                        raw_arguments = function.get("arguments")
                        if isinstance(raw_arguments, str):
                            try:
                                arguments = json.loads(raw_arguments)
                            except Exception:
                                arguments = {"input": raw_arguments}
                        elif isinstance(raw_arguments, dict):
                            arguments = raw_arguments
                        else:
                            arguments = {}
                        parts.append(
                            {
                                "functionCall": {
                                    "name": function_name,
                                    "args": arguments,
                                }
                            }
                        )

        if parts:
            contents.append({"role": genai_role, "parts": parts})

    function_declarations: List[Dict[str, Any]] = []
    for tool in list(request_body.get("tools") or []):
        if not isinstance(tool, dict):
            continue
        function = tool.get("function") or {}
        name = str(function.get("name") or "").strip()
        if not name:
            continue
        function_declarations.append(
            {
                "name": name,
                "description": str(function.get("description") or ""),
                "parameters": function.get("parameters") or {"type": "object", "properties": {}},
            }
        )

    body: Dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": request_body.get("temperature", default_temperature),
        },
    }
    if request_body.get("max_tokens"):
        body["generationConfig"]["maxOutputTokens"] = int(request_body["max_tokens"])
    if system_chunks:
        body["systemInstruction"] = {"parts": [{"text": "\n\n".join(system_chunks)}]}
    if function_declarations:
        body["tools"] = [{"functionDeclarations": function_declarations}]

    headers = {"Content-Type": "application/json"}
    for key, value in (extra_headers or {}).items():
        headers[str(key)] = str(value)

    return ProviderPreparedRequest(
        provider="google_genai",
        url=f"{base_url.rstrip('/')}/models/{model}:generateContent",
        headers=headers,
        json_body=body,
        params={"key": api_key},
    )


def _parse_openai_compat_response(
    data: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[List[Dict[str, Any]]], Any, Any]:
    choice = (data.get("choices") or [{}])[0] or {}
    assistant_message = (choice.get("message") or {})
    tool_calls = assistant_message.get("tool_calls")
    content = assistant_message.get("content")
    finish_reason = choice.get("finish_reason")
    return assistant_message, tool_calls, content, finish_reason


def _parse_anthropic_response(
    data: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[List[Dict[str, Any]]], Any, Any]:
    blocks = list(data.get("content") or [])
    text_chunks: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    for index, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        block_type = str(block.get("type") or "").strip().lower()
        if block_type == "text":
            text = str(block.get("text") or "")
            if text:
                text_chunks.append(text)
            continue
        if block_type == "tool_use":
            function_name = str(block.get("name") or "").strip()
            if not function_name:
                continue
            arguments = block.get("input") or {}
            tool_calls.append(
                {
                    "id": str(block.get("id") or f"anthropic_tool_{index}"),
                    "type": "function",
                    "function": {
                        "name": function_name,
                        "arguments": json.dumps(arguments, ensure_ascii=False),
                    },
                }
            )
    assistant_message: Dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join([item for item in text_chunks if item]).strip(),
    }
    if tool_calls:
        assistant_message["tool_calls"] = tool_calls
    finish_reason = str(data.get("stop_reason") or "")
    return assistant_message, tool_calls or None, assistant_message.get("content"), finish_reason


def _parse_google_genai_response(
    data: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[List[Dict[str, Any]]], Any, Any]:
    candidates = list(data.get("candidates") or [])
    candidate = candidates[0] if candidates else {}
    content_obj = candidate.get("content") or {}
    parts = list(content_obj.get("parts") or [])

    text_chunks: List[str] = []
    tool_calls: List[Dict[str, Any]] = []
    for index, part in enumerate(parts):
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            text_chunks.append(text)
        function_call = part.get("functionCall") or {}
        if isinstance(function_call, dict) and function_call:
            function_name = str(function_call.get("name") or "").strip()
            if function_name:
                arguments = function_call.get("args") or {}
                tool_calls.append(
                    {
                        "id": f"genai_tool_{index}",
                        "type": "function",
                        "function": {
                            "name": function_name,
                            "arguments": json.dumps(arguments, ensure_ascii=False),
                        },
                    }
                )

    assistant_message: Dict[str, Any] = {
        "role": "assistant",
        "content": "\n".join([item for item in text_chunks if item]).strip(),
    }
    if tool_calls:
        assistant_message["tool_calls"] = tool_calls
    finish_reason = str(candidate.get("finishReason") or "")
    return assistant_message, tool_calls or None, assistant_message.get("content"), finish_reason
