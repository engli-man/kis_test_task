import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any
from uuid import UUID


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"


class InvalidDataError(ValueError):
    pass


def _storage_paths(data_dir: Path) -> tuple[Path, Path]:
    return data_dir / "tasks", data_dir / "drafts"


def init_storage(data_dir: Path = DATA_DIR) -> None:
    tasks_dir, drafts_dir = _storage_paths(data_dir)
    tasks_dir.mkdir(parents=True, exist_ok=True)
    drafts_dir.mkdir(parents=True, exist_ok=True)


def _is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        return False
    return str(parsed) == value


def _is_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _is_date(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        date.fromisoformat(value)
    except ValueError:
        return False
    return True


def validate_task(task: Any) -> None:
    if not isinstance(task, dict):
        raise InvalidDataError("корневая структура должна быть объектом")

    required_types = {
        "id": str,
        "title": str,
        "description": str,
        "promised_at": str,
        "deadline": str,
        "status": str,
        "comments": list,
    }
    for field, expected_type in required_types.items():
        if field not in task:
            raise InvalidDataError(f"отсутствует поле '{field}'")
        if not isinstance(task[field], expected_type):
            raise InvalidDataError(f"поле '{field}' имеет неверный тип")

    if "completed_at" not in task:
        raise InvalidDataError("отсутствует поле 'completed_at'")
    if not _is_uuid(task["id"]):
        raise InvalidDataError("поле 'id' не является UUID")
    if not task["title"].strip():
        raise InvalidDataError("поле 'title' не должно быть пустым")
    if not _is_datetime(task["promised_at"]):
        raise InvalidDataError("поле 'promised_at' должно содержать дату, время и часовой пояс")
    if not _is_date(task["deadline"]):
        raise InvalidDataError("поле 'deadline' должно содержать дату ISO 8601")
    if task["status"] not in {"open", "completed"}:
        raise InvalidDataError("поле 'status' должно быть 'open' или 'completed'")

    completed_at = task["completed_at"]
    if task["status"] == "open" and completed_at is not None:
        raise InvalidDataError("у открытого дела 'completed_at' должно быть null")
    if task["status"] == "completed" and not _is_datetime(completed_at):
        raise InvalidDataError("у завершённого дела должна быть дата завершения")

    for index, comment in enumerate(task["comments"]):
        if not isinstance(comment, dict):
            raise InvalidDataError(f"комментарий {index + 1} должен быть объектом")
        for field in ("id", "text", "created_at"):
            if field not in comment or not isinstance(comment[field], str):
                raise InvalidDataError(
                    f"поле '{field}' комментария {index + 1} отсутствует или имеет неверный тип"
                )
        if not _is_uuid(comment["id"]):
            raise InvalidDataError(f"id комментария {index + 1} не является UUID")
        if not _is_datetime(comment["created_at"]):
            raise InvalidDataError(f"время комментария {index + 1} имеет неверный формат")


def validate_draft(draft: Any) -> None:
    if not isinstance(draft, dict):
        raise InvalidDataError("корневая структура черновика должна быть объектом")

    expected_types = {
        "title": str,
        "description": str,
        "promised_at": str,
        "deadline": str,
        "updated_at": str,
    }
    if "task_id" not in draft:
        raise InvalidDataError("в черновике отсутствует поле 'task_id'")
    if draft["task_id"] is not None and not _is_uuid(draft["task_id"]):
        raise InvalidDataError("поле 'task_id' черновика не является UUID")
    for field, expected_type in expected_types.items():
        if field not in draft or not isinstance(draft[field], expected_type):
            raise InvalidDataError(f"поле '{field}' черновика отсутствует или имеет неверный тип")
    if not _is_datetime(draft["updated_at"]):
        raise InvalidDataError("поле 'updated_at' черновика имеет неверный формат")


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(data, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except Exception:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def save_task(task: dict[str, Any], data_dir: Path = DATA_DIR) -> Path:
    validate_task(task)
    init_storage(data_dir)
    tasks_dir, _ = _storage_paths(data_dir)
    path = tasks_dir / f"{task['id']}.json"
    if path.exists():
        try:
            load_task(path)
        except (OSError, UnicodeError, json.JSONDecodeError, InvalidDataError) as error:
            raise InvalidDataError(
                f"существующий файл '{path.name}' повреждён и не будет перезаписан: {error}"
            ) from error
    _atomic_write_json(path, task)
    return path


def load_task(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as source:
        task = json.load(source)
    validate_task(task)
    if path.stem != task["id"]:
        raise InvalidDataError("имя файла не совпадает с id дела")
    return task


def load_tasks(data_dir: Path = DATA_DIR) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    init_storage(data_dir)
    tasks_dir, _ = _storage_paths(data_dir)
    tasks: list[dict[str, Any]] = []
    problems: list[dict[str, str]] = []

    for path in sorted(tasks_dir.glob("*.json")):
        try:
            tasks.append(load_task(path))
        except (OSError, UnicodeError, json.JSONDecodeError, InvalidDataError) as error:
            problems.append({"file": path.name, "error": str(error)})
    return tasks, problems


def _validate_draft_key(draft_key: str) -> None:
    if draft_key != "new" and not _is_uuid(draft_key):
        raise ValueError("ключ черновика должен быть 'new' или UUID")


def save_draft(
    draft_key: str, draft: dict[str, Any], data_dir: Path = DATA_DIR
) -> Path:
    _validate_draft_key(draft_key)
    validate_draft(draft)
    if draft_key == "new" and draft["task_id"] is not None:
        raise InvalidDataError("у нового дела 'task_id' должно быть null")
    if draft_key != "new" and draft["task_id"] != draft_key:
        raise InvalidDataError("ключ черновика не совпадает с 'task_id'")
    init_storage(data_dir)
    _, drafts_dir = _storage_paths(data_dir)
    path = drafts_dir / f"{draft_key}.json"
    if path.exists():
        _, problem = load_draft(draft_key, data_dir)
        if problem is not None:
            raise InvalidDataError(
                f"существующий файл '{path.name}' повреждён и не будет перезаписан: "
                f"{problem['error']}"
            )
    _atomic_write_json(path, draft)
    return path


def load_draft(
    draft_key: str, data_dir: Path = DATA_DIR
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    _validate_draft_key(draft_key)
    init_storage(data_dir)
    _, drafts_dir = _storage_paths(data_dir)
    path = drafts_dir / f"{draft_key}.json"
    if not path.exists():
        return None, None
    try:
        with path.open(encoding="utf-8") as source:
            draft = json.load(source)
        validate_draft(draft)
        if draft_key == "new" and draft["task_id"] is not None:
            raise InvalidDataError("у нового дела 'task_id' должно быть null")
        if draft_key != "new" and draft["task_id"] != draft_key:
            raise InvalidDataError("ключ черновика не совпадает с 'task_id'")
        return draft, None
    except (OSError, UnicodeError, json.JSONDecodeError, InvalidDataError) as error:
        return None, {"file": path.name, "error": str(error)}


def delete_draft(draft_key: str, data_dir: Path = DATA_DIR) -> None:
    _validate_draft_key(draft_key)
    _, drafts_dir = _storage_paths(data_dir)
    (drafts_dir / f"{draft_key}.json").unlink(missing_ok=True)
