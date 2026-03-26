"""
Tests for shared arr Pydantic models (arr_models.py).

Verifies camelCase → snake_case mapping, required-field validation,
and default values for ArrQueue and ArrHistory.
"""

from datetime import datetime

import pytest
from pydantic import ValidationError

from movieseer.aggregator.services.arr_models import (
    ArrHistory,
    ArrQueue,
    StatusMessage,
)

# Minimal camelCase dicts that satisfy all required fields.
_QUALITY = {"quality": {"name": "HD-1080p", "resolution": 1080}}

_MINIMAL_QUEUE = {
    "quality": _QUALITY,
    "size": 1000.0,
    "title": "A Film",
    "status": "downloading",
}

_MINIMAL_HISTORY = {
    "sourceTitle": "A.Film.2024",
    "quality": _QUALITY,
    "qualityCutoffNotMet": False,
    "date": "2024-01-01T00:00:00Z",
    "eventType": "grabbed",
}


class TestArrQueue:
    """ArrQueue validates camelCase arr API queue records."""

    def test_minimal_dict_parses(self):
        q = ArrQueue.model_validate(_MINIMAL_QUEUE)
        assert q.title == "A Film"
        assert q.size == 1000.0
        assert q.status == "downloading"

    def test_camel_to_snake_conversion(self):
        q = ArrQueue.model_validate(
            {
                **_MINIMAL_QUEUE,
                "trackedDownloadStatus": "Warning",
                "downloadId": "abc123",
                "downloadClient": "SABnzbd",
                "sizeLeft": 500.0,
            }
        )
        assert q.tracked_download_status == "Warning"
        assert q.download_id == "abc123"
        assert q.download_client == "SABnzbd"

    def test_defaults_applied(self):
        q = ArrQueue.model_validate(_MINIMAL_QUEUE)
        assert q.languages == []
        assert q.status_messages == []
        assert q.tracked_download_status == "Ok"
        assert q.sizeleft == 0.0
        assert q.download_id is None
        assert q.download_client is None
        assert q.indexer is None
        assert q.error_message is None

    def test_status_messages_parsed(self):
        q = ArrQueue.model_validate(
            {
                **_MINIMAL_QUEUE,
                "statusMessages": [{"messages": ["No files found", "Try again"]}],
            }
        )
        assert len(q.status_messages) == 1
        assert isinstance(q.status_messages[0], StatusMessage)
        assert q.status_messages[0].messages == ["No files found", "Try again"]

    def test_status_message_default_is_empty_list(self):
        sm = StatusMessage.model_validate({})
        assert sm.messages == []

    def test_missing_required_field_raises(self):
        with pytest.raises(ValidationError):
            ArrQueue.model_validate({"title": "A Film", "status": "downloading"})


class TestArrHistory:
    """ArrHistory validates camelCase arr API history records."""

    def test_minimal_dict_parses(self):
        h = ArrHistory.model_validate(_MINIMAL_HISTORY)
        assert h.source_title == "A.Film.2024"
        assert h.event_type == "grabbed"
        assert h.quality_cutoff_not_met is False

    def test_date_parsed_as_datetime(self):
        h = ArrHistory.model_validate(_MINIMAL_HISTORY)
        assert isinstance(h.date, datetime)

    def test_data_defaults_to_empty_dict(self):
        h = ArrHistory.model_validate(_MINIMAL_HISTORY)
        assert h.data == {}

    def test_data_field_populated(self):
        h = ArrHistory.model_validate(
            {
                **_MINIMAL_HISTORY,
                "data": {"message": "Timeout", "reason": "retry"},
            }
        )
        assert h.data["message"] == "Timeout"

    def test_download_id_optional(self):
        h = ArrHistory.model_validate({**_MINIMAL_HISTORY, "downloadId": "xyz789"})
        assert h.download_id == "xyz789"

    def test_invalid_event_type_raises(self):
        with pytest.raises(ValidationError):
            ArrHistory.model_validate({**_MINIMAL_HISTORY, "eventType": "notARealEvent"})
