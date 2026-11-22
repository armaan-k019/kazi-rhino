import pytest

from rhino_ai_mods.voice.rules import RuleMapper, normalize, words_to_numbers


@pytest.mark.parametrize("spoken,expected", [
    ("two point five", "2.5"),
    ("twenty five", "25"),
    ("minus three", "-3"),
    ("ten by ten", "10 by 10"),
])
def test_words_to_numbers(spoken, expected):
    assert words_to_numbers(spoken) == expected


def test_normalize_strips_fillers_and_punctuation():
    assert normalize("Please undo.") == "undo"
    assert normalize("Circle zero comma zero comma zero five.") == "circle 0,0,0 5"
    assert normalize("Circle 0, 0, 0 5") == "circle 0,0,0 5"


@pytest.mark.parametrize("spoken,macro,source", [
    ("Undo.", "_Undo", "alias"),
    ("Zoom extents", "_Zoom _All _Extents", "alias"),
    ("Boolean union.", "_BooleanUnion", "command"),
    ("circle zero comma zero comma zero five", "_Circle 0,0,0 5", "command"),
    ("Box", "_Box", "command"),
    ("run loft", "_Loft", "command"),
    ("top view", "_SetView _World _Top", "alias"),
])
def test_rule_hits(spoken, macro, source):
    m = RuleMapper().map(spoken)
    assert m is not None
    assert (m.macro, m.source) == (macro, source)


@pytest.mark.parametrize("spoken", [
    "make a box ten by ten by five",
    "remind me to call the client",
    "move this up a bit",
])
def test_sentences_go_to_the_model(spoken):
    assert RuleMapper().map(spoken) is None


def test_dangerous_commands_need_confirmation():
    assert RuleMapper().map("delete").needs_confirm
    assert RuleMapper().map("exit").needs_confirm
    assert not RuleMapper().map("box").needs_confirm


def test_live_command_list_is_used():
    r = RuleMapper(["MyPluginCommand"])
    assert r.map("my plugin command").macro == "_MyPluginCommand"
