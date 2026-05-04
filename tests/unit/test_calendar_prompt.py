"""Unit tests for the keypress-driven calendar picker prompt.

The picker reads raw keypresses (so it can recognise ESC) instead of using
``click.prompt``. These tests patch ``_read_keypress`` to feed key sequences
and verify the buffer/Enter/ESC/Backspace/Ctrl+C contract of
``_prompt_choice_index``.
"""

from typing import Optional
from unittest.mock import patch

import click
import pytest

from herds_cli.commands import cmd_calendar


def _run_with_keys(default: Optional[int], n: int, keys: list[str]) -> Optional[int]:
    with patch.object(cmd_calendar, "_read_keypress", side_effect=keys):
        return cmd_calendar._prompt_choice_index(default, n)


def test_enter_with_default_returns_default():
    assert _run_with_keys(default=2, n=3, keys=["\r"]) == 2


def test_digit_then_enter_returns_value():
    assert _run_with_keys(default=None, n=3, keys=["2", "\r"]) == 2


def test_multi_digit_then_enter_returns_value():
    # Buffer accumulates "1" + "2" -> 12 within range 1..15.
    assert _run_with_keys(default=None, n=15, keys=["1", "2", "\r"]) == 12


def test_esc_returns_none():
    assert _run_with_keys(default=2, n=3, keys=["\x1b"]) is None


def test_esc_returns_none_even_after_typing_digits():
    # User starts typing then changes their mind.
    assert _run_with_keys(default=None, n=3, keys=["1", "\x1b"]) is None


def test_ctrl_c_raises_abort():
    with pytest.raises(click.Abort):
        _run_with_keys(default=2, n=3, keys=["\x03"])


def test_backspace_clears_buffer_and_default_kicks_in():
    # Type "2", backspace it, then Enter -> default applies.
    assert _run_with_keys(default=1, n=3, keys=["2", "\x7f", "\r"]) == 1


def test_out_of_range_re_prompts_then_accepts():
    # "9" is out of range for n=3 -> error + re-prompt; then "2\r" succeeds.
    assert _run_with_keys(default=None, n=3, keys=["9", "\r", "2", "\r"]) == 2


def test_empty_buffer_with_no_default_re_prompts():
    # Enter with empty buffer and no default -> error + re-prompt; then "1\r".
    assert _run_with_keys(default=None, n=3, keys=["\r", "1", "\r"]) == 1


def test_non_digit_chars_are_ignored():
    # Letters and spaces are silently ignored; only digits accumulate.
    assert _run_with_keys(default=None, n=9, keys=["a", " ", "3", "\r"]) == 3
