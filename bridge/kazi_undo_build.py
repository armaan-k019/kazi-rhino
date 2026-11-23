#! python3
"""KaziUndoBuild: remove the last thing kazi built in Grasshopper."""
import scriptcontext as sc

cmds = sc.sticky.get("rhino_ai_mods_commands")
if cmds is None:
    print("[kazi] bridge is not running. Run KaziStart.")
else:
    try:
        cmds["kazi_undo_build"]({})
    except Exception as exc:  # noqa: BLE001
        print("[kazi] %s" % exc)
