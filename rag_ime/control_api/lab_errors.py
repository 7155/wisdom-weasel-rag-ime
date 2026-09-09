"""Translate Lab failures into the existing HTTP status and JSON receipts.

Route descriptors select these adapters. They receive only an exception, never
an HTTP handler or an application service. Legacy command and App routes reuse
the same adapters until their transport is migrated separately.
"""

from __future__ import annotations

import sqlite3
from http import HTTPStatus


__all__ = [
    "lab_trial_error_response",
    "lab_golden_error_response",
    "lab_project_error_response",
    "lab_scene_recipe_error_response",
]


def lab_scene_recipe_error_response(
    exc: Exception,
) -> tuple[HTTPStatus, dict[str, object]]:
    from ..agent_lab.scene_recipes import (
        AgentLabSceneRecipeConflict,
        AgentLabSceneRecipeServiceUnavailable,
        AgentLabSceneRecipeUnavailable,
    )

    if isinstance(
        exc,
        (
            AgentLabSceneRecipeConflict,
            AgentLabSceneRecipeUnavailable,
            AgentLabSceneRecipeServiceUnavailable,
        ),
    ):
        return HTTPStatus(exc.http_status), exc.response_payload()
    if isinstance(exc, (sqlite3.Error, OSError)):
        unavailable = AgentLabSceneRecipeServiceUnavailable("storage_unavailable")
        return HTTPStatus.SERVICE_UNAVAILABLE, unavailable.response_payload()
    if isinstance(exc, ValueError):
        return HTTPStatus.BAD_REQUEST, {
            "ok": False,
            "code": "AGENT_LAB_SCENE_RECIPE_INVALID_REQUEST",
            "error": "场景操作参数无效，请核对后重试。",
        }
    return HTTPStatus.INTERNAL_SERVER_ERROR, {
        "ok": False,
        "code": "AGENT_LAB_SCENE_RECIPE_INTERNAL_ERROR",
        "error": "场景配置服务暂不可用，请刷新查看状态。",
    }


def lab_trial_error_response(exc: Exception) -> tuple[HTTPStatus, dict[str, object]]:
    from ..agent_lab.trials import (
        AgentLabTrialConflict,
        AgentLabTrialNotFound,
        AgentLabTrialServiceUnavailable,
    )

    if isinstance(exc, (AgentLabTrialConflict, AgentLabTrialServiceUnavailable)):
        return HTTPStatus(exc.http_status), exc.response_payload()
    if isinstance(exc, AgentLabTrialNotFound):
        return HTTPStatus.NOT_FOUND, {
            "ok": False,
            "code": "AGENT_LAB_TRIAL_NOT_FOUND",
            "error": "未找到这次场景试验。",
        }
    if isinstance(exc, (sqlite3.Error, OSError)):
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "ok": False,
            "code": "AGENT_LAB_TRIAL_UNAVAILABLE",
            "error": "场景试验暂时无法读取或保存，请保留原请求后重试。",
        }
    if isinstance(exc, (TypeError, ValueError)):
        return HTTPStatus.UNPROCESSABLE_ENTITY, {
            "ok": False,
            "code": "AGENT_LAB_TRIAL_INVALID_REQUEST",
            "error": "场景试验参数无效，请核对后重试。",
        }
    return HTTPStatus.INTERNAL_SERVER_ERROR, {
        "ok": False,
        "code": "AGENT_LAB_TRIAL_INTERNAL_ERROR",
        "error": "场景试验服务暂时不可用；已保存的执行记录仍会保留。",
    }


def lab_project_error_response(exc: Exception) -> tuple[HTTPStatus, dict[str, object]]:
    from ..agent_lab.projects import (
        AgentLabProjectValidationError,
        AgentLabProjectUnavailable,
    )

    if isinstance(exc, AgentLabProjectValidationError):
        return HTTPStatus(exc.http_status), exc.response_payload()
    if isinstance(exc, (sqlite3.Error, OSError)):
        return (
            HTTPStatus.SERVICE_UNAVAILABLE,
            AgentLabProjectUnavailable().response_payload(),
        )
    if isinstance(exc, ValueError):
        return HTTPStatus.UNPROCESSABLE_ENTITY, {
            "ok": False,
            "code": "AGENT_LAB_PROJECT_INVALID_REQUEST",
            "message": "项目操作参数无效，请核对后重试。",
        }
    return HTTPStatus.INTERNAL_SERVER_ERROR, {
        "ok": False,
        "code": "AGENT_LAB_PROJECT_INTERNAL_ERROR",
        "message": "项目服务暂时不可用；已保存的成果仍会保留。",
    }


def lab_golden_error_response(exc: Exception) -> tuple[HTTPStatus, dict[str, object]]:
    from ..agent_lab.golden import (
        AgentLabGoldenConflict,
        AgentLabGoldenServiceUnavailable,
        AgentLabGoldenValidationError,
    )

    if isinstance(
        exc,
        (
            AgentLabGoldenConflict,
            AgentLabGoldenServiceUnavailable,
            AgentLabGoldenValidationError,
        ),
    ):
        return HTTPStatus(exc.http_status), exc.response_payload()
    if isinstance(exc, (sqlite3.Error, OSError)):
        return HTTPStatus.SERVICE_UNAVAILABLE, {
            "ok": False,
            "code": "AGENT_LAB_GOLDEN_UNAVAILABLE",
            "message": "评测集暂时无法读取或保存，请稍后重试。",
        }
    if isinstance(exc, ValueError):
        return HTTPStatus.UNPROCESSABLE_ENTITY, {
            "ok": False,
            "code": "AGENT_LAB_GOLDEN_INVALID_REQUEST",
            "message": "评测操作参数无效，请核对后重试。",
        }
    return HTTPStatus.INTERNAL_SERVER_ERROR, {
        "ok": False,
        "code": "AGENT_LAB_GOLDEN_INTERNAL_ERROR",
        "message": "评测服务暂时不可用；已保存的记录仍会保留。",
    }
