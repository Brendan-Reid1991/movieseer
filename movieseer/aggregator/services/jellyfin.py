from __future__ import annotations

from typing import Literal, cast

from movieseer.aggregator.services.base import _BaseServiceClient
from movieseer.config import JELLYFIN_API_KEY, JELLYFIN_URL

TaskState = Literal["Idle", "Running", "Cancelling"]
_LIBRARY_SCAN_KEY = "RefreshLibrary"


class JellyfinClient(_BaseServiceClient):
    """Jellyfin API client. 

    Only required to trigger library refreshes and to track the status.
    """    

    BASE_URL = JELLYFIN_URL
    _API_PREFIX = ""

    def __init__(self) -> None:
        super().__init__(headers={"X-Emby-Token": JELLYFIN_API_KEY})

    async def _task_id(self, key: str) -> str:
        tasks = await self._get("/ScheduledTasks")
        assert isinstance(tasks, list)
        for task in tasks:
            if isinstance(task, dict) and task.get("Key") == key:
                return str(task["Id"])
        raise ValueError(f"No scheduled task with key {key!r}")

    async def start_refresh(self) -> str:
        task_id = await self._task_id(_LIBRARY_SCAN_KEY)
        await self._post(f"/ScheduledTasks/Running/{task_id}")
        return task_id

    async def refresh_state(self, task_id: str) -> TaskState:
        data = await self._get(f"/ScheduledTasks/{task_id}")
        assert isinstance(data, dict)
        return cast(TaskState, data["State"])
