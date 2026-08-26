"""Unit tests for `_offending_entry` — no HTTP round trip.

`web/bands.py` and `web/form_errors.py` had zero direct coverage before this;
`_offending_entry`'s behaviour changed when `second_entry` was dropped from the
manual entries (roadmap item 0), which is the moment to stop deferring it.
"""

from app.web.form_errors import _offending_entry


def test_offending_entry_names_entry_1a_when_it_is_the_offender() -> None:
    assert _offending_entry({"entry_1a": "0", "entry_1b": "5"}) == "entry_1a"


def test_offending_entry_names_entry_1b_when_it_is_the_offender() -> None:
    assert _offending_entry({"entry_1a": "5", "entry_1b": "-3"}) == "entry_1b"


def test_offending_entry_prefers_entry_1a_when_both_are_non_positive() -> None:
    assert _offending_entry({"entry_1a": "0", "entry_1b": "0"}) == "entry_1a"


def test_offending_entry_skips_a_non_numeric_value_rather_than_blaming_it() -> None:
    """A value that fails to parse isn't the domain's complaint — the schema
    already would have rejected it before the domain ever saw a plan."""
    assert _offending_entry({"entry_1a": "not a number", "entry_1b": "-1"}) == "entry_1b"


def test_offending_entry_falls_back_to_entry_1a() -> None:
    """Reached only if the domain raised "must all be positive" but neither
    submitted value actually parses as non-positive — should not happen, but
    the fallback must still name a primary field, not the retired one."""
    assert _offending_entry({"entry_1a": "5", "entry_1b": "5"}) == "entry_1a"
