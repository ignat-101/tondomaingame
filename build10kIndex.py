from pathlib import Path

from tenkclub_service import build10kIndex


def main() -> None:
    output = Path(__file__).resolve().parent / "tenkclub-index.json"
    path = build10kIndex(output)
    print(path)


if __name__ == "__main__":
    main()
