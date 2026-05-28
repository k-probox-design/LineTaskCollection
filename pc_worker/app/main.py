from app import config, orchestrator


def main() -> None:
    config.setup_logging()
    orchestrator.run_once()


if __name__ == "__main__":
    main()
