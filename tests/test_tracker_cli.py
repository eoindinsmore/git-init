"""Smoke tests for the tracker CLI (spec §7) — parser wiring + no-op verify.

The command *logic* is the same code path exercised by the calls/marking/analytics
tests; here we only confirm the CLI parses every subcommand and that ``verify`` runs
cleanly against an empty/absent log.
"""

from __future__ import annotations

from tracker import cli


def test_parser_has_all_subcommands():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "cmd")
    assert set(sub.choices) == {"new", "amend", "close", "mark", "verify", "report"}


def test_verify_command_ok_on_empty(capsys, monkeypatch, tmp_path):
    # Point the event log at an absent file — verify should report a clean empty chain.
    monkeypatch.setattr(cli.ev, "EVENTS_PATH", tmp_path / "none.jsonl")
    assert cli.main(["verify"]) == 0
    assert "hash chain OK" in capsys.readouterr().out
