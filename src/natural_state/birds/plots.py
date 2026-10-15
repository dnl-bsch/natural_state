"""Figure of the fitted curves, to check each species threshold by eye."""

import math

import numpy as np
import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.figure import Figure

from natural_state.birds.regression import LogisticFit, to_logit
from natural_state.birds.settings import Settings
from natural_state.birds.thresholds import SpeciesThreshold, Status

POINT_COLOR = "#4c6a92"
"""Colour of the validated clips."""

THRESHOLD_COLOR = "#c0392b"
"""Colour of the threshold line."""


def plot_calibration_curves(
    validations: pd.DataFrame,
    results: list[SpeciesThreshold],
    settings: Settings,
    rng: np.random.Generator,
) -> Figure:
    """Plot the validated clips and the fitted curve, one panel per validated species.

    Points are the validated clips, jittered vertically so they do not overlap. The black line is the
    fitted probability that a prediction is correct. The dashed line is ``p_target``, and the red line is
    the confidence threshold used for the species.

    Parameters
    ----------
    validations : pd.DataFrame
        Validated clips with columns ``commonName``, ``confidence`` and ``outcome``.
    results : list of SpeciesThreshold
        Threshold decisions. Species without validated clips are left out.
    settings : Settings
        Pipeline parameters.
    rng : np.random.Generator
        Random number generator for the vertical jitter.

    Returns
    -------
    Figure
        The figure, with two panels per row.
    """
    validated = [result for result in results if result.n_validated > 0]
    n_columns = 2
    n_rows = math.ceil(len(validated) / n_columns)
    fig, axes = plt.subplots(n_rows, n_columns, figsize=(10, 3.5 * n_rows), sharey=True, squeeze=False)

    for ax, result in zip(axes.flat, validated, strict=False):
        clips = validations[validations["commonName"] == result.common_name]
        x = to_logit(clips["confidence"].to_numpy(dtype=np.float64), settings.sensitivity, settings.clip)
        jitter = rng.uniform(-0.03, 0.03, len(x))
        ax.scatter(x, clips["outcome"] + jitter, s=12, alpha=0.4, color=POINT_COLOR)

        if result.status == Status.LOGISTIC_FIT:
            assert result.beta0 is not None and result.beta1 is not None
            fit = LogisticFit(result.beta0, result.beta1, p_slope=np.nan, aic=np.nan)
            # Also cover high scores, so that a threshold above the validated range stays visible.
            low, high = to_logit(np.array([0.1, 0.9999]), settings.sensitivity, settings.clip)
            grid = np.linspace(low, high, 200)
            ax.plot(grid, fit.probability(grid), color="black")
        elif result.status == Status.SCORE_INDEPENDENT:
            assert result.precision_estimate is not None
            ax.hlines(result.precision_estimate, x.min(), x.max(), color="black")

        if result.confidence_threshold is not None:
            threshold = to_logit(np.array([result.confidence_threshold]), settings.sensitivity, settings.clip)
            ax.axvline(float(threshold[0]), color=THRESHOLD_COLOR)

        ax.axhline(settings.p_target, linestyle="--", color="grey", linewidth=1)
        ax.set_title(f"{result.common_name}\n{result.status}", fontsize=10)
        ax.set_xlabel("logit(BirdNET confidence)")

    for ax in axes[:, 0]:
        ax.set_ylabel("pr(prediction correct)")
    for ax in axes.flat[len(validated) :]:
        ax.set_visible(False)

    fig.tight_layout()
    return fig
