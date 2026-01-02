import time

from config import load_config
from log_utils import append_run_log
from main import main


def run_loop():
    config = load_config()
    default_minutes = config["trading"].get("cycle_minutes", 60)
    run_log_path = config["paths"].get("run_log_path")
    while True:
        try:
            main()
        except Exception as exc:
            print(f"Loop error: {exc}")
            append_run_log(run_log_path, f"Loop error: {exc}")
        sleep_seconds = max(5, int(float(default_minutes) * 60))
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    run_loop()
