import pytest
from tests.conftest import make_price_series
from stock_advisor.analysis.technical import (
    TechnicalSignal,
    classify_verdict,
    compute_macd,
    compute_rsi,
    compute_sma,
    compute_technical_signal,
    compute_volume_trend,
)


def test_sma_matches_hand_computed_average():
    series = make_price_series(closes=[10, 20, 30, 40, 50])
    assert compute_sma(series.close, window=5) == 30.0


def test_rsi_all_gains_is_100():
    series = make_price_series(closes=list(range(1, 20)))  # strictly rising
    assert compute_rsi(series.close, window=14) == pytest.approx(100.0)


def test_macd_known_values():
    # Linear price series + small fast/slow/signal windows (not the 50/200/12-26-9
    # production defaults — this test is of the generic compute_macd function,
    # same as test_sma_matches_hand_computed_average uses window=5, not 50/200).
    # Hand-verified: with closes rising by 1 each step, EMA(fast=2) - EMA(slow=4)
    # stabilizes at exactly 1.0 from the first point both EMAs are defined, and
    # the signal line (an EMA of a constant 1.0 series) is also exactly 1.0.
    series = make_price_series(closes=[10, 11, 12, 13, 14, 15, 16])
    line, signal = compute_macd(series.close, fast=2, slow=4, signal=2)
    assert line == pytest.approx(1.0, abs=0.001)
    assert signal == pytest.approx(1.0, abs=0.001)


def test_volume_trend_rising_when_recent_higher():
    volumes = [100] * 20 + [300] * 20
    assert compute_volume_trend(volumes, window=20) == "rising"


def test_composite_verdict_bullish_when_three_signals_align():
    signal = TechnicalSignal(
        sma_50=110,
        sma_200=100,
        rsi_14=55,
        macd_line=1.0,
        macd_signal_line=0.5,
        volume_trend="rising",
        verdict=None,
    )
    assert classify_verdict(signal) == "bullish"


def test_composite_verdict_neutral_when_mixed():
    signal = TechnicalSignal(
        sma_50=100,
        sma_200=110,
        rsi_14=55,
        macd_line=1.0,
        macd_signal_line=0.5,
        volume_trend="flat",
        verdict=None,
    )
    assert classify_verdict(signal) == "neutral"


def test_sma_200_none_with_insufficient_history():
    series = make_price_series(closes=[1.0] * 50)
    result = compute_technical_signal(series)
    assert result.sma_200 is None
