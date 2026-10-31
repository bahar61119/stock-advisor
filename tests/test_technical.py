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


# --- Guards for the two internal refactors ---


def inline_rsi(closes, window):
    """RSI with the average-gain/loss EMA written out inline.

    `compute_rsi` now delegates that step to `compute_ema`; this is the
    independent derivation it must keep agreeing with, since the existing
    all-gains test would pass even if the smoothing were wrong.
    """
    if len(closes) < window + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(delta if delta > 0 else 0.0)
        losses.append(0.0 if delta > 0 else -delta)
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    k = 2.0 / (window + 1)
    for i in range(window, len(gains)):
        avg_gain = gains[i] * k + avg_gain * (1 - k)
        avg_loss = losses[i] * k + avg_loss * (1 - k)
    if avg_gain + avg_loss == 0:
        return 50.0
    return 100.0 * avg_gain / (avg_gain + avg_loss)


def test_rsi_matches_an_inline_ema_derivation_on_mixed_series():
    import random

    random.seed(7)
    for _ in range(50):
        closes = [100.0]
        for _ in range(random.randint(15, 120)):
            closes.append(max(1.0, closes[-1] + random.uniform(-3, 3)))
        assert compute_rsi(closes, window=14) == pytest.approx(
            inline_rsi(closes, 14), abs=1e-12
        )


def test_rsi_all_losses_is_zero():
    assert compute_rsi(list(range(40, 1, -1)), window=14) == pytest.approx(0.0)


def test_rsi_flat_series_is_fifty():
    assert compute_rsi([100.0] * 30, window=14) == 50.0


def test_compute_technical_signal_verdict_is_never_none():
    """compute_technical_signal used to build a TechnicalSignal with
    verdict=None (violating its own Literal annotation) before building the
    real one. It now builds one object; the returned verdict is always set.
    """
    series = make_price_series(closes=[float(i) for i in range(1, 60)])
    result = compute_technical_signal(series)
    assert result.verdict in ("bullish", "neutral", "bearish")


def test_compute_technical_signal_verdict_matches_its_own_components():
    """The single construction must carry the verdict classified from the
    very components it reports -- not a stale one.
    """
    closes = [100 * (1.004**i) for i in range(250)]
    volumes = [1000.0] * 230 + [3000.0] * 20
    series = make_price_series(closes=closes, volumes=volumes)
    result = compute_technical_signal(series)
    assert classify_verdict(result) == result.verdict


def test_classify_verdict_accepts_components_without_a_verdict():
    """classify_verdict is typed on TechnicalComponents so it can be called
    before a verdict exists, which is what removes the verdict=None hack.
    """
    from stock_advisor.analysis.technical import TechnicalComponents

    components = TechnicalComponents(
        sma_50=110,
        sma_200=100,
        rsi_14=55,
        macd_line=1.0,
        macd_signal_line=0.5,
        volume_trend="rising",
    )
    assert classify_verdict(components) == "bullish"
