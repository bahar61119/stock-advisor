"""Rules-based technical signal module for stock analysis."""
from dataclasses import dataclass
from typing import Literal

from stock_advisor.providers.market_data.base import PriceSeries


@dataclass
class TechnicalComponents:
    """The individual indicator readings, before they are classified.

    Split out from `TechnicalSignal` so a verdict can be computed from the
    components without first constructing a `TechnicalSignal` that has no
    verdict yet -- which previously meant building one with `verdict=None`,
    in violation of its own `Literal` annotation, and then building a second
    one with the real verdict.
    """

    sma_50: float | None
    sma_200: float | None
    rsi_14: float | None
    macd_line: float | None
    macd_signal_line: float | None
    volume_trend: Literal["rising", "flat", "falling"] | None


@dataclass
class TechnicalSignal(TechnicalComponents):
    """Technical analysis signal with component indicators and composite verdict.

    Field order is inherited (the six components, then `verdict`), so this is
    constructed exactly as before.
    """

    verdict: Literal["bullish", "neutral", "bearish"]


def compute_sma(closes: list[float], window: int) -> float | None:
    """Compute simple moving average over the last `window` closes.

    Returns None if fewer than `window` closes are provided.
    """
    if len(closes) < window:
        return None
    return sum(closes[-window:]) / window


def compute_rsi(closes: list[float], window: int) -> float | None:
    """Compute relative strength index (RSI) over the last `window` closes.

    Returns None if fewer than `window + 1` closes are provided (need deltas).

    Algorithm:
    1. Calculate gains and losses between consecutive closes
    2. Average gain and loss (first average is SMA, subsequent are EMA)
    3. RSI = 100 * avg_gain / (avg_gain + avg_loss)
    """
    if len(closes) < window + 1:
        return None

    # Calculate deltas (gains and losses)
    gains = []
    losses = []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        if delta > 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-delta)

    # Average gain/loss: SMA over the first `window` periods, then an EMA --
    # exactly what compute_ema does (it seeds from the same SMA and uses the
    # same k = 2 / (window + 1)), so reuse it rather than inlining it again.
    avg_gain = compute_ema(gains, window)[-1]
    avg_loss = compute_ema(losses, window)[-1]

    # Avoid division by zero
    if avg_gain + avg_loss == 0:
        return 50.0

    rsi = 100.0 * avg_gain / (avg_gain + avg_loss)
    return rsi


def compute_ema(closes: list[float], window: int) -> list[float]:
    """Compute exponential moving average.

    First value is the SMA of the first `window` prices.
    Subsequent values use the standard recursive EMA formula.

    Returns a list of EMA values, one per close starting from index window-1.
    """
    if len(closes) < window:
        return []

    ema_values = []
    k = 2.0 / (window + 1)

    # First EMA: SMA of first window prices
    ema = sum(closes[:window]) / window
    ema_values.append(ema)

    # Subsequent EMAs: recursive update
    for i in range(window, len(closes)):
        ema = closes[i] * k + ema * (1 - k)
        ema_values.append(ema)

    return ema_values


def compute_macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float | None, float | None]:
    """Compute MACD line and signal line.

    MACD line = EMA(fast) - EMA(slow)
    Signal line = EMA of MACD line

    Returns (macd_line, signal_line) where both may be None if insufficient data.

    EMA seeding: first value is SMA of first window prices, then standard recursive update.
    """
    if len(closes) < slow:
        return None, None

    # Compute fast and slow EMAs
    fast_ema = compute_ema(closes, fast)
    slow_ema = compute_ema(closes, slow)

    # MACD line starts at index slow-1 (when both EMAs are defined)
    # We need the last MACD value
    if len(fast_ema) < len(slow_ema) or len(slow_ema) == 0:
        return None, None

    # Build MACD line values
    # fast_ema starts at index fast-1, slow_ema starts at index slow-1
    # MACD line starts at index slow-1 (when both are defined)
    macd_values = []
    for i in range(len(slow_ema)):
        # fast_ema[i] corresponds to close[fast + i]
        # slow_ema[i] corresponds to close[slow + i]
        # We align them: when slow_ema[i] is computed at close[slow + i],
        # fast_ema is at fast_ema[slow + i - fast] = fast_ema[i + slow - fast]
        fast_idx = i + slow - fast
        if fast_idx < len(fast_ema):
            macd_values.append(fast_ema[fast_idx] - slow_ema[i])

    if len(macd_values) == 0:
        return None, None

    # Compute signal line (EMA of MACD values)
    if len(macd_values) < signal:
        return macd_values[-1], None

    signal_ema = compute_ema(macd_values, signal)
    if len(signal_ema) == 0:
        return macd_values[-1], None

    return macd_values[-1], signal_ema[-1]


