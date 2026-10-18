from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import storage


class InputValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def new_editor_values() -> dict[str, Any]:
    now = datetime.now().astimezone()
    return {
        "task_id": None,
        "title": "",
        "description": "",
        "promised_at": now.isoformat(timespec="seconds"),
        "deadline": now.date().isoformat(),
        "updated_at": now.isoformat(timespec="seconds"),
    }


def _draft_date_error(draft: dict[str, Any]) -> str | None:
    try:
        promised_at = datetime.fromisoformat(draft["promised_at"])
        date.fromisoformat(draft["deadline"])
    except (TypeError, ValueError):
        return "черновик содержит некорректную дату обещания или дедлайн"
    if promised_at.tzinfo is None:
        return "в дате обещания черновика отсутствует часовой пояс"
    return None


def load_editor_values(
    draft_key: str,
    task: dict[str, Any] | None = None,
    data_dir: Path = storage.DATA_DIR,
) -> tuple[dict[str, Any], dict[str, str] | None]:
    draft, problem = storage.load_draft(draft_key, data_dir)
    if draft is not None:
        date_error = _draft_date_error(draft)
        if date_error is None:
            return draft, None
        problem = {"file": f"{draft_key}.json", "error": date_error}
    if draft_key == "new":
        return new_editor_values(), problem
    if task is None or task.get("id") != draft_key:
        raise ValueError("для редактора существующего дела нужны его данные")
    return {
        "task_id": task["id"],
        "title": task["title"],
        "description": task["description"],
        "promised_at": task["promised_at"],
        "deadline": task["deadline"],
        "updated_at": _now_iso(),
    }, problem


def save_editor_draft(
    draft_key: str,
    task_id: str | None,
    title: str,
    description: str,
    promised_at: str,
    deadline: str,
    data_dir: Path = storage.DATA_DIR,
) -> dict[str, Any]:
    draft = {
        "task_id": task_id,
        "title": title,
        "description": description,
        "promised_at": promised_at,
        "deadline": deadline,
        "updated_at": _now_iso(),
    }
    storage.save_draft(draft_key, draft, data_dir)
    return draft


def _validate_fields(values: dict[str, Any]) -> dict[str, str]:
    title = values.get("title")
    description = values.get("description")
    promised_at = values.get("promised_at")
    deadline = values.get("deadline")

    if not isinstance(title, str):
        raise InputValidationError("Название дела должно быть строкой.")
    if not isinstance(description, str):
        raise InputValidationError("Описание дела должно быть строкой.")
    title = title.strip()
    description = description.strip()
    if not title:
        raise InputValidationError("Введите название дела.")
    if not isinstance(promised_at, str):
        raise InputValidationError("Укажите дату и время обещания.")
    try:
        promised = datetime.fromisoformat(promised_at)
    except ValueError as error:
        raise InputValidationError("Укажите корректные дату и время обещания.") from error
    if promised.tzinfo is None:
        raise InputValidationError("Для времени обещания не указан часовой пояс.")
    if not isinstance(deadline, str):
        raise InputValidationError("Укажите дедлайн.")
    try:
        normalized_deadline = date.fromisoformat(deadline).isoformat()
    except ValueError as error:
        raise InputValidationError("Укажите корректный дедлайн.") from error

    return {
        "title": title,
        "description": description,
        "promised_at": promised.isoformat(timespec="seconds"),
        "deadline": normalized_deadline,
    }


def _delete_valid_draft(draft_key: str, data_dir: Path) -> None:
    draft, problem = storage.load_draft(draft_key, data_dir)
    if draft is not None and problem is None and _draft_date_error(draft) is None:
        storage.delete_draft(draft_key, data_dir)


def create_task(
    values: dict[str, Any], data_dir: Path = storage.DATA_DIR
) -> dict[str, Any]:
    fields = _validate_fields(values)
    task = {
        "id": str(uuid4()),
        **fields,
        "status": "open",
        "completed_at": None,
        "comments": [],
    }
    storage.save_task(task, data_dir)
    _delete_valid_draft("new", data_dir)
    return task


def update_task(
    task: dict[str, Any],
    values: dict[str, Any],
    data_dir: Path = storage.DATA_DIR,
) -> dict[str, Any]:
    fields = _validate_fields(values)
    updated_task = deepcopy(task)
    updated_task.update(fields)
    storage.save_task(updated_task, data_dir)
    _delete_valid_draft(updated_task["id"], data_dir)
    return updated_task


def close_task(
    task: dict[str, Any], data_dir: Path = storage.DATA_DIR
) -> dict[str, Any]:
    if task.get("status") == "completed":
        return deepcopy(task)
    completed_task = deepcopy(task)
    completed_task["status"] = "completed"
    completed_task["completed_at"] = _now_iso()
    storage.save_task(completed_task, data_dir)
    return completed_task
