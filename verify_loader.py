
import sys
import types
from unittest.mock import MagicMock

# Mock nonebot
nonebot_mock = MagicMock()
sys.modules["nonebot"] = nonebot_mock

# Add utils to path
sys.path.append("/root/bot/src/plugins/gemini_chat/utils")

# Import prompt_loader
import prompt_loader

def test_prompt_generation():
    # Load the actual system.yaml we just modified
    config = prompt_loader.load_prompt_yaml("system.yaml")
    
    # Generate prompt
    prompt = prompt_loader.generate_system_prompt(config)
    
    print("Generated Prompt Preview:")
    print(prompt)
    
    # Verify key sections
    if "Universal Sensei" in prompt or "Rules" in prompt: 
        # Note: "Universal Sensei" might not be in the final text if I used that as a section header but I think I did.
        # Let's check what I wrote in prompt_loader.py: parts.append("\n## Relationships & Attitude (Universal Sensei)")
        if "Relationships & Attitude (Universal Sensei)" in prompt:
            print("\n[SUCCESS] Found 'Universal Sensei' section.")
        else:
            print("\n[FAILURE] 'Universal Sensei' section missing.")
            
    if "所有用户 (都是 Sensei)" in prompt:
         print("[SUCCESS] Found target description.")
    else:
         print("[FAILURE] Target description missing.")

if __name__ == "__main__":
    test_prompt_generation()
