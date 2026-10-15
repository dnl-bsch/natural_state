"""Parameters of the bird pipeline. On the platform these would be per-project settings."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Parameters that control how thresholds are decided.

    Attributes
    ----------
    p_target : float
        Required probability that an accepted prediction is correct.
    sensitivity : float
        BirdNET sensitivity. Must match the sensitivity used in the BirdNET run.
    min_validations : int
        Minimum number of validated clips before any threshold is set for a species.
    alpha : float
        Significance level for the test that the score is related to correctness.
    clip : float
        Confidence is reported with 4 decimals. Clipping to ``[clip, 1 - clip]`` keeps the logit
        finite at 0 and 1.
    prediction_columns : frozenset of str
        Columns the predictions file must contain.
    validation_columns : frozenset of str
        Columns the validations file must contain.
    """

    p_target: float = 0.99
    sensitivity: float = 1.0
    min_validations: int = 50
    alpha: float = 0.05
    clip: float = 1e-4
    prediction_columns: frozenset[str] = frozenset(
        {"common_name", "species_code", "confidence", "begin_path", "begin_time_s"}
    )
    validation_columns: frozenset[str] = frozenset({"commonName", "confidence", "outcome", "filename"})
