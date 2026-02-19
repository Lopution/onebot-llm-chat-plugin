import sys
import os
import asyncio
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, "/root/bot/src")

# Mock nonebot
sys.modules["nonebot"] = MagicMock()
sys.modules["nonebot.adapters.onebot.v11"] = MagicMock()
sys.modules["nonebot.params"] = MagicMock()
sys.modules["nonebot.log"] = MagicMock() # logger

# Mock on_message to return a pass-through decorator
def mock_on_message(*args, **kwargs):
    def decorator(func):
        return func
    # The on_message returns an object (Matcher) which has .handle() method
    matcher = MagicMock()
    matcher.handle.return_value = decorator
    return matcher

sys.modules["nonebot"].on_message = mock_on_message
# Also need to mock on_command
sys.modules["nonebot"].on_command = mock_on_message

from nonebot.adapters.onebot.v11 import GroupMessageEvent

# Define dummy event class
class GroupMessageEvent:
    def __init__(self):
        self.group_id = 123
        self.user_id = 456
        self.message_id = 789
        self.to_me = False
        self.original_message = []
        self.sender = MagicMock()
        self.sender.card = "TestUser"
        self.sender.nickname = "TestUser"
        
    def get_plaintext(self):
        return ""

sys.modules["nonebot.adapters.onebot.v11"].GroupMessageEvent = GroupMessageEvent
sys.modules["nonebot"].logger = MagicMock()

# Mock config
from mika_chat_core.config import Config
mock_config = Config(mika_api_key="AIxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx")
mock_config.mika_proactive_rate = 1.0  # Force trigger for testing
mock_config.mika_heat_threshold = 2    # Low threshold
mock_config.mika_proactive_cooldown = 0 # No cooldown
mock_config.mika_group_whitelist = []  # Empty whitelist = allow logic? Check code.
mock_config.mika_proactive_keywords = ["Mika"]
mock_config.mika_proactive_topics = ["test"]
mock_config.mika_proactive_ignore_len = 0

# Import matchers
# We need to patch get_plugin_config before importing matchers
with patch("nonebot.get_plugin_config", return_value=mock_config):
    from mika_chat_core import matchers

# Overwrite global config in matchers just in case
matchers.plugin_config = mock_config
matchers._proactive_cooldowns = {} # Reset cooldowns

async def test_proactive():
    print("Testing Proactive Logic...")
    
    # 1. Test Heat Trigger
    # Simulate messages
    matchers.heat_monitor.record_message("123") # Heat = 1
    matchers.heat_monitor.record_message("123") # Heat = 2
    
    print(f"Current Heat: {matchers.heat_monitor.get_heat('123')}")
    # Create event
    event = GroupMessageEvent()
    event.group_id = 123
    event.to_me = False
    event.get_plaintext = MagicMock(return_value="hello world")
    
    # Check proactive
    result = await matchers.check_proactive(event)
    print(f"Check Result (Heat Trigger): {result}")
    
    if not result:
        print("Reason: Failed heat trigger check.")
        
    # 2. Test Keyword Trigger
    event.get_plaintext = MagicMock(return_value="hello Mika")
    result = await matchers.check_proactive(event)
    print(f"Check Result (Keyword Trigger): {result}")

    # 3. Test Judge Intent (Mock Mika client)
    # This requires mocking get_mika_client_dep
    
    mock_client = MagicMock()
    mock_client.context_store.get_context.return_value = [] # awaitable?
    
    # define async mock for get_context
    async def mock_get_context(*args):
        return []
    mock_client.context_store.get_context = mock_get_context
    
    async def mock_judge(context, heat):
        return {"should_reply": True, "reason": "Test pass"}
    mock_client.judge_proactive_intent = mock_judge

    # Patch deps
    # We need to ensure deps module is mocked or patchable
    # Since we imported matchers, deps might be imported relative.
    # We can patch 'mika_chat_core.deps.get_mika_client_dep'

    with patch("mika_chat_core.deps.get_mika_client_dep", return_value=mock_client), \
         patch("mika_chat_core.matchers.handle_group") as mock_handle_group:
         
         await matchers._handle_proactive(MagicMock(), event)
         
         if mock_handle_group.call_count > 0:
             print("SUCCESS: _handle_proactive called handle_group")
         else:
             print("FAILURE: _handle_proactive did NOT call handle_group")

if __name__ == "__main__":
    asyncio.run(test_proactive())
