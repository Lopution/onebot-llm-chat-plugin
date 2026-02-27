import time

from mika_chat_core.utils.history_image_policy import (
    HistoryImageAction,
    determine_history_image_action,
)
from mika_chat_core.utils.image_cache_core import CachedImage


def _image(msg_id: str) -> CachedImage:
    return CachedImage(
        url=f"https://example.com/{msg_id}.jpg",
        sender_id="123",
        sender_name="Tester",
        message_id=msg_id,
        timestamp=time.time(),
    )


def test_hybrid_uses_inline_only_for_strong_reference():
    decision = determine_history_image_action(
        message_text="刚才那张图是啥",
        candidate_images=[_image("m1"), _image("m2")],
        mode="hybrid",
        inline_max=1,
        two_stage_max=2,
        enable_collage=False,
        inline_threshold=0.85,
        two_stage_threshold=0.5,
    )

    assert decision.action == HistoryImageAction.INLINE
    assert [img.message_id for img in decision.images_to_inject] == ["m1"]


def test_hybrid_general_keyword_prefers_two_stage():
    decision = determine_history_image_action(
        message_text="帮我看看这张图",
        candidate_images=[_image("m1"), _image("m2"), _image("m3")],
        mode="hybrid",
        inline_max=1,
        two_stage_max=2,
        enable_collage=False,
        inline_threshold=0.85,
        two_stage_threshold=0.5,
    )

    assert decision.action == HistoryImageAction.TWO_STAGE
    assert decision.candidate_msg_ids == ["m1", "m2"]


def test_hybrid_comparison_uses_collage_only_when_enabled():
    disabled = determine_history_image_action(
        message_text="对比这两张",
        candidate_images=[_image("m1"), _image("m2")],
        mode="hybrid",
        inline_max=1,
        two_stage_max=2,
        enable_collage=False,
        inline_threshold=0.85,
        two_stage_threshold=0.5,
    )
    enabled = determine_history_image_action(
        message_text="对比这两张",
        candidate_images=[_image("m1"), _image("m2")],
        mode="hybrid",
        inline_max=1,
        two_stage_max=2,
        enable_collage=True,
        inline_threshold=0.85,
        two_stage_threshold=0.5,
    )

    assert disabled.action == HistoryImageAction.TWO_STAGE
    assert enabled.action == HistoryImageAction.COLLAGE


def test_context_image_placeholder_supports_image_keyword_variant():
    decision = determine_history_image_action(
        message_text="嗯",
        candidate_images=[_image("m1")],
        context_messages=[{"role": "assistant", "content": "[Image: a screenshot]"}],
        mode="hybrid",
        inline_max=1,
        two_stage_max=1,
        enable_collage=False,
        inline_threshold=0.85,
        two_stage_threshold=0.3,
    )

    assert decision.action == HistoryImageAction.TWO_STAGE
    assert decision.candidate_msg_ids == ["m1"]


def test_implicit_reference_with_picid_placeholder_triggers_two_stage():
    decision = determine_history_image_action(
        message_text="啥意思",
        candidate_images=[_image("m1")],
        context_messages=[{"role": "user", "content": "[图片][picid:abc123]"}],
        mode="hybrid",
        inline_max=1,
        two_stage_max=1,
        enable_collage=False,
        inline_threshold=0.85,
        two_stage_threshold=0.5,
    )

    assert decision.action == HistoryImageAction.TWO_STAGE
    assert decision.candidate_msg_ids == ["m1"]


def test_implicit_reference_with_emoji_placeholder_triggers_two_stage():
    decision = determine_history_image_action(
        message_text="解释下",
        candidate_images=[_image("m1")],
        context_messages=[{"role": "user", "content": "[表情][emoji:deadbeef]"}],
        mode="hybrid",
        inline_max=1,
        two_stage_max=1,
        enable_collage=False,
        inline_threshold=0.85,
        two_stage_threshold=0.5,
    )

    assert decision.action == HistoryImageAction.TWO_STAGE
    assert decision.candidate_msg_ids == ["m1"]


def test_implicit_reference_with_multimodal_history_triggers_two_stage():
    decision = determine_history_image_action(
        message_text="啥意思",
        candidate_images=[_image("m1")],
        context_messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "看看"},
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
                ],
            }
        ],
        mode="hybrid",
        inline_max=1,
        two_stage_max=1,
        enable_collage=False,
        inline_threshold=0.85,
        two_stage_threshold=0.5,
    )

    assert decision.action == HistoryImageAction.TWO_STAGE
    assert decision.candidate_msg_ids == ["m1"]


def test_implicit_followup_punctuation_triggers_two_stage_when_recent_media_present():
    decision = determine_history_image_action(
        message_text="？",
        candidate_images=[_image("m1")],
        context_messages=[{"role": "user", "content": "[图片][picid:abc123]", "message_id": "m1"}],
        mode="hybrid",
        inline_max=1,
        two_stage_max=1,
        enable_collage=False,
        inline_threshold=0.85,
        two_stage_threshold=0.5,
    )

    assert decision.action == HistoryImageAction.TWO_STAGE
    assert decision.candidate_msg_ids == ["m1"]


def test_punctuation_without_media_does_not_trigger_two_stage():
    decision = determine_history_image_action(
        message_text="？",
        candidate_images=[_image("m1")],
        context_messages=[{"role": "user", "content": "随便聊聊"}],
        mode="hybrid",
        inline_max=1,
        two_stage_max=1,
        enable_collage=False,
        inline_threshold=0.85,
        two_stage_threshold=0.5,
    )

    assert decision.action == HistoryImageAction.NONE
