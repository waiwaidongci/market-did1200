import logging
import time
from pathlib import Path
from src.services.bound_runs import claim_bound, execute_bound
from src.services.execution import claim, execute, materialize_due
from src.utils.wakeup import wait

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
heartbeat = Path('/tmp/analysis-heartbeat')


def main():
    while True:
        try:
            materialize_due()
            lease = claim()
            if lease:
                execute(lease)
            else:
                bound_lease = claim_bound()
                if bound_lease:
                    execute_bound(bound_lease)
                else:
                    wait()
            heartbeat.touch()
        except Exception:
            log.exception('Worker cycle failed')
            time.sleep(2)


if __name__ == '__main__':
    main()
