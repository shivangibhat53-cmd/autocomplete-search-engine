"""
Pipeline scheduler — runs the ingestion pipeline on a schedule.

Simulates:
  Real-time (every 5 min) → Kafka consumer
  Nightly batch           → Spark job on S3 logs

Here we use asyncio to run periodically.
In production you'd use:
  - Celery + Redis for task queuing
  - Apache Airflow for complex DAGs
  - Kubernetes CronJob for scheduled runs
"""
import asyncio
import os
from datetime import datetime
from src.pipeline.ingestion import run_pipeline

# How often to run in minutes
REALTIME_INTERVAL_MINUTES = int(
    os.getenv("PIPELINE_INTERVAL_MINUTES", "5")
)

LOG_FILEPATH  = os.getenv("LOG_FILEPATH",  "data/search_logs.csv")
API_BASE_URL  = os.getenv("API_BASE_URL",  "http://localhost:8000")


async def run_scheduler() -> None:
    """
    Run the pipeline on a schedule forever.

    First run is immediate on startup.
    Subsequent runs happen every REALTIME_INTERVAL_MINUTES.
    """
    print(f"Pipeline scheduler starting...")
    print(f"  Interval : every {REALTIME_INTERVAL_MINUTES} minutes")
    print(f"  Log file : {LOG_FILEPATH}")
    print(f"  API URL  : {API_BASE_URL}")

    run_count = 0

    while True:
        run_count += 1
        print(f"\n[Run #{run_count}] "
              f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        try:
            result = await run_pipeline(
                log_filepath = LOG_FILEPATH,
                api_base_url = API_BASE_URL,
            )
            print(f"[Run #{run_count}] Complete: {result}")

        except Exception as e:
            print(f"[Run #{run_count}] Pipeline failed: {e}")
            import traceback
            traceback.print_exc()

        # Wait for next run
        interval_seconds = REALTIME_INTERVAL_MINUTES * 60
        print(f"\nNext run in {REALTIME_INTERVAL_MINUTES} minutes...")
        await asyncio.sleep(interval_seconds)


if __name__ == "__main__":
    asyncio.run(run_scheduler())