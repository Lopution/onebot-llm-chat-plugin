from __future__ import annotations

from mika_chat_core.contracts import Author, ContentPart, EventEnvelope
from mika_chat_core.event_envelope import extract_content_parts
from mika_chat_core.semantic_transcript import (
    build_context_record_text,
    summarize_content_parts,
    summarize_envelope,
)


class _Seg:
    def __init__(self, seg_type: str, data: dict):
        self.type = seg_type
        self.data = data


def _compact_parts(parts: list[ContentPart]) -> list[tuple[str, str, str, str]]:
    return [
        (
            p.kind,
            p.target_id,
            p.text,
            p.asset_ref,
        )
        for p in parts
    ]


def test_extract_content_parts_v11_v12_semantics_are_consistent():
    v11_parts = extract_content_parts(
        [
            _Seg("text", {"text": "你好"}),
            _Seg("at", {"qq": "10000"}),
            _Seg("at", {"qq": "all"}),
            _Seg("reply", {"id": "r-1"}),
            _Seg("image", {"url": "asset-image"}),
            _Seg("file", {"file": "asset-file"}),
        ],
        fallback_plaintext="",
    )
    v12_parts = extract_content_parts(
        [
            _Seg("text", {"text": "你好"}),
            _Seg("mention", {"user_id": "10000"}),
            _Seg("mention_all", {}),
            _Seg("reply", {"message_id": "r-1"}),
            _Seg("image", {"file_id": "asset-image"}),
            _Seg("file", {"file_id": "asset-file"}),
        ],
        fallback_plaintext="",
    )

    assert _compact_parts(v11_parts) == _compact_parts(v12_parts)
    assert [p.kind for p in v11_parts] == ["text", "mention", "mention", "reply", "image", "attachment"]


def test_build_context_record_text_uses_semantic_fallback_on_parse_failure():
    summary = summarize_content_parts(
        [
            ContentPart(kind="reply", target_id="msg-1"),
            ContentPart(kind="mention", target_id="10000", text="@10000"),
        ]
    )
    text = build_context_record_text(
        summary=summary,
        plaintext="原始文本",
        parsed_text="",
        parse_failed=True,
    )
    assert "[引用消息]" in text
    assert "@10000" in text
    assert "原始文本" in text


def test_build_context_record_text_appends_image_and_attachment_placeholders():
    summary = summarize_content_parts(
        [
            ContentPart(kind="text", text="hello"),
            ContentPart(kind="image", asset_ref="img-1"),
            ContentPart(kind="attachment", asset_ref="file-1"),
            ContentPart(kind="attachment", asset_ref="file-2"),
        ]
    )
    text = build_context_record_text(
        summary=summary,
        plaintext="hello",
        parsed_text="hello",
        parse_failed=False,
    )
    assert text.endswith("[图片] [附件×2]")


def test_summarize_envelope_counts_match_parts():
    envelope = EventEnvelope(
        schema_version=1,
        session_id="group:123",
        platform="onebot_v11",
        protocol="onebot",
        message_id="m1",
        timestamp=1.0,
        author=Author(id="u1"),
        content_parts=[
            ContentPart(kind="mention", target_id="10000"),
            ContentPart(kind="image", asset_ref="img"),
            ContentPart(kind="attachment", asset_ref="f1"),
            ContentPart(kind="attachment", asset_ref="f2"),
        ],
    )
    summary = summarize_envelope(envelope)
    assert summary.has_mention is True
    assert summary.image_count == 1
    assert summary.attachment_count == 2
