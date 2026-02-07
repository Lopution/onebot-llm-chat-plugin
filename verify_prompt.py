
import sys
import os
sys.path.append("/root/bot")

# Mock nonebot logger
import nonebot
from unittest.mock import MagicMock
nonebot.logger = MagicMock()
nonebot.get_driver = MagicMock()

from src.mika_chat_core.utils.prompt_loader import get_system_prompt

try:
    prompt = get_system_prompt(prompt_file="system.yaml")
    
    # Check for new sections
    checks = {
        "Role": "# Role: 圣园未花",
        "Personality": "## Personality",
        "Relationships": "## Relationships & Attitude",
        "To Sensei": "### To Sensei (Master)",
        "Language Style": "## Language Style",
        "Instructions": "## System Instructions (Critical)",
        "Few-Shot": "## Dialogue Examples (Few-Shot)"
    }
    
    failed = []
    for name, signature in checks.items():
        if signature not in prompt:
            failed.append(name)
            
    if not failed:
        print("SUCCESS: System prompt loaded and contains all new sections.")
        print("-" * 50)
        print(prompt[:500] + "\n...\n" + prompt[-500:])
        print("-" * 50)
    else:
        print(f"FAILURE: Missing sections: {failed}")
        print("Generated partial prompt:")
        print(prompt)

except Exception as e:
    print(f"FAILURE: Exception during prompt loading: {e}")
    import traceback
    traceback.print_exc()
