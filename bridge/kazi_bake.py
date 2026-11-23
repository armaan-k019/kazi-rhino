#! python3
"""KaziBake: bake the outputs of the last kazi build to layers kazi::<title>::<output>."""
import scriptcontext as sc

cmds = sc.sticky.get("rhino_ai_mods_commands")
if cmds is None:
    print("[kazi] bridge is not running. Run KaziStart.")
else:
    try:
        cmds["kazi_bake"]({})
    except Exception as exc:  # noqa: BLE001
        print("[kazi] %s" % exc)