def compute_volume_trend(
    volumes: list[float], window: int
) -> Literal["rising", "flat", "falling"] | None:
    """Compute volume trend by comparing recent to older volume.

    Returns "rising" if recent average > older average,
    "falling" if recent average < older average,
    "flat" if they're approximately equal.
    Returns None if insufficient data.
    """
    if len(volumes) < 2 * window:
        return None

    older_avg = sum(volumes[-2 * window : -window]) / window
    recent_avg = sum(volumes[-window:]) / window

    # Use a small threshold to detect "flat"
    threshold = 0.01 * older_avg  # 1% threshold
    if abs(recent_avg - older_avg) <= threshold:
        return "flat"
    elif recent_avg > older_avg:
        return "rising"
    else:
        return "falling"


def classify_verdict(
    signal: TechnicalComponents,
) -> Literal["bullish", "neutral", "bearish"]:
    """Classify verdict based on individual signal components.

    Takes `TechnicalComponents` (a `TechnicalSignal` is also accepted, being
    a subclass) so it can be called before a verdict exists.

    Counts bullish and bearish points:
    - Bullish: sma_50 > sma_200, macd_line > macd_signal_line, 30 < rsi_14 < 70, volume_trend == "rising"
    - Bearish: sma_50 < sma_200, macd_line < macd_signal_line, rsi_14 <= 30 or rsi_14 >= 70, volume_trend == "falling"

    Returns "bullish" if bullish points >= 3, "bearish" if bearish points >= 3, else "neutral".
    """
    bullish_points = 0
    bearish_points = 0

    # SMA comparison
    if signal.sma_50 is not None and signal.sma_200 is not None:
        if signal.sma_50 > signal.sma_200:
            bullish_points += 1
        elif signal.sma_50 < signal.sma_200:
            bearish_points += 1

    # MACD comparison
    if signal.macd_line is not None and signal.macd_signal_line is not None:
        if signal.macd_line > signal.macd_signal_line:
            bullish_points += 1
        elif signal.macd_line < signal.macd_signal_line:
            bearish_points += 1

    # RSI range check
    if signal.rsi_14 is not None:
        if 30 < signal.rsi_14 < 70:
            bullish_points += 1
        elif signal.rsi_14 <= 30 or signal.rsi_14 >= 70:
            bearish_points += 1

    # Volume trend
    if signal.volume_trend is not None:
        if signal.volume_trend == "rising":
            bullish_points += 1
        elif signal.volume_trend == "falling":
            bearish_points += 1

    if bullish_points >= 3:
        return "bullish"
    elif bearish_points >= 3:
        return "bearish"
    else:
        return "neutral"


def compute_technical_signal(series: PriceSeries) -> TechnicalSignal:
    """Compute composite technical signal from a price series.

    Returns TechnicalSignal with all indicators computed where sufficient data exists.
    Components are None when series has fewer data points than the window requires.
    Verdict falls back to "neutral" when fewer than 2 of the 4 inputs are available.
    """
    closes = series.close
    volumes = series.volume

    # Compute individual indicators
    sma_50 = compute_sma(closes, window=50)
    sma_200 = compute_sma(closes, window=200)
    rsi_14 = compute_rsi(closes, window=14)
    macd_line, macd_signal_line = compute_macd(closes, fast=12, slow=26, signal=9)
    volume_trend = compute_volume_trend(volumes, window=20)

    # Classify from the components, then build the signal once.
    components = TechnicalComponents(
        sma_50=sma_50,
        sma_200=sma_200,
        rsi_14=rsi_14,
        macd_line=macd_line,
        macd_signal_line=macd_signal_line,
        volume_trend=volume_trend,
    )
    return TechnicalSignal(**vars(components), verdict=classify_verdict(components))
