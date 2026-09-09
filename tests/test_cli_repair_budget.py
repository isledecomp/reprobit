"""The command-wide repair candidate budget follows an explicit discovery budget."""

from __future__ import annotations

from reprobit.cli_repair import repair_candidate_limit
from reprobit.search_limits import (
    DEFAULT_RETUNE_CANDIDATES,
    DEFAULT_RETUNE_PROBE_CANDIDATES,
    MAX_RETUNE_PROBE_CANDIDATES,
)


def test_defaults_apply_without_either_budget() -> None:
    assert repair_candidate_limit(None, None) == DEFAULT_RETUNE_PROBE_CANDIDATES


def test_an_explicit_candidate_limit_always_wins() -> None:
    assert repair_candidate_limit(300, 2000) == 300


def test_a_larger_discovery_budget_grows_the_command_limit() -> None:
    grown = repair_candidate_limit(None, 2005)
    assert grown == 2005 + DEFAULT_RETUNE_CANDIDATES
    assert grown > DEFAULT_RETUNE_PROBE_CANDIDATES


def test_a_small_discovery_budget_keeps_the_default_limit() -> None:
    assert repair_candidate_limit(None, 8) == DEFAULT_RETUNE_PROBE_CANDIDATES


def test_the_grown_limit_never_exceeds_the_maximum() -> None:
    assert repair_candidate_limit(None, MAX_RETUNE_PROBE_CANDIDATES) == MAX_RETUNE_PROBE_CANDIDATES
