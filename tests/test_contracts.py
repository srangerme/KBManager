from __future__ import annotations

import json

from kbmanager.contracts import ApiResult, ApiStatus


def test_api_result_serializes_to_stable_dict() -> None:
    result = ApiResult.success(
        "kb.test",
        warnings=["check input"],
        next_actions=["continue"],
    )

    assert result.to_dict() == {
        "status": "success",
        "operation": "kb.test",
        "objects": {"created": [], "updated": [], "deprecated": []},
        "diffs": [],
        "warnings": ["check input"],
        "errors": [],
        "review": {"required": False, "options": []},
        "next_actions": ["continue"],
    }
    assert json.loads(json.dumps(result.to_dict()))["status"] == ApiStatus.SUCCESS.value


def test_api_error_contains_required_fields() -> None:
    result = ApiResult.failed(
        "kb.test",
        "invalid_input",
        "Input is invalid",
        "Provide a valid object ID",
    )

    [error] = result.to_dict()["errors"]
    assert error == {
        "operation": "kb.test",
        "code": "invalid_input",
        "message": "Input is invalid",
        "suggestion": "Provide a valid object ID",
    }
