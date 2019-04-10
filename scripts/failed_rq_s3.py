#!/usr/bin/env python3
import time
from redis import Redis
from rq import push_connection, Queue
from s3_copy_file import timecheck


def main_loop():
    conn = Redis(host='redis', port=6379)
    push_connection(conn)
    lq = Queue("low", connection=conn, default_timeout=600)  # put long timeout
    hq = Queue("high", connection=conn)
    starttime = time.time()
    registry = hq.failed_job_registry
    while True:
        # todo check for network status
        if(timecheck()):
            if(len(registry) > 0):
                for job_id in registry.get_job_ids():
                    print("requeue failed job")
                    print(job_id)
                    lq.enqueue_job(job_id)
                    #registry.requeue(job_id)
        time.sleep(60.0 - ((time.time() - starttime) % 60.0))


main_loop()
