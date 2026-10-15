"""Logistic regression of prediction correctness on the BirdNET logit score."""

from dataclasses import dataclass

import numpy as np
import numpy.typing as npt
import statsmodels.api as sm

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
