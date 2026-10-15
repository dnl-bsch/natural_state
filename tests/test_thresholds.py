import numpy as np
import pandas as pd

from natural_state.birds.regression import logistic, to_confidence
from natural_state.birds.settings import Settings
from natural_state.birds.thresholds import Status, jeffreys_precision, species_threshold, species_thresholds

SETTINGS = Settings()


def test_jeffreys_precision() -> None:
    assert jeffreys_precision(n_correct=150, n_validated=150) == 150.5 / 151


def test_too_few_clips_gives_no_threshold() -> None:
    result = species_threshold("Test bird", np.full(10, 0.5), np.ones(10, dtype=np.int64), SETTINGS)
    assert result.status == Status.INSUFFICIENT_VALIDATION
    assert result.confidence_threshold is None


def test_all_correct_with_many_clips_accepts_the_validated_range() -> None:
    confidence = np.linspace(0.2, 0.9, 150)
    result = species_threshold("Test bird", confidence, np.ones(150, dtype=np.int64), SETTINGS)
    assert result.status == Status.SCORE_INDEPENDENT
    assert result.confidence_threshold == 0.2  # lowest validated score


def test_low_precision_without_score_effect_accepts_nothing() -> None:
    # 59 of 60 correct, with the wrong clip in the middle of the score range, so there is no score effect.
    # The precision estimate 59.5 / 61 = 0.975 is below 0.99, so nothing is accepted.
    confidence = np.linspace(0.2, 0.9, 60)
    outcome = np.ones(60, dtype=np.int64)
    outcome[30] = 0
    result = species_threshold("Test bird", confidence, outcome, SETTINGS)
    assert result.status == Status.SCORE_INDEPENDENT
    assert result.precision_estimate == 59.5 / 61
    assert result.confidence_threshold is None


def test_clear_score_effect_gives_a_logistic_fit() -> None:
    rng = np.random.default_rng(1)
    logit_score = rng.uniform(-4, 6, 300)
    outcome = (rng.uniform(0, 1, 300) < logistic(-1.0 + 1.5 * logit_score)).astype(np.int64)
    result = species_threshold("Test bird", to_confidence(logit_score), outcome, SETTINGS)
    assert result.status == Status.LOGISTIC_FIT
    assert result.confidence_threshold is not None
    assert 0 < result.confidence_threshold < 1


def test_unvalidated_species_are_added_without_threshold() -> None:
    validations = pd.DataFrame({"commonName": ["Bird A"] * 10, "confidence": [0.5] * 10, "outcome": [1] * 10})
    results = species_thresholds(validations, ["Bird A", "Bird B"], SETTINGS)
    assert [result.common_name for result in results] == ["Bird A", "Bird B"]
    assert results[1].status == Status.INSUFFICIENT_VALIDATION
    assert results[1].reason == "no validated clips"
