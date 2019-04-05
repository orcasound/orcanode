import time
import logging
from redis import Redis
from rq import push_connection, Queue, get_failed_queue


def main_loop():
    conn = Redis(host='redis', port=6379)
    push_connection(conn)
    lq = Queue("low", connection=conn, default_timeout=600)  # put long timeout
    starttime = time.time()
    fq = get_failed_queue()
    while True:
        # todo check for network status
        for job in fq.jobs:
            print("requeue failed job")
            print(job.id)
            lq.enqueue_job(job)
            fq.remove(job)
        time.sleep(60.0 - ((time.time() - starttime) % 60.0))


main_loop()
