from types import SimpleNamespace


def test_build_event_context_v11_group():
    from mika_chat_core.utils.event_context import build_event_context

    bot = SimpleNamespace(type="OneBot V11", self_id="42")
    sender = SimpleNamespace(card="", nickname="Nick")

    class Event:
        user_id = 111
        group_id = 222
        message_id = 333
        to_me = True

        def __init__(self):
            self.sender = sender

        def get_plaintext(self):
            return "hi"

        def get_session_id(self):
            return "group_222_111"

    ctx = build_event_context(bot, Event())

    assert ctx.platform == "onebot_v11"
    assert ctx.user_id == "111"
    assert ctx.group_id == "222"
    assert ctx.message_id == "333"
    assert ctx.is_group is True
    assert ctx.is_tome is True
    assert ctx.plaintext == "hi"
    assert ctx.session_key == "group:222"
    assert ctx.sender_name == "Nick"


def test_build_event_context_v12_group_mentions_fallbacks():
    from mika_chat_core.utils.event_context import build_event_context

    bot = SimpleNamespace(type="OneBot V12", self_id="10000")

    class Event:
        user_id = "u1"
        group_id = "g1"
        message_id = "m1"

        def is_tome(self):
            return True

        def get_plaintext(self):
            return "hello"

        def get_session_id(self):
            return "group_g1_u1"

    ctx = build_event_context(bot, Event())

    assert ctx.platform == "onebot_v12"
    assert ctx.user_id == "u1"
    assert ctx.group_id == "g1"
    assert ctx.message_id == "m1"
    assert ctx.is_group is True
    assert ctx.is_tome is True
    assert ctx.session_key == "group:g1"
    # no sender field -> fallback to user_id
    assert ctx.sender_name == "u1"


def test_build_event_context_private_session_key():
    from mika_chat_core.utils.event_context import build_event_context

    bot = SimpleNamespace(type="OneBot V12", self_id="10000")

    class Event:
        user_id = "123"
        message_id = "m2"
        to_me = False

        def get_plaintext(self):
            return "ping"

        def get_session_id(self):
            return "private_123"

    ctx = build_event_context(bot, Event())
    assert ctx.group_id is None
    assert ctx.session_key == "private:123"


def test_build_event_context_parses_from_session_id_when_missing_fields():
    from mika_chat_core.utils.event_context import build_event_context

    bot = SimpleNamespace(type="OneBot V11", self_id="42")

    class Event:
        def get_plaintext(self):
            return ""

        def get_session_id(self):
            return "group_888_999"

    ctx = build_event_context(bot, Event())
    assert ctx.group_id == "888"
    assert ctx.user_id == "999"
    assert ctx.session_key == "group:888"
