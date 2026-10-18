from datetime import date, datetime, time

import streamlit as st

import services
import storage


st.set_page_config(page_title="Дневник обещаний")


def _widget_key(field: str, draft_key: str) -> str:
    return f"editor_{field}_{draft_key}"


def _editor_values(draft_key: str) -> dict[str, str]:
    promised_date: date = st.session_state[_widget_key("promised_date", draft_key)]
    promised_time: time = st.session_state[_widget_key("promised_time", draft_key)]
    local_timezone = datetime.now().astimezone().tzinfo
    promised_at = datetime.combine(
        promised_date, promised_time, tzinfo=local_timezone
    ).isoformat(timespec="seconds")
    deadline: date = st.session_state[_widget_key("deadline", draft_key)]
    return {
        "title": st.session_state[_widget_key("title", draft_key)],
        "description": st.session_state[_widget_key("description", draft_key)],
        "promised_at": promised_at,
        "deadline": deadline.isoformat(),
    }


def _save_draft(draft_key: str, task_id: str | None) -> None:
    load_problem = st.session_state.get(_widget_key("load_problem", draft_key))
    if load_problem is not None:
        st.session_state[_widget_key("draft_error", draft_key)] = (
            "повреждённый черновик оставлен без изменений"
        )
        return
    try:
        services.save_editor_draft(
            draft_key=draft_key,
            task_id=task_id,
            **_editor_values(draft_key),
        )
        st.session_state.pop(_widget_key("draft_error", draft_key), None)
    except (OSError, ValueError) as error:
        st.session_state[_widget_key("draft_error", draft_key)] = str(error)


def _initialize_editor(draft_key: str, task: dict | None) -> dict[str, str] | None:
    title_key = _widget_key("title", draft_key)
    problem_key = _widget_key("load_problem", draft_key)
    if title_key in st.session_state:
        return st.session_state.get(problem_key)

    values, problem = services.load_editor_values(draft_key, task)
    promised_at = datetime.fromisoformat(values["promised_at"])
    st.session_state[title_key] = values["title"]
    st.session_state[_widget_key("description", draft_key)] = values["description"]
    st.session_state[_widget_key("promised_date", draft_key)] = promised_at.date()
    st.session_state[_widget_key("promised_time", draft_key)] = promised_at.time().replace(
        tzinfo=None
    )
    st.session_state[_widget_key("deadline", draft_key)] = date.fromisoformat(
        values["deadline"]
    )
    if problem is not None:
        st.session_state[problem_key] = problem
    return problem


def _clear_editor(draft_key: str) -> None:
    prefix = f"editor_"
    suffix = f"_{draft_key}"
    for key in list(st.session_state):
        if key.startswith(prefix) and key.endswith(suffix):
            del st.session_state[key]


storage.init_storage()
tasks, problems = storage.load_tasks()
tasks.sort(key=lambda task: (task["deadline"], task["title"].lower()))
tasks_by_id = {task["id"]: task for task in tasks}

if "pending_selection" in st.session_state:
    st.session_state["selected_task_id"] = st.session_state.pop("pending_selection")
if st.session_state.get("selected_task_id") not in {"new", *tasks_by_id}:
    st.session_state["selected_task_id"] = "new"

st.title("Дневник обещаний")

if problems:
    st.warning("Некоторые файлы дел повреждены. Они оставлены без изменений.")
    for problem in problems:
        st.error(f"{problem['file']}: {problem['error']}")

options = ["new", *tasks_by_id]


def _task_label(task_id: str) -> str:
    if task_id == "new":
        return "＋ Новое дело"
    task = tasks_by_id[task_id]
    return f"{task['title']} · до {task['deadline']}"


st.sidebar.header("Дела")
selected_id = st.sidebar.radio(
    "Выберите дело",
    options,
    key="selected_task_id",
    format_func=_task_label,
)

selected_task = tasks_by_id.get(selected_id)
draft_problem = _initialize_editor(selected_id, selected_task)

if "flash_message" in st.session_state:
    st.success(st.session_state.pop("flash_message"))
if draft_problem:
    st.warning(
        f"Черновик {draft_problem['file']} повреждён и оставлен без изменений: "
        f"{draft_problem['error']}"
    )

st.subheader("Новое дело" if selected_id == "new" else "Редактирование дела")
callback_args = (selected_id, None if selected_id == "new" else selected_id)

st.text_input(
    "Название",
    key=_widget_key("title", selected_id),
    on_change=_save_draft,
    args=callback_args,
)
st.text_area(
    "Описание",
    key=_widget_key("description", selected_id),
    on_change=_save_draft,
    args=callback_args,
)

date_column, time_column, deadline_column = st.columns(3)
with date_column:
    st.date_input(
        "Дата обещания",
        key=_widget_key("promised_date", selected_id),
        on_change=_save_draft,
        args=callback_args,
    )
with time_column:
    st.time_input(
        "Время обещания",
        key=_widget_key("promised_time", selected_id),
        step=60,
        on_change=_save_draft,
        args=callback_args,
    )
with deadline_column:
    st.date_input(
        "Дедлайн",
        key=_widget_key("deadline", selected_id),
        on_change=_save_draft,
        args=callback_args,
    )

draft_error = st.session_state.get(_widget_key("draft_error", selected_id))
if draft_error:
    st.error(f"Не удалось сохранить черновик: {draft_error}")
else:
    st.caption("Изменения полей автоматически сохраняются в локальный черновик.")

if st.button("Сохранить", type="primary"):
    values = _editor_values(selected_id)
    _save_draft(*callback_args)
    try:
        if selected_task is None:
            saved_task = services.create_task(values)
            _clear_editor("new")
            st.session_state["pending_selection"] = saved_task["id"]
            st.session_state["flash_message"] = "Дело создано."
        else:
            services.update_task(selected_task, values)
            st.session_state["flash_message"] = "Изменения сохранены."
        st.rerun()
    except (OSError, ValueError) as error:
        st.error(str(error))
