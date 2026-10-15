"""Label every BirdNET prediction as an observation or not."""

import numpy as np
import pandas as pd

from natural_state.birds.regression import logistic, to_logit
from natural_state.birds.settings import Settings
from natural_state.birds.thresholds import Status

THRESHOLD_COLUMNS = [
    "status",
    "confidence_threshold",
    "beta0",
    "beta1",
    "precision_estimate",
    "min_validated_conf",
]
"""Columns of the thresholds table that are needed to label predictions."""


def label_predictions(predictions: pd.DataFrame, thresholds: pd.DataFrame, settings: Settings) -> pd.DataFrame:
    """Label each prediction as an observation or not.

    Parameters
    ----------
    predictions : pd.DataFrame
        BirdNET predictions with columns ``common_name`` and ``confidence``.
    thresholds : pd.DataFrame
        Output of `thresholds_table`, one row per species.
    settings : Settings
        Pipeline parameters.

    Returns
    -------
    pd.DataFrame
        A copy of the predictions with three new columns:

        - ``p_correct``: modelled probability that the prediction is correct. Empty when there is no model.
        - ``threshold_status``: how the species threshold was decided.
        - ``observation``: the species name if the confidence is at or above the species threshold,
          otherwise empty.
    """
    species = predictions.join(thresholds.set_index("common_name")[THRESHOLD_COLUMNS], on="common_name")
    confidence = species["confidence"]

    # Species with a logistic fit: read the probability off the fitted curve.
    logit_score = to_logit(confidence.to_numpy(dtype=np.float64), settings.sensitivity, settings.clip)
    beta0 = species["beta0"].to_numpy(dtype=np.float64)
    beta1 = species["beta1"].to_numpy(dtype=np.float64)
    is_logistic = species["status"] == Status.LOGISTIC_FIT

    # Score-independent species: one precision, but only inside the validated score range.
    in_validated_range = (species["status"] == Status.SCORE_INDEPENDENT) & (confidence >= species["min_validated_conf"])

    p_correct = np.select(
        [is_logistic, in_validated_range],
        [logistic(beta0 + beta1 * logit_score), species["precision_estimate"].to_numpy(dtype=np.float64)],
        default=np.nan,
    )

    # Below the threshold, or without a threshold, a prediction is not an observation.
    is_observation = species["confidence_threshold"].notna() & (confidence >= species["confidence_threshold"])

    result = predictions.copy()
    result["p_correct"] = p_correct
    result["threshold_status"] = species["status"]
    result["observation"] = predictions["common_name"].where(is_observation)
    return result


def summarise(labelled: pd.DataFrame, thresholds: pd.DataFrame) -> pd.DataFrame:
    """Count predictions and observations per species.

    Parameters
    ----------
    labelled : pd.DataFrame
        Output of `label_predictions`.
    thresholds : pd.DataFrame
        Output of `thresholds_table`.

    Returns
    -------
    pd.DataFrame
        One row per species, indexed by ``common_name``, with the number of predictions and observations,
        the threshold status and value, and the share of predictions accepted.
    """
    counts = labelled.groupby("common_name").agg(
        predictions=("common_name", "size"),
        observations=("observation", "count"),
    )
    species_info = thresholds.set_index("common_name")[["status", "confidence_threshold"]]
    summary = counts.join(species_info)
    summary["share_accepted"] = (summary["observations"] / summary["predictions"]).round(3)
    return summary
