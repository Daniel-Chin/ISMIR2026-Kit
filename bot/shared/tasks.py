"""Queue abstraction: ingress enqueues, worker consumes.

CloudTasksQueue is the production path (retries + concurrency limit come
from the queue's own settings). LocalQueue POSTs straight to the worker so
the whole flow runs on a laptop with LOCAL_MODE=1.
"""

import json
from typing import Any, Dict

import requests

from shared.config import settings


class LocalQueue:
    def __init__(self, worker_url: str):
        self.worker_url = worker_url.rstrip("/")

    def enqueue(self, payload: Dict[str, Any]) -> None:
        resp = requests.post(self.worker_url + "/task", json=payload, timeout=60)
        resp.raise_for_status()


class CloudTasksQueue:
    def __init__(self, queue_path: str, worker_url: str, sa_email: str):
        from google.cloud import tasks_v2  # imported lazily: not needed locally

        self.client = tasks_v2.CloudTasksClient()
        self.queue_path = queue_path
        self.worker_url = worker_url.rstrip("/")
        self.sa_email = sa_email

    def enqueue(self, payload: Dict[str, Any]) -> None:
        task = {
            "http_request": {
                "http_method": "POST",
                "url": self.worker_url + "/task",
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(payload).encode(),
                "oidc_token": {"service_account_email": self.sa_email},
            }
        }
        self.client.create_task(parent=self.queue_path, task=task)


def make_queue():
    if settings.local_mode:
        return LocalQueue(settings.worker_url or "http://localhost:8081")
    return CloudTasksQueue(
        settings.tasks_queue, settings.worker_url, settings.tasks_sa_email
    )
