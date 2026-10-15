"""Decide a confidence threshold for each species.

Each species gets one of three statuses:

- `logistic_fit`: enough validated clips, both outcomes present, and a significantly positive slope.
  The threshold is where the fitted curve reaches p_target.
- `score_independent`: enough validated clips, but no significant positive slope, for example because
  every clip was correct. One precision is estimated for the whole validated score range.
- `insufficient_validation`: too few validated clips, or the species was not validated at all.
  There is no threshold, so the species gets no observations.

One species never stops the pipeline. Its status and a reason are recorded and the next species is processed.
"""

from collections.abc import Iterable
from dataclasses import asdict, dataclass
from enum import StrEnum

import numpy as np
import pandas as pd

from natural_state.birds.regression import (
    FloatArray,
    IntArray,
    bootstrap_threshold_ci,
    fit_logistic,
    to_confidence,
    to_logit,
)
from natural_state.birds.settings import Settings


class Status(StrEnum):
    """How the threshold of a species was decided.

    Attributes
    ----------
    LOGISTIC_FIT
        The threshold comes from the fitted logistic curve.
    SCORE_INDEPENDENT
        Correctness does not depend on the score, so one precision applies to the validated range.
    INSUFFICIENT_VALIDATION
        Too few validated clips. The species has no threshold.
    """

    LOGISTIC_FIT = "logistic_fit"
    SCORE_INDEPENDENT = "score_independent"
    INSUFFICIENT_VALIDATION = "insufficient_validation"


@dataclass
class SpeciesThreshold:
    """The threshold decision for one species.

    Fields that do not apply to a status stay None.

    Attributes
    ----------
    common_name : str
        Species name, as used by BirdNET.
    status : Status
        How the threshold was decided.
    reason : str
        Explanation of the decision, for review. Empty when nothing needs attention.
    n_validated : int
        Number of validated clips.
    n_correct : int
        Number of validated clips that were correct.
    min_validated_conf, max_validated_conf : float or None
        Lowest and highest confidence score among the validated clips.
    beta0, beta1 : float or None
        Intercept and slope of the logistic regression, when one was fitted.
    p_slope : float or None
        p-value of the slope.
    aic : float or None
        Akaike information criterion of the fit.
    logit_threshold : float or None
        Threshold on the logit scale, for ``logistic_fit`` species.
    confidence_threshold : float or None
        Threshold on the confidence scale. Predictions at or above it become observations.
        None means no prediction of this species is accepted.
    threshold_ci_low, threshold_ci_high : float or None
        Bootstrap 95 % interval of the confidence threshold.
    precision_estimate : float or None
        Single precision estimate, for ``score_independent`` species.
    """

    common_name: str
    status: Status
    reason: str = ""
    n_validated: int = 0
    n_correct: int = 0
    min_validated_conf: float | None = None
    max_validated_conf: float | None = None
    beta0: float | None = None
    beta1: float | None = None
    p_slope: float | None = None
    aic: float | None = None
    logit_threshold: float | None = None
    confidence_threshold: float | None = None
    threshold_ci_low: float | None = None
    threshold_ci_high: float | None = None
    precision_estimate: float | None = None


def jeffreys_precision(n_correct: int, n_validated: int) -> float:
    """Estimate precision as ``(k + 0.5) / (n + 1)``, the Jeffreys estimate.

    Unlike ``k / n``, it stays below 1 when every clip is correct, so a perfect but small sample
    does not count as certainty.

    Parameters
    ----------
    n_correct : int
        Number of correct clips, ``k``.
    n_validated : int
        Number of validated clips, ``n``.

    Returns
    -------
    float
        Estimated share of correct predictions.
    """
    return (n_correct + 0.5) / (n_validated + 1)


