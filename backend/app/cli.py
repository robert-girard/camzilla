from .config import get_settings
from .validation import missing_configuration


def main() -> int:
    missing = missing_configuration(get_settings())
    if missing:
        print("Missing configuration: " + ", ".join(missing))
        return 1
    print("Configuration is present.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
