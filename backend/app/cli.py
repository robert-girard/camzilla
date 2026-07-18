import argparse

from .config import get_settings
from .validation import missing_configuration


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Camzilla configuration without values.")
    parser.add_argument(
        "--camera", action="store_true", help="require physical-camera configuration"
    )
    args = parser.parse_args()
    missing = missing_configuration(get_settings(), require_camera=args.camera)
    if missing:
        print("Missing configuration: " + ", ".join(missing))
        return 1
    print("Configuration is present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
