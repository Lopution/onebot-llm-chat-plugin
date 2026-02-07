
import sys
import os

# Add src to path
sys.path.insert(0, os.path.abspath("src"))

print("Importing config...")
try:
    from mika_chat_core.config import Config
    print("Config imported.")
except Exception as e:
    print(f"Failed to import Config: {e}")

print("Importing logic...")
try:
    from mika_chat_core.gemini_api import GeminiClient
    print("GeminiClient imported.")
except Exception as e:
    print(f"Failed to import GeminiClient: {e}")

print("Importing tools (simulating lazy import)...")
try:
    from mika_chat_core.tools import handle_search_group_history
    print("handle_search_group_history imported.")
except Exception as e:
    print(f"Failed to import tools: {e}")

print("Importing handlers...")
try:
    from mika_chat_core.handlers import sync_offline_messages
    print("handlers imported.")
except Exception as e:
    print(f"Failed to import handlers: {e}")
