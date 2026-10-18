import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import storage


def make_task(title: str = "Тестовое дело") -> dict:
    return {
        "id": str(uuid4()),
        "title": title,
        "description": "Описание",
        "promised_at": "2026-10-18T12:00:00+03:00",
        "deadline": "2026-10-25",
        "status": "open",
        "completed_at": None,
        "comments": [],
    }


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary_directory.name) / "data"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_init_storage_creates_directories(self) -> None:
        storage.init_storage(self.data_dir)

        self.assertTrue((self.data_dir / "tasks").is_dir())
        self.assertTrue((self.data_dir / "drafts").is_dir())

    def test_two_valid_tasks_load_when_third_file_is_corrupted(self) -> None:
        first = make_task("Первое")
        second = make_task("Второе")
        storage.save_task(first, self.data_dir)
        storage.save_task(second, self.data_dir)
        damaged_path = self.data_dir / "tasks" / "damaged.json"
        damaged_contents = '{"id": "оборванный JSON"'
        damaged_path.write_text(damaged_contents, encoding="utf-8")

        tasks, problems = storage.load_tasks(self.data_dir)

        self.assertEqual({task["id"] for task in tasks}, {first["id"], second["id"]})
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["file"], "damaged.json")
        self.assertEqual(damaged_path.read_text(encoding="utf-8"), damaged_contents)

    def test_valid_json_with_invalid_structure_is_reported(self) -> None:
        storage.init_storage(self.data_dir)
        path = self.data_dir / "tasks" / "invalid.json"
        contents = json.dumps({"id": "not-a-uuid", "title": 42})
        path.write_text(contents, encoding="utf-8")

        tasks, problems = storage.load_tasks(self.data_dir)

        self.assertEqual(tasks, [])
        self.assertEqual(problems[0]["file"], "invalid.json")
        self.assertEqual(path.read_text(encoding="utf-8"), contents)

    def test_save_task_replaces_file_without_leaving_temporary_files(self) -> None:
        task = make_task()
        path = storage.save_task(task, self.data_dir)
        task["description"] = "Обновлённое описание"

        storage.save_task(task, self.data_dir)

        self.assertEqual(storage.load_task(path), task)
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_save_task_does_not_replace_corrupted_existing_file(self) -> None:
        task = make_task()
        storage.init_storage(self.data_dir)
        path = self.data_dir / "tasks" / f"{task['id']}.json"
        contents = '{"damaged": true'
        path.write_text(contents, encoding="utf-8")

        with self.assertRaisesRegex(storage.InvalidDataError, "не будет перезаписан"):
            storage.save_task(task, self.data_dir)

        self.assertEqual(path.read_text(encoding="utf-8"), contents)

    def test_draft_round_trip_and_delete(self) -> None:
        task_id = str(uuid4())
        draft = {
            "task_id": task_id,
            "title": "Черновик",
            "description": "Ещё не сохранено",
            "promised_at": "неполный ввод допустим",
            "deadline": "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        storage.save_draft(task_id, draft, self.data_dir)
        loaded, problem = storage.load_draft(task_id, self.data_dir)
        self.assertEqual(loaded, draft)
        self.assertIsNone(problem)

        storage.delete_draft(task_id, self.data_dir)
        loaded, problem = storage.load_draft(task_id, self.data_dir)
        self.assertIsNone(loaded)
        self.assertIsNone(problem)

    def test_corrupted_draft_is_reported_and_not_changed(self) -> None:
        task_id = str(uuid4())
        storage.init_storage(self.data_dir)
        path = self.data_dir / "drafts" / f"{task_id}.json"
        contents = "not json"
        path.write_text(contents, encoding="utf-8")

        draft, problem = storage.load_draft(task_id, self.data_dir)

        self.assertIsNone(draft)
        self.assertEqual(problem["file"], path.name)
        self.assertEqual(path.read_text(encoding="utf-8"), contents)

    def test_save_draft_does_not_replace_corrupted_existing_file(self) -> None:
        task_id = str(uuid4())
        storage.init_storage(self.data_dir)
        path = self.data_dir / "drafts" / f"{task_id}.json"
        contents = "not json"
        path.write_text(contents, encoding="utf-8")
        draft = {
            "task_id": task_id,
            "title": "Черновик",
            "description": "Описание",
            "promised_at": "",
            "deadline": "",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        with self.assertRaisesRegex(storage.InvalidDataError, "не будет перезаписан"):
            storage.save_draft(task_id, draft, self.data_dir)

        self.assertEqual(path.read_text(encoding="utf-8"), contents)

    def test_noncanonical_uuid_values_are_rejected(self) -> None:
        canonical_id = str(uuid4())
        for invalid_id in (
            canonical_id.upper(),
            canonical_id.replace("-", ""),
            "../../unsafe-path",
        ):
            with self.subTest(invalid_id=invalid_id):
                task = make_task()
                task["id"] = invalid_id
                with self.assertRaises(storage.InvalidDataError):
                    storage.save_task(task, self.data_dir)
                with self.assertRaises(ValueError):
                    storage.load_draft(invalid_id, self.data_dir)

    def test_invalid_task_is_not_written(self) -> None:
        task = make_task()
        task["comments"] = "не список"

        with self.assertRaises(storage.InvalidDataError):
            storage.save_task(task, self.data_dir)

        tasks_dir = self.data_dir / "tasks"
        self.assertFalse(tasks_dir.exists())


if __name__ == "__main__":
    unittest.main()
