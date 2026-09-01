"""Tests for the generic helpers in utils.py."""

from __future__ import annotations

import pytest

from utils import format_time, parse_time, safe_filename


class TestParseTime:
    def test_hhmmss(self) -> None:
        assert parse_time("01:02:03") == 3723.0

    def test_mmss(self) -> None:
        assert parse_time("02:30") == 150.0

    def test_bare_seconds(self) -> None:
        assert parse_time("45") == 45.0

    def test_decimal_seconds(self) -> None:
        assert parse_time("12.5") == 12.5

    def test_numeric_input(self) -> None:
        assert parse_time(90) == 90.0
        assert parse_time(1.5) == 1.5

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_time("not-a-time")
        with pytest.raises(ValueError):
            parse_time("")


class TestFormatTime:
    def test_basic(self) -> None:
        assert format_time(3723) == "01:02:03"

    def test_negative_clamped(self) -> None:
        assert format_time(-5) == "00:00:00"

    def test_rounds_down(self) -> None:
        assert format_time(59.9) == "00:00:59"


class TestSafeFilename:
    def test_illegal_chars_replaced(self) -> None:
        assert safe_filename('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"

    def test_whitespace_to_underscore(self) -> None:
        assert safe_filename("hello world") == "hello_world"

    def test_empty_falls_back(self) -> None:
        assert safe_filename("") == "clip"
        assert safe_filename("***") == "clip"

    def test_custom_fallback(self) -> None:
        assert safe_filename("", fallback="custom") == "custom"