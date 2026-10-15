import numpy as np
import pytest

from natural_state.birds.regression import (
    LogisticFit,
    fit_logistic,
    logistic,
    to_confidence,
    to_logit,
)


def simulate_validations(beta0: float, beta1: float, n: int, seed: int = 1) -> tuple[np.ndarray, np.ndarray]:
    """Logit scores and 0/1 outcomes drawn from a known logistic model."""
    rng = np.random.default_rng(seed)
    x = rng.uniform(-4, 6, n)
    y = (rng.uniform(0, 1, n) < logistic(beta0 + beta1 * x)).astype(np.int64)
    return x, y


def test_to_logit_and_to_confidence_are_inverse() -> None:
    confidence = np.array([0.1, 0.5, 0.9, 0.99])
    assert to_confidence(to_logit(confidence)) == pytest.approx(confidence)


def test_to_logit_of_one_half_is_zero() -> None:
    assert to_logit(np.array([0.5]))[0] == pytest.approx(0.0)


def test_to_logit_is_finite_at_zero_and_one() -> None:
    assert np.isfinite(to_logit(np.array([0.0, 1.0]))).all()


def test_sensitivity_scales_the_logit() -> None:
    confidence = np.array([0.8])
    assert to_logit(confidence, sensitivity=2.0) == pytest.approx(to_logit(confidence) / 2)


def test_threshold_reaches_the_target_probability() -> None:
    fit = LogisticFit(beta0=-1.0, beta1=2.0, p_slope=0.0, aic=0.0)
    threshold = fit.threshold(0.99)
    assert logistic(fit.beta0 + fit.beta1 * np.array([threshold]))[0] == pytest.approx(0.99)


def test_threshold_matches_the_wood_and_kahl_formula() -> None:
    # threshold = (ln(p / (1 - p)) - beta0) / beta1
    fit = LogisticFit(beta0=3.0, beta1=0.5, p_slope=0.0, aic=0.0)
    expected = (np.log(0.9 / 0.1) - 3.0) / 0.5
    assert fit.threshold(0.9) == pytest.approx(expected)


def test_fit_recovers_known_coefficients() -> None:
    x, y = simulate_validations(beta0=-1.0, beta1=1.5, n=5000)
    fit = fit_logistic(x, y)
    assert fit.beta0 == pytest.approx(-1.0, abs=0.2)
    assert fit.beta1 == pytest.approx(1.5, abs=0.2)
    assert fit.p_slope < 0.001


def test_fit_finds_no_slope_when_outcome_ignores_the_score() -> None:
    x, y = simulate_validations(beta0=1.0, beta1=0.0, n=500)
    fit = fit_logistic(x, y)
    assert fit.p_slope > 0.05
