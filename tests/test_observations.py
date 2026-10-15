import pandas as pd

from natural_state.birds.observations import label_predictions
from natural_state.birds.settings import Settings
from natural_state.birds.thresholds import SpeciesThreshold, Status, thresholds_table


def test_only_predictions_at_or_above_the_threshold_become_observations() -> None:
    thresholds = thresholds_table(
        [
            SpeciesThreshold(
                "Bird A",
                Status.LOGISTIC_FIT,
                beta0=0.0,
                beta1=1.0,
                confidence_threshold=0.8,
                min_validated_conf=0.1,
            ),
            SpeciesThreshold("Bird B", Status.INSUFFICIENT_VALIDATION, reason="no validated clips"),
        ]
    )
    predictions = pd.DataFrame(
        {"common_name": ["Bird A", "Bird A", "Bird A", "Bird B"], "confidence": [0.5, 0.8, 0.95, 0.99]}
    )

    labelled = label_predictions(predictions, thresholds, Settings())

    observation = labelled["observation"]
    assert pd.isna(observation.iloc[0])  # 0.5 is below the threshold of 0.8
    assert observation.iloc[1] == "Bird A"  # exactly at the threshold
    assert observation.iloc[2] == "Bird A"
    assert pd.isna(labelled["observation"].iloc[3])  # no threshold for Bird B
    assert pd.isna(labelled["p_correct"].iloc[3])


def test_score_independent_probability_applies_only_inside_the_validated_range() -> None:
    thresholds = thresholds_table(
        [
            SpeciesThreshold(
                "Bird A",
                Status.SCORE_INDEPENDENT,
                precision_estimate=0.995,
                confidence_threshold=0.3,
                min_validated_conf=0.3,
            )
        ]
    )
    predictions = pd.DataFrame({"common_name": ["Bird A", "Bird A"], "confidence": [0.2, 0.6]})

    labelled = label_predictions(predictions, thresholds, Settings())

    assert pd.isna(labelled["p_correct"].iloc[0])
    assert labelled["p_correct"].iloc[1] == 0.995
    assert pd.isna(labelled["observation"].iloc[0])
    assert labelled["observation"].iloc[1] == "Bird A"
