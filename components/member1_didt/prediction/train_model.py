"""Train the DIDT one-day milk-yield model from approved Farm X core records."""
import argparse
from pathlib import Path

from components.member1_didt.prediction.model_training import train_from_farmx


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="Destination for the fitted model artifact")
    args = parser.parse_args()
    result = train_from_farmx(args.output)
    print(result)


if __name__ == "__main__":
    main()
