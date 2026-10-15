"""Logistic regression of prediction correctness on the BirdNET logit score."""

import warnings
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import statsmodels.api as sm
from statsmodels.tools.sm_exceptions import ConvergenceWarning, PerfectSeparationWarning

FloatArray = npt.NDArray[np.float64]
"""Array of floats, for example confidence or logit scores."""

IntArray = npt.NDArray[np.int64]
"""Array of integers, for example validation outcomes (1 = correct, 0 = wrong)."""


def to_logit(confidence: FloatArray, sensitivity: float = 1.0, clip: float = 1e-4) -> FloatArray:
    """Convert BirdNET confidence scores back to logit scores.

    The logit score is ``ln(c / (1 - c)) / sensitivity``. Scores of exactly 0 or 1 would give an
    infinite logit, so they are first clipped to ``[clip, 1 - clip]``.

    Parameters
    ----------
    confidence : FloatArray
        BirdNET confidence scores between 0 and 1.
    sensitivity : float, default 1.0
        BirdNET sensitivity used in the BirdNET run.
    clip : float, default 1e-4
        Distance from 0 and 1 to which scores are clipped.

    Returns
    -------
    FloatArray
        Logit scores, one per confidence score.
    """
    clipped = np.clip(confidence, clip, 1 - clip)
    logit: FloatArray = np.log(clipped / (1 - clipped)) / sensitivity
    return logit


def logistic(z: FloatArray) -> FloatArray:
    """Apply the logistic function ``1 / (1 + e^-z)``.

    Parameters
    ----------
    z : FloatArray
        Any real numbers.

    Returns
    -------
    FloatArray
        Values between 0 and 1.
    """
    p: FloatArray = 1 / (1 + np.exp(-z))
    return p


def to_confidence(logit_score: FloatArray | float, sensitivity: float = 1.0) -> FloatArray:
    """Convert logit scores to BirdNET confidence scores. This is the inverse of `to_logit`.

    Parameters
    ----------
    logit_score : FloatArray or float
        Logit scores.
    sensitivity : float, default 1.0
        BirdNET sensitivity used in the BirdNET run.

    Returns
    -------
    FloatArray
        Confidence scores between 0 and 1.
    """
    return logistic(np.asarray(logit_score, dtype=np.float64) * sensitivity)


@dataclass(frozen=True)
class LogisticFit:
    """Fitted model ``logit(p) = beta0 + beta1 * x``.

    Here ``p`` is the probability that a prediction is correct and ``x`` is the logit score.

    Attributes
    ----------
    beta0 : float
        Intercept.
    beta1 : float
        Slope on the logit score. A positive slope means higher scores are more often correct.
    p_slope : float
        p-value of the slope.
    aic : float
        Akaike information criterion of the fit.
    """

    beta0: float
    beta1: float
    p_slope: float
    aic: float

    def probability(self, x: FloatArray) -> FloatArray:
        """Probability that a prediction is correct, given its logit score.

        Parameters
        ----------
        x : FloatArray
            Logit scores.

        Returns
        -------
        FloatArray
            Probabilities between 0 and 1.
        """
        return logistic(self.beta0 + self.beta1 * x)

    def threshold(self, p: float) -> float:
        """Logit score at which the probability of a correct prediction equals ``p``.

        This solves the fitted curve for ``x``: ``(ln(p / (1 - p)) - beta0) / beta1``.

        Parameters
        ----------
        p : float
            Target probability, strictly between 0 and 1.

        Returns
        -------
        float
            Logit score threshold.
        """
        return float((np.log(p / (1 - p)) - self.beta0) / self.beta1)


def fit_logistic(x: FloatArray, y: IntArray) -> LogisticFit:
    """Fit a logistic regression of the outcome on the logit score.

    Parameters
    ----------
    x : FloatArray
        Logit scores of the validated clips.
    y : IntArray
        Outcomes of the validated clips: 1 if the prediction was correct, 0 if not.

    Returns
    -------
    LogisticFit
        Coefficients, p-value of the slope and AIC.
    """
    model = sm.Logit(y, sm.add_constant(x))
    result = model.fit(disp=False)
    return LogisticFit(
        beta0=float(result.params[0]),
        beta1=float(result.params[1]),
        p_slope=float(result.pvalues[1]),
        aic=float(result.aic),
    )


def bootstrap_threshold_ci(
    x: FloatArray,
    y: IntArray,
    p_target: float,
    sensitivity: float,
    n_bootstrap: int,
    rng: np.random.Generator,
) -> tuple[float, float]:
    """95 % percentile interval of the confidence threshold, from resampling the validated clips.

    A resample is skipped when it has only one outcome, when the fit fails or does not converge,
    or when its slope is not positive.

    Parameters
    ----------
    x : FloatArray
        Logit scores of the validated clips.
    y : IntArray
        Outcomes of the validated clips: 1 if correct, 0 if not.
    p_target : float
        Target probability that a prediction is correct.
    sensitivity : float
        BirdNET sensitivity, used to convert thresholds back to confidence scores.
    n_bootstrap : int
        Number of resamples.
    rng : np.random.Generator
        Random number generator, so that results can be reproduced.

    Returns
    -------
    tuple of float
        Lower and upper bound of the interval, on the confidence scale. Both are NaN if every
        resample was skipped.
    """
    thresholds = []
    for _ in range(n_bootstrap):
        sample = rng.integers(0, len(x), len(x))
        x_sample = x[sample]
        y_sample = y[sample]
        if y_sample.min() == y_sample.max():
            continue

        with warnings.catch_warnings():
            # Turn these warnings into errors, so that unreliable fits are skipped below.
            warnings.simplefilter("error", PerfectSeparationWarning)
            warnings.simplefilter("error", ConvergenceWarning)
            try:
                fit = fit_logistic(x_sample, y_sample)
            except (PerfectSeparationWarning, ConvergenceWarning, np.linalg.LinAlgError):
                continue

        if fit.beta1 > 0:
            thresholds.append(float(to_confidence(fit.threshold(p_target), sensitivity)))

    if not thresholds:
        return np.nan, np.nan
    low, high = np.percentile(thresholds, [2.5, 97.5])
    return float(low), float(high)
