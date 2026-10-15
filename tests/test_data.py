from pathlib import Path

import pandas as pd
import pytest

from natural_state.birds.data import load_validations
from natural_state.birds.settings import Settings


def write_validations(path: Path, **overrides: object) -> Path:
    columns: dict[str, object] = {
        "commonName": ["Bird A", "Bird A"],
        "confidence": [0.2, 0.9],
        "outcome": [0, 1],
        "filename": ["a.wav", "b.wav"],
    }
    columns.update(overrides)
    file = path / "validation_results.csv"
    pd.DataFrame(columns).to_csv(file, index=False)
    return file


def test_valid_file_loads(tmp_path: Path) -> None:
    assert len(load_validations(write_validations(tmp_path), Settings())) == 2


def test_missing_column_is_reported(tmp_path: Path) -> None:
    file = write_validations(tmp_path)
    pd.read_csv(file).drop(columns="outcome").to_csv(file, index=False)
    with pytest.raises(ValueError, match="missing columns \\['outcome'\\]"):
        load_validations(file, Settings())


def test_confidence_outside_zero_to_one_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="confidence"):
        load_validations(write_validations(tmp_path, confidence=[0.2, 1.5]), Settings())


def test_outcome_other_than_zero_or_one_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="outcome"):
        load_validations(write_validations(tmp_path, outcome=[0, 2]), Settings())
