import streamlit as st
from storage import DATA_DIR, init_storage, load_tasks


st.set_page_config(page_title="Дневник обещаний")

init_storage()
tasks, problems = load_tasks()

st.title("Дневник обещаний")

st.metric("Дел в хранилище", len(tasks) + len(problems))

if problems:
    st.warning("Некоторые файлы дел повреждены. Они оставлены без изменений.")
    for problem in problems:
        st.error(f"{problem['file']}: {problem['error']}")
else:
    st.success("Повреждённых файлов дел не обнаружено.")
