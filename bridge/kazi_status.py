#! python3
"""KaziStatus: is the bridge running, and what has kazi built this session."""
import scriptcontext as sc

bridge = sc.sticky.get("rhino_ai_mods_bridge")
cmds = sc.sticky.get("rhino_ai_mods_commands")
if bridge is None or not bridge.running:
    print("[kazi] bridge is NOT running. Run KaziStart.")
else:
    print("[kazi] bridge running on %s:%d" % (bridge.host, bridge.sock.getsockname()[1]))
    builds = cmds["kazi_builds"]({})["builds"]
    if not builds:
        print("[kazi] nothing built yet")
    for i, b in enumerate(reversed(builds)):
        print("[kazi] %s%s  (sliders: %s)" % ("-> " if i == 0 else "   ", b.get("title"),
                                             ", ".join(sorted((b.get("sliders") or {}).keys()))))
