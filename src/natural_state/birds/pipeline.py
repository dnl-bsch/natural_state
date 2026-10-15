"""Run the full bird pipeline: read inputs, decide thresholds, label predictions, write outputs.

Usage, from the repository root:

    uv run birds --raw-dir data/raw/birds --out-dir data/output/birds
"""

import argparse
from pathlib import Path

from natural_state.birds.data import load_predictions, load_validations
from natural_state.birds.observations import label_predictions, summarise
from natural_state.birds.plots import plot_calibration_curves
from natural_state.birds.settings import Settings
from natural_state.birds.thresholds import species_thresholds, thresholds_table


def run(raw_dir: Path, out_dir: Path, settings: Settings) -> None:
    """Run every step of the bird pipeline and write the outputs.

    Parameters
    ----------
    raw_dir : Path
        Folder with ``birdnet_predictions.csv`` and ``validation_results.csv``.
    out_dir : Path
        Folder for the outputs. It is created if needed and receives ``species_thresholds.csv``,
        ``birdnet_predictions_with_observation.csv``, ``observation_summary.csv`` and
        ``figures/bird_calibration_curves.png``.
    settings : Settings
        Pipeline parameters.
    """
    predictions = load_predictions(raw_dir / "birdnet_predictions.csv", settings)
    validations = load_validations(raw_dir / "validation_results.csv", settings)

    results = species_thresholds(validations, predictions["common_name"], settings)
    thresholds = thresholds_table(results)
    labelled = label_predictions(predictions, thresholds, settings)
    summary = summarise(labelled, thresholds)

    figures_dir = out_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)
    thresholds.to_csv(out_dir / "species_thresholds.csv", index=False)
    labelled.to_csv(out_dir / "birdnet_predictions_with_observation.csv", index=False)
    summary.to_csv(out_dir / "observation_summary.csv")

    fig = plot_calibration_curves(validations, results, settings)
    fig.savefig(figures_dir / "bird_calibration_curves.png", dpi=150)

    print(summary.to_string())
    print(f"\nwritten to {out_dir}")


def main() -> None:
    """Command-line entry point, installed as ``birds``.

    Reads ``--raw-dir``, ``--out-dir`` and ``--p-target`` from the command line and calls `run`.
    """
    parser = argparse.ArgumentParser(description="Turn BirdNET predictions into bird observations.")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw/birds"), help="folder with the input CSVs")
    parser.add_argument("--out-dir", type=Path, default=Path("data/output/birds"), help="folder for the outputs")
    parser.add_argument("--p-target", type=float, default=Settings.p_target, help="required probability correct")
    args = parser.parse_args()
    run(args.raw_dir, args.out_dir, Settings(p_target=args.p_target))


if __name__ == "__main__":
    main()
