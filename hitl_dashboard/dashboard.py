# hitl_dashboard/dashboard.py
"""
HITL дашборд для RAG-системы.
Предоставляет интерфейс для:
- Просмотра логов взаимодействий
- Оценки качества ответов (лайк/дизлайк)
- Исправления некорректных ответов
- Фильтрации по дате, модели, запросу
- Экспорта исправленных примеров для дообучения
"""
import json
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional

import streamlit as st
import pandas as pd

# Настройка страницы
st.set_page_config(
    page_title="RAG HITL Dashboard",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Директория с логами (из переменной окружения или по умолчанию)
LOG_DIR = Path(os.getenv("LOG_DIR", "./logs"))
INTERACTIONS_FILE = LOG_DIR / "hitl" / "interactions.jsonl"
FEEDBACK_FILE = LOG_DIR / "hitl" / "feedback.jsonl"

# Создаём директорию, если её нет
LOG_DIR.mkdir(parents=True, exist_ok=True)
(LOG_DIR / "hitl").mkdir(parents=True, exist_ok=True)


def load_interactions(limit: int = 500) -> pd.DataFrame:
    """Загружает взаимодействия из JSONL в DataFrame."""
    if not INTERACTIONS_FILE.exists():
        return pd.DataFrame()
    interactions = []
    with open(INTERACTIONS_FILE, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= limit:
                break
            try:
                interactions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not interactions:
        return pd.DataFrame()
    df = pd.DataFrame(interactions)
    # Преобразуем timestamp в datetime
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def load_feedback() -> pd.DataFrame:
    """Загружает обратную связь из JSONL."""
    if not FEEDBACK_FILE.exists():
        return pd.DataFrame()
    feedback = []
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                feedback.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return pd.DataFrame(feedback)


def save_feedback(feedback_record: Dict):
    """Сохраняет обратную связь в файл."""
    with open(FEEDBACK_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(feedback_record, ensure_ascii=False) + "\n")


def update_interaction_with_correction(request_id: str, corrected_response: str):
    """
    Обновляет запись взаимодействия, добавляя исправленный ответ.
    (Можно также перезаписывать исходный файл, но проще хранить отдельно)
    """
    # Читаем все записи
    if not INTERACTIONS_FILE.exists():
        return
    lines = []
    updated = False
    with open(INTERACTIONS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            try:
                record = json.loads(line)
                if record.get("request_id") == request_id:
                    record["corrected_response"] = corrected_response
                    updated = True
                lines.append(json.dumps(record, ensure_ascii=False))
            except json.JSONDecodeError:
                lines.append(line.strip())
    if updated:
        with open(INTERACTIONS_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        st.success(f"Сохранено исправление для {request_id}")


def export_training_dataset(df: pd.DataFrame, output_path: Path):
    """Экспортирует пары (запрос, исправленный ответ) в JSONL."""
    training_pairs = []
    for _, row in df.iterrows():
        if pd.notna(row.get("corrected_response")) and row["corrected_response"]:
            training_pairs.append({
                "prompt": row["user_query"],
                "completion": row["corrected_response"]
            })
        elif row.get("user_feedback") == "positive":
            training_pairs.append({
                "prompt": row["user_query"],
                "completion": row["response"]
            })
    if training_pairs:
        with open(output_path, "w", encoding="utf-8") as f:
            for pair in training_pairs:
                f.write(json.dumps(pair, ensure_ascii=False) + "\n")
        st.success(f"Экспортировано {len(training_pairs)} пар в {output_path}")
    else:
        st.warning("Нет подходящих примеров для экспорта")


# --- Интерфейс Streamlit ---
st.title("🤖 RAG System HITL Dashboard")
st.markdown("Просмотр, оценка и исправление ответов ассистента")

# Боковая панель с фильтрами
st.sidebar.header("Фильтры")
limit = st.sidebar.number_input("Количество последних записей", min_value=10, max_value=2000, value=200)
refresh_button = st.sidebar.button("Обновить данные")

# Загрузка данных
df_interactions = load_interactions(limit=limit)
df_feedback = load_feedback()

# Добавляем информацию о фидбеке в основной DataFrame
if not df_interactions.empty and not df_feedback.empty:
    # Объединяем по request_id
    feedback_dict = df_feedback.set_index("request_id").to_dict(orient="index")
    df_interactions["feedback_type"] = df_interactions["request_id"].apply(
        lambda rid: feedback_dict.get(rid, {}).get("feedback_type", "")
    )
    df_interactions["expert_comment"] = df_interactions["request_id"].apply(
        lambda rid: feedback_dict.get(rid, {}).get("comment", "")
    )

# Фильтр по наличию фидбека
show_only_with_feedback = st.sidebar.checkbox("Показывать только с обратной связью")
if show_only_with_feedback and not df_interactions.empty:
    df_interactions = df_interactions[df_interactions["feedback_type"] != ""]

# Фильтр по поисковому запросу
search_query = st.sidebar.text_input("Поиск по запросу")
if search_query and not df_interactions.empty:
    mask = df_interactions["user_query"].str.contains(search_query, case=False, na=False)
    df_interactions = df_interactions[mask]

# Основная область
if df_interactions.empty:
    st.info("Нет данных. Загрузите логи взаимодействий.")
    st.stop()

st.write(f"Показано **{len(df_interactions)}** записей из **{len(df_interactions)}**")

# Выбор режима отображения
view_mode = st.radio("Режим просмотра", ["Карточки", "Таблица"], horizontal=True)

if view_mode == "Таблица":
    # Таблица с основными полями
    display_cols = ["timestamp", "request_id", "user_query", "response", "feedback_type"]
    available_cols = [c for c in display_cols if c in df_interactions.columns]
    st.dataframe(df_interactions[available_cols], use_container_width=True)
else:
    # Карточки для каждого взаимодействия
    for idx, row in df_interactions.iterrows():
        with st.expander(f"{row['timestamp']} | {row['request_id'][:20]} | {row['user_query'][:80]}", expanded=False):
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown("**Запрос:**")
                st.write(row["user_query"])
                st.markdown("**Ответ ассистента:**")
                st.write(row["response"])
                if row.get("corrected_response"):
                    st.markdown("**Исправленный ответ:**")
                    st.info(row["corrected_response"])
                st.markdown("**Метаданные:**")
                meta = row.get("metadata", {})
                if meta:
                    st.json(meta)
                else:
                    st.write("Нет метаданных")
            with col2:
                st.markdown("**Оценка**")
                # Текущая оценка
                current_feedback = row.get("feedback_type", "")
                if current_feedback == "positive":
                    st.success("👍 Положительная")
                elif current_feedback == "negative":
                    st.error("👎 Отрицательная")
                elif current_feedback == "correction":
                    st.info("✏️ Исправление")
                else:
                    st.write("Нет оценки")
                
                # Кнопки быстрой оценки
                col_pos, col_neg, col_corr = st.columns(3)
                if col_pos.button("👍", key=f"pos_{row['request_id']}"):
                    save_feedback({
                        "request_id": row["request_id"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "feedback_type": "positive",
                        "comment": None,
                        "corrected_response": None
                    })
                    st.rerun()
                if col_neg.button("👎", key=f"neg_{row['request_id']}"):
                    save_feedback({
                        "request_id": row["request_id"],
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "feedback_type": "negative",
                        "comment": None,
                        "corrected_response": None
                    })
                    st.rerun()
                if col_corr.button("✏️", key=f"corr_{row['request_id']}"):
                    st.session_state[f"edit_mode_{row['request_id']}"] = True
                
                # Форма исправления
                if st.session_state.get(f"edit_mode_{row['request_id']}", False):
                    corrected = st.text_area("Исправленный ответ", value=row.get("corrected_response", row["response"]), height=200)
                    comment = st.text_input("Комментарий эксперта (почему исправлено?)")
                    if st.button("Сохранить исправление", key=f"save_{row['request_id']}"):
                        update_interaction_with_correction(row["request_id"], corrected)
                        save_feedback({
                            "request_id": row["request_id"],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "feedback_type": "correction",
                            "comment": comment,
                            "corrected_response": corrected,
                            "expert_id": "expert"
                        })
                        st.session_state[f"edit_mode_{row['request_id']}"] = False
                        st.rerun()

# Экспорт датасета для дообучения
st.sidebar.header("Экспорт данных")
if st.sidebar.button("Экспортировать датасет для fine-tuning"):
    output_path = LOG_DIR / "training_dataset.jsonl"
    export_training_dataset(df_interactions, output_path)
    with open(output_path, "r") as f:
        st.sidebar.download_button(
            label="Скачать датасет",
            data=f.read(),
            file_name="training_dataset.jsonl",
            mime="application/json"
        )

# Статистика
st.sidebar.header("Статистика")
if not df_feedback.empty:
    feedback_counts = df_feedback["feedback_type"].value_counts()
    st.sidebar.write("**Распределение фидбека:**")
    for fb_type, count in feedback_counts.items():
        st.sidebar.write(f"- {fb_type}: {count}")
else:
    st.sidebar.write("Нет обратной связи")

# Путь к логам
st.sidebar.caption(f"Логи: `{INTERACTIONS_FILE}`")

if __name__ == "__main__":
    pass