def species_threshold(
    common_name: str,
    confidence: FloatArray,
    outcome: IntArray,
    settings: Settings,
    rng: np.random.Generator,
) -> SpeciesThreshold:
    """Decide the threshold for one species from its validated clips.

    Parameters
    ----------
    common_name : str
        Species name.
    confidence : FloatArray
        Confidence scores of the validated clips.
    outcome : IntArray
        Outcomes of the validated clips: 1 if correct, 0 if not.
    settings : Settings
        Pipeline parameters.
    rng : np.random.Generator
        Random number generator for the bootstrap interval.

    Returns
    -------
    SpeciesThreshold
        The decision, with the fitted model and threshold where they apply.
    """
    n_validated = len(outcome)
    n_correct = int(outcome.sum())
    max_validated_conf = float(confidence.max())
    result = SpeciesThreshold(
        common_name=common_name,
        status=Status.INSUFFICIENT_VALIDATION,
        n_validated=n_validated,
        n_correct=n_correct,
        min_validated_conf=float(confidence.min()),
        max_validated_conf=max_validated_conf,
    )

    if n_validated < settings.min_validations:
        result.reason = f"only {n_validated} validated clips"
        return result

    if n_correct == n_validated:
        return score_independent(result, "all validated clips correct", settings)
    if n_correct == 0:
        return score_independent(result, "no validated clip correct", settings)

    x = to_logit(confidence, settings.sensitivity, settings.clip)
    fit = fit_logistic(x, outcome)
    result.beta0 = fit.beta0
    result.beta1 = fit.beta1
    result.p_slope = fit.p_slope
    result.aic = fit.aic

    slope_is_positive = fit.beta1 > 0 and fit.p_slope < settings.alpha
    if not slope_is_positive:
        reason = f"slope not significantly positive (b1 = {fit.beta1:.2f}, p = {fit.p_slope:.2f})"
        return score_independent(result, reason, settings)

    result.status = Status.LOGISTIC_FIT
    result.logit_threshold = fit.threshold(settings.p_target)
    result.confidence_threshold = float(to_confidence(result.logit_threshold, settings.sensitivity))
    result.threshold_ci_low, result.threshold_ci_high = bootstrap_threshold_ci(
        x, outcome, settings.p_target, settings.sensitivity, settings.n_bootstrap, rng
    )
    if result.confidence_threshold > max_validated_conf:
        # Still applied, because it only makes the rule stricter. Flagged for review.
        result.reason = "threshold above highest validated score (extrapolated)"
    return result


def score_independent(result: SpeciesThreshold, reason: str, settings: Settings) -> SpeciesThreshold:
    """Set a score-independent threshold, using one precision for the whole validated score range.

    If that precision reaches ``p_target``, every prediction inside the validated range is accepted.
    Otherwise no prediction is accepted.

    Parameters
    ----------
    result : SpeciesThreshold
        Decision so far. It is updated in place.
    reason : str
        Why no logistic threshold is used. The precision comparison is appended to it.
    settings : Settings
        Pipeline parameters.

    Returns
    -------
    SpeciesThreshold
        The updated decision.
    """
    precision = jeffreys_precision(result.n_correct, result.n_validated)
    accept = precision >= settings.p_target

    result.status = Status.SCORE_INDEPENDENT
    result.precision_estimate = precision
    result.confidence_threshold = result.min_validated_conf if accept else None
    comparison = "≥" if accept else "<"
    result.reason = f"{reason}; precision estimate {precision:.4f} {comparison} {settings.p_target}"
    return result


def species_thresholds(
    validations: pd.DataFrame,
    predicted_species: Iterable[str],
    settings: Settings,
    rng: np.random.Generator,
) -> list[SpeciesThreshold]:
    """Decide thresholds for every validated species and every predicted species.

    Predicted species without any validated clips get the status ``insufficient_validation``.

    Parameters
    ----------
    validations : pd.DataFrame
        Validated clips with columns ``commonName``, ``confidence`` and ``outcome``.
    predicted_species : iterable of str
        Species names that appear in the predictions.
    settings : Settings
        Pipeline parameters.
    rng : np.random.Generator
        Random number generator for the bootstrap intervals.

    Returns
    -------
    list of SpeciesThreshold
        One decision per species: validated species first, then unvalidated ones in alphabetical order.
    """
    results = []
    for common_name, clips in validations.groupby("commonName"):
        result = species_threshold(
            common_name=str(common_name),
            confidence=clips["confidence"].to_numpy(dtype=np.float64),
            outcome=clips["outcome"].to_numpy(dtype=np.int64),
            settings=settings,
            rng=rng,
        )
        results.append(result)

    validated = {result.common_name for result in results}
    for common_name in sorted(set(predicted_species) - validated):
        results.append(SpeciesThreshold(common_name, Status.INSUFFICIENT_VALIDATION, reason="no validated clips"))
    return results


def thresholds_table(results: list[SpeciesThreshold]) -> pd.DataFrame:
    """Turn the threshold decisions into a table.

    Parameters
    ----------
    results : list of SpeciesThreshold
        Decisions, one per species.

    Returns
    -------
    pd.DataFrame
        One row per species, with every field of `SpeciesThreshold` as a column.
    """
    return pd.DataFrame([asdict(result) for result in results])
