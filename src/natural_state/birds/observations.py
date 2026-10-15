"""Label every BirdNET prediction as an observation or not."""

import numpy as np
import pandas as pd

from natural_state.birds.regression import logistic, to_logit
from natural_state.birds.settings import Settings
from natural_state.birds.thresholds import Status

THRESHOLD_COLUMNS = [
    "common_name",
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
    labelled = predictions.merge(thresholds[THRESHOLD_COLUMNS], on="common_name", how="left")
    confidence = labelled["confidence"]

    p_correct = pd.Series(np.nan, index=labelled.index)

    # Species with a logistic fit: read the probability off the fitted curve.
    is_logistic = labelled["status"] == Status.LOGISTIC_FIT
    logit_score = to_logit(confidence.to_numpy(dtype=np.float64), settings.sensitivity, settings.clip)
    beta0 = labelled["beta0"].to_numpy(dtype=np.float64)
    beta1 = labelled["beta1"].to_numpy(dtype=np.float64)
    p_from_curve = logistic(beta0 + beta1 * logit_score)
    p_correct[is_logistic] = p_from_curve[is_logistic.to_numpy()]

    # Score-independent species: one precision, but only inside the validated score range.
    in_validated_range = (labelled["status"] == Status.SCORE_INDEPENDENT) & (
        confidence >= labelled["min_validated_conf"]
    )
    p_correct[in_validated_range] = labelled.loc[in_validated_range, "precision_estimate"]

    # Below the threshold, or without a threshold, a prediction is not an observation.
    is_observation = labelled["confidence_threshold"].notna() & (confidence >= labelled["confidence_threshold"])

    # A left merge keeps the row order of the predictions, so the new columns can be copied as arrays.
    result = predictions.copy()
    result["p_correct"] = p_correct.to_numpy()
    result["threshold_status"] = labelled["status"].to_numpy()
    result["observation"] = labelled["common_name"].where(is_observation).to_numpy()
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
