"""Load the BirdNET predictions and the ornithologist validations, and check their contents."""

from pathlib import Path

import pandas as pd

from natural_state.birds.settings import Settings


def load_predictions(path: Path, settings: Settings) -> pd.DataFrame:
    """Read and check the BirdNET predictions export.

    Parameters
    ----------
    path : Path
        CSV file with one row per 3-second clip and its predicted species.
    settings : Settings
        Pipeline parameters. Its ``prediction_columns`` are the columns the file must contain.

    Returns
    -------
    pd.DataFrame
        The predictions, unchanged.

    Raises
    ------
    ValueError
        If a required column is missing or a confidence lies outside 0 to 1.
    """
    predictions = pd.read_csv(path)
    check_columns(predictions, settings.prediction_columns, "predictions")
    check_confidence(predictions, "predictions")
    return predictions


def load_validations(path: Path, settings: Settings) -> pd.DataFrame:
    """Read and check the validation results.

    Parameters
    ----------
    path : Path
        CSV file with one row per clip that an ornithologist marked correct (1) or not (0).
    settings : Settings
        Pipeline parameters. Its ``validation_columns`` are the columns the file must contain.

    Returns
    -------
    pd.DataFrame
        The validations, unchanged.

    Raises
    ------
    ValueError
        If a required column is missing, a confidence lies outside 0 to 1, or an outcome is not 0 or 1.
    """
    validations = pd.read_csv(path)
    check_columns(validations, settings.validation_columns, "validations")
    check_confidence(validations, "validations")

    outcomes = set(validations["outcome"].unique())
    if not outcomes <= {0, 1}:
        raise ValueError(f"validations: outcome must be 0 or 1, found {sorted(outcomes)}")
    return validations


def check_columns(table: pd.DataFrame, required: frozenset[str], name: str) -> None:
    """Check that a table has all required columns.

    Parameters
    ----------
    table : pd.DataFrame
        Table to check.
    required : frozenset of str
        Column names that must be present.
    name : str
        Name of the table, used in the error message.

    Raises
    ------
    ValueError
        If any required column is missing. The message lists the missing columns.
    """
    missing = required - set(table.columns)
    if missing:
        raise ValueError(f"{name}: missing columns {sorted(missing)}")


def check_confidence(table: pd.DataFrame, name: str) -> None:
    """Check that every confidence score lies between 0 and 1.

    Parameters
    ----------
    table : pd.DataFrame
        Table with a ``confidence`` column.
    name : str
        Name of the table, used in the error message.

    Raises
    ------
    ValueError
        If any confidence is below 0 or above 1.
    """
    if not table["confidence"].between(0, 1).all():
        raise ValueError(f"{name}: confidence must be between 0 and 1")
