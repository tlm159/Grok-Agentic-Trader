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
        # Smart Sleep: Align to the next cycle mark (e.g., :00, :30)
        # This ensures we hit 15:30 market open precisely even if started at 15:26
        from datetime import datetime, timedelta
        
        now = datetime.now()
        cycle = int(default_minutes)
        if cycle < 1: cycle = 1
        
        # Calculate minutes to next grid point
        # Example: cycle=30, now=15:26 -> remainder=26 -> wait=4 -> target 15:30
        remainder = now.minute % cycle
        wait_minutes = cycle - remainder
        
        # Calculate target time (zero seconds)
        target = now + timedelta(minutes=wait_minutes)
        target = target.replace(second=0, microsecond=0)
        
        seconds_to_sleep = (target - now).total_seconds()
        
        # Safety buffering
        if seconds_to_sleep < 1:
            seconds_to_sleep += 60 # wait at least a minute if we are literally on the edge
            
        print(f"⏳ Waiting {int(seconds_to_sleep)}s until {target.strftime('%H:%M:%S')}...")
        time.sleep(seconds_to_sleep)


if __name__ == "__main__":
    run_loop()
