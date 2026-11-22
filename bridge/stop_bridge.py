#! python3
"""Stop the rhino-ai-mods bridge started by rhino_ai_bridge.py."""
import scriptcontext as sc

bridge = sc.sticky.pop("rhino_ai_mods_bridge", None)
if bridge is None:
    print("rhino-ai-mods bridge is not running")
else:
    bridge.stop()
    print("rhino-ai-mods bridge stopped")
