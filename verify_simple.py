
import sys
import yaml
from pathlib import Path

# Adjust path to find module
sys.path.append("/root/bot/src/plugins/gemini_chat/utils")

# Mock logger
class Logger:
    def success(self, msg): print(f"[SUCCESS] {msg}")
    def error(self, msg): print(f"[ERROR] {msg}")
    def warning(self, msg): print(f"[WARNING] {msg}")
    def debug(self, msg): print(f"[DEBUG] {msg}")
    def info(self, msg): print(f"[INFO] {msg}")

import builtins
# Hack to mock nonebot.logger before import
# But prompt_loader imports 'nonebot' directly.
# We'll just read the file locally and use a modified version of the function to test logic
# or just run a script that manually checks the yaml structure.

def check_yaml():
    try:
        with open("/root/bot/src/plugins/gemini_chat/prompts/system.yaml", 'r') as f:
            data = yaml.safe_load(f)
        
        print("YAML Loaded successfully.")
        required_keys = ['role', 'personality']
        for k in required_keys:
            if k not in data:
                print(f"MISSING KEY: {k}")
            else:
                print(f"FOUND KEY: {k}")
                
        # Simulate logic
        role = data.get("role", {})
        print(f"Role Name: {role.get('name')}")
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check_yaml()
