from __future__ import annotations


def test_build_llm_safe_message_text_rewrites_group_nickname_to_alias():
    from mika_chat_core.utils.speaker_labels import build_llm_safe_message_text
    from mika_chat_core.utils.speaker_labels import speaker_label_for_user_id

    msg = "[明天16把Q12一把Q7(1131426188)]: mika也提到了"
    out = build_llm_safe_message_text(msg)
    assert out.startswith(f"{speaker_label_for_user_id('1131426188')}: ")
    assert "mika也提到了" in out
    assert "Q12" not in out
    assert "Q7" not in out
    assert "明天16把" not in out


def test_build_llm_safe_message_text_keeps_private_tag_unchanged():
    from mika_chat_core.utils.speaker_labels import build_llm_safe_message_text

    msg = "[⭐Sensei]: 你好"
    assert build_llm_safe_message_text(msg) == msg

