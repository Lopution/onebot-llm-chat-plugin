# Tool Plugin Example

This example demonstrates a minimal external tool plugin for `mika_chat_core`.

## Configure

Add this module path to config:

```env
MIKA_TOOL_PLUGINS=["examples.tool_plugin_example.plugin:Plugin"]
```

## What it provides

- tool name: `roll_dice`
- source: `plugin`
- behavior: returns a random dice result
