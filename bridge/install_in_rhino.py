#! python3
"""Run once inside Rhino 8:  _-ScriptEditor _Run "<repo>\\bridge\\install_in_rhino.py"

Adds Kazi* command aliases (typed in the command bar, or put on a toolbar button):

    KaziStart      start the bridge (rhinomcp's mcpstart too, if installed)
    KaziStop       stop the bridge
    KaziStatus     bridge status + what kazi built this session
    KaziUndoBuild  remove the last voice/MCP build from Grasshopper
    KaziBake       bake the last build's outputs to layers kazi::<title>::<output>

Then add  KaziStart  to Tools > Options > General > "Run these commands every time Rhino starts".
"""
import os

import Rhino

HERE = os.path.dirname(os.path.abspath(__file__))


def run(script):
    return '_-ScriptEditor _Run "%s"' % os.path.join(HERE, script)


ALIASES = {
    "KaziStart": "_-mcpstart _Enter " + run("rhino_ai_bridge.py"),
    "KaziStop": run("stop_bridge.py"),
    "KaziStatus": run("kazi_status.py"),
    "KaziUndoBuild": run("kazi_undo_build.py"),
    "KaziBake": run("kazi_bake.py"),
}


def install(aliases=Rhino.ApplicationSettings.CommandAliasList, mcp_installed=None):
    if mcp_installed is None:
        mcp_installed = "mcpstart" in [str(n).lower() for n in
                                       Rhino.Commands.Command.GetCommandNames(True, False)]
    done = []
    for name, macro in ALIASES.items():
        if name == "KaziStart" and not mcp_installed:
            macro = run("rhino_ai_bridge.py")
        if aliases.IsAlias(name):
            aliases.SetMacro(name, macro)
        else:
            aliases.Add(name, macro)
        done.append(name)
    print("[kazi] installed aliases: " + ", ".join(done))
    if not mcp_installed:
        print("[kazi] rhinomcp not found: install it from Package Manager for Claude's modeling tools")
    print('[kazi] last step: add "KaziStart" to Tools > Options > General > '
          '"Run these commands every time Rhino starts"')
    return done


if __name__ == "__main__":
    install()
