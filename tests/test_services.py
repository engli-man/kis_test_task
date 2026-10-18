import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import services
import storage


def editor_values(title: str = "Новое дело") -> dict[str, str]:
    return {
        "title": title,
        "description": "Описание",
        "promised_at": "2026-10-18T12:00:00+03:00",
        "deadline": "2026-10-25",
    }


class ServicesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temporary_directory.name) / "data"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_create_task_saves_task_and_removes_new_draft(self) -> None:
        values = editor_values()
        services.save_editor_draft("new", None, **values, data_dir=self.data_dir)

        task = services.create_task(values, self.data_dir)

        tasks, problems = storage.load_tasks(self.data_dir)
        self.assertEqual(tasks, [task])
        self.assertEqual(problems, [])
        self.assertEqual(storage.load_draft("new", self.data_dir), (None, None))

    def test_update_task_changes_only_editable_fields(self) -> None:
        original = services.create_task(editor_values(), self.data_dir)
        services.save_editor_draft(
            original["id"],
            original["id"],
            **editor_values("Черновое название"),
            data_dir=self.data_dir,
        )

        updated = services.update_task(
            original, editor_values("Новое название"), self.data_dir
        )

        self.assertEqual(updated["title"], "Новое название")
        self.assertEqual(updated["id"], original["id"])
        self.assertEqual(updated["status"], original["status"])
        self.assertEqual(storage.load_draft(original["id"], self.data_dir), (None, None))

    def test_draft_is_restored_instead_of_saved_task_values(self) -> None:
        task = services.create_task(editor_values("Сохранённое"), self.data_dir)
        draft = services.save_editor_draft(
            task["id"],
            task["id"],
            **editor_values("Несохранённое"),
            data_dir=self.data_dir,
        )

        values, problem = services.load_editor_values(task["id"], task, self.data_dir)

        self.assertEqual(values, draft)
        self.assertIsNone(problem)

    def test_validation_error_preserves_draft_and_saved_task(self) -> None:
        task = services.create_task(editor_values("Исходное"), self.data_dir)
        invalid_values = editor_values("")
        draft = services.save_editor_draft(
            task["id"], task["id"], **invalid_values, data_dir=self.data_dir
        )

        with self.assertRaises(services.InputValidationError):
            services.update_task(task, invalid_values, self.data_dir)

        saved_task = storage.load_tasks(self.data_dir)[0][0]
        saved_draft = storage.load_draft(task["id"], self.data_dir)[0]
        self.assertEqual(saved_task["title"], "Исходное")
        self.assertEqual(saved_draft, draft)
        self.assertIsNotNone(datetime.fromisoformat(saved_draft["updated_at"]).tzinfo)

    def test_non_string_title_and_description_are_rejected(self) -> None:
        for field, invalid_value in (("title", 42), ("description", ["текст"])):
            with self.subTest(field=field):
                values = editor_values()
                values[field] = invalid_value

                with self.assertRaises(services.InputValidationError):
                    services.create_task(values, self.data_dir)

    def test_deadline_is_normalized_to_iso_date(self) -> None:
        values = editor_values()
        values["deadline"] = "20261025"

        task = services.create_task(values, self.data_dir)

        self.assertEqual(task["deadline"], "2026-10-25")

    def test_deadline_before_promised_date_is_rejected(self) -> None:
        values = editor_values()
        values["deadline"] = "2026-10-17"

        with self.assertRaisesRegex(
            services.InputValidationError, "раньше даты обещания"
        ):
            services.create_task(values, self.data_dir)

    def test_invalid_deadline_is_not_saved_to_draft(self) -> None:
        task = services.create_task(editor_values(), self.data_dir)
        valid_draft = services.save_editor_draft(
            task["id"], task["id"], **editor_values(), data_dir=self.data_dir
        )
        invalid_values = editor_values()
        invalid_values["deadline"] = "2026-10-17"

        with self.assertRaises(services.InputValidationError):
            services.save_editor_draft(
                task["id"], task["id"], **invalid_values, data_dir=self.data_dir
            )

        saved_draft = storage.load_draft(task["id"], self.data_dir)[0]
        self.assertEqual(saved_draft, valid_draft)

    def test_existing_draft_with_early_deadline_is_not_restored(self) -> None:
        task = services.create_task(editor_values("Сохранённое"), self.data_dir)
        invalid_draft = {
            "task_id": task["id"],
            "title": "Некорректный черновик",
            "description": "Описание",
            "promised_at": "2026-10-18T12:00:00+03:00",
            "deadline": "2026-10-17",
            "updated_at": "2026-10-18T13:00:00+03:00",
        }
        storage.save_draft(task["id"], invalid_draft, self.data_dir)

        values, problem = services.load_editor_values(task["id"], task, self.data_dir)

        self.assertEqual(values["title"], task["title"])
        self.assertIn("раньше даты обещания", problem["error"])
        self.assertEqual(storage.load_draft(task["id"], self.data_dir)[0], invalid_draft)

    def test_close_task_sets_completion_time_and_preserves_other_data(self) -> None:
        task = services.create_task(editor_values(), self.data_dir)
        task["comments"] = [
            {
                "id": str(uuid4()),
                "text": "Комментарий",
                "created_at": "2026-10-18T13:00:00+03:00",
            }
        ]
        storage.save_task(task, self.data_dir)

        completed = services.close_task(task, self.data_dir)

        self.assertEqual(completed["status"], "completed")
        self.assertIsNotNone(datetime.fromisoformat(completed["completed_at"]).tzinfo)
        for field in ("id", "title", "description", "promised_at", "deadline", "comments"):
            self.assertEqual(completed[field], task[field])
        self.assertEqual(storage.load_tasks(self.data_dir)[0], [completed])

    def test_close_task_rejects_deadline_before_promised_date(self) -> None:
        task = services.create_task(editor_values(), self.data_dir)
        task["deadline"] = "2026-10-17"

        with self.assertRaises(services.InputValidationError):
            services.close_task(task, self.data_dir)

        saved_task = storage.load_tasks(self.data_dir)[0][0]
        self.assertEqual(saved_task["status"], "open")

    def test_invalid_draft_dates_fall_back_without_changing_draft(self) -> None:
        task = services.create_task(editor_values("Сохранённое"), self.data_dir)
        draft = services.save_editor_draft(
            task["id"],
            task["id"],
            **{
                **editor_values("Черновик"),
                "promised_at": "не дата",
                "deadline": "тоже не дата",
            },
            data_dir=self.data_dir,
        )

        values, problem = services.load_editor_values(task["id"], task, self.data_dir)
        services.update_task(task, values, self.data_dir)

        self.assertEqual(values["title"], task["title"])
        self.assertEqual(problem["file"], f"{task['id']}.json")
        saved_draft, draft_problem = storage.load_draft(task["id"], self.data_dir)
        self.assertEqual(saved_draft, draft)
        self.assertIsNone(draft_problem)

    def test_add_comment_saves_uuid_time_and_text(self) -> None:
        task = services.create_task(editor_values(), self.data_dir)

        updated = services.add_comment(task, "  Первый комментарий  ", self.data_dir)

        self.assertEqual(len(updated["comments"]), 1)
        comment = updated["comments"][0]
        self.assertEqual(comment["text"], "Первый комментарий")
        self.assertEqual(str(UUID(comment["id"])), comment["id"])
        self.assertIsNotNone(datetime.fromisoformat(comment["created_at"]).tzinfo)
        saved_tasks, problems = storage.load_tasks(self.data_dir)
        self.assertEqual(saved_tasks, [updated])
        self.assertEqual(problems, [])

    def test_empty_comment_is_rejected_without_changing_task(self) -> None:
        task = services.create_task(editor_values(), self.data_dir)

        for text in ("", "   "):
            with self.subTest(text=text):
                with self.assertRaises(services.InputValidationError):
                    services.add_comment(task, text, self.data_dir)

        saved_task = storage.load_tasks(self.data_dir)[0][0]
        self.assertEqual(saved_task["comments"], [])

    def test_comment_cannot_be_added_to_completed_task(self) -> None:
        task = services.create_task(editor_values(), self.data_dir)
        completed = services.close_task(task, self.data_dir)

        with self.assertRaises(services.InputValidationError):
            services.add_comment(completed, "Поздний комментарий", self.data_dir)

        saved_task = storage.load_tasks(self.data_dir)[0][0]
        self.assertEqual(saved_task["comments"], [])

    def test_search_tasks_by_title_and_description(self) -> None:
        first = services.create_task(editor_values("Подготовить договор"), self.data_dir)
        second_values = editor_values("Позвонить заказчику")
        second_values["description"] = "Обсудить условия ПОСТАВКИ"
        second = services.create_task(second_values, self.data_dir)
        tasks = [first, second]

        self.assertEqual(services.search_tasks(tasks, "дого"), [first])
        self.assertEqual(services.search_tasks(tasks, "постав"), [second])
        self.assertEqual(services.search_tasks(tasks, "  ПОСТАВКИ  "), [second])
        self.assertEqual(services.search_tasks(tasks, "нет совпадений"), [])

    def test_empty_search_query_returns_all_tasks(self) -> None:
        tasks = [
            services.create_task(editor_values("Первое"), self.data_dir),
            services.create_task(editor_values("Второе"), self.data_dir),
        ]

        self.assertEqual(services.search_tasks(tasks, "   "), tasks)

    def test_filter_tasks_by_day(self) -> None:
        first_values = editor_values("Первое")
        first_values["deadline"] = "2026-12-31"
        second_values = editor_values("Второе")
        second_values["deadline"] = "2027-01-01"
        first = services.create_task(first_values, self.data_dir)
        second = services.create_task(second_values, self.data_dir)

        result = services.filter_tasks_by_deadline(
            [first, second], "day", date(2026, 12, 31)
        )

        self.assertEqual(result, [first])

    def test_filter_week_starts_on_monday_across_year_boundary(self) -> None:
        tasks = []
        for title, deadline in (
            ("Понедельник", "2026-12-28"),
            ("Воскресенье", "2027-01-03"),
            ("Следующий понедельник", "2027-01-04"),
        ):
            values = editor_values(title)
            values["deadline"] = deadline
            tasks.append(services.create_task(values, self.data_dir))

        result = services.filter_tasks_by_deadline(
            tasks, "week", date(2027, 1, 1)
        )

        self.assertEqual(result, tasks[:2])

    def test_filter_calendar_month_respects_month_and_year(self) -> None:
        tasks = []
        for title, deadline in (
            ("Начало декабря", "2026-12-01"),
            ("Конец декабря", "2026-12-31"),
            ("Другой год", "2027-12-01"),
            ("Следующий месяц", "2027-01-01"),
        ):
            values = editor_values(title)
            values["deadline"] = deadline
            tasks.append(services.create_task(values, self.data_dir))

        result = services.filter_tasks_by_deadline(
            tasks, "month", date(2026, 12, 15)
        )

        self.assertEqual(result, tasks[:2])

    def test_filter_tasks_by_inclusive_date_range(self) -> None:
        tasks = []
        for title, deadline in (
            ("До диапазона", "2026-11-30"),
            ("Начало", "2026-12-01"),
            ("Конец", "2027-01-02"),
            ("После диапазона", "2027-01-03"),
        ):
            values = editor_values(title)
            values["deadline"] = deadline
            tasks.append(services.create_task(values, self.data_dir))

        result = services.filter_tasks_by_deadline(
            tasks, "range", date(2026, 12, 1), date(2027, 1, 2)
        )

        self.assertEqual(result, tasks[1:3])

    def test_filter_rejects_reversed_date_range(self) -> None:
        with self.assertRaises(services.InputValidationError):
            services.filter_tasks_by_deadline(
                [], "range", date(2027, 1, 2), date(2026, 12, 1)
            )


if __name__ == "__main__":
    unittest.main()
