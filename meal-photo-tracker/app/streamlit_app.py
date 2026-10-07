"""Streamlit front end for mealtrack.  Run with:  streamlit run app/streamlit_app.py"""

from __future__ import annotations

import os
from datetime import date

import pandas as pd
import streamlit as st

from mealtrack import config
from mealtrack.demo import seed_demo
from mealtrack.editing import items_from_rows
from mealtrack.models import MEAL_TYPES, EstimateError, MealEstimate, NotFoodError
from mealtrack.store import Store
from mealtrack.summary import summarize_day, summarize_range
from mealtrack.vision import Cache, ImageError, VisionError, analyze_photo, get_backend

config.load_env()
st.set_page_config(page_title="mealtrack", layout="centered")

ITEM_COLUMNS = ["name", "grams", "kcal", "kcal_low", "kcal_high", "protein_g", "carbs_g", "fat_g"]


# --------------------------------------------------------------------------- sidebar
def default_backend() -> str:
    explicit = os.getenv("MEALTRACK_BACKEND")
    if explicit in ("claude", "mock"):
        return explicit
    return "claude" if os.getenv("ANTHROPIC_API_KEY") else "mock"


st.title("mealtrack")
st.caption("Photo to calories and macros, with honest uncertainty ranges.")

with st.sidebar:
    st.header("Settings")
    backend_name = st.radio(
        "Vision backend",
        ["claude", "mock"],
        index=0 if default_backend() == "claude" else 1,
        help="'mock' returns fake placeholder data and uses a separate demo database.",
    )
    goal_kcal = st.number_input("Calorie goal (kcal)", 500, 6000, config.goal_kcal(), step=50)
    goal_water = st.number_input("Water goal (ml)", 500, 6000, config.goal_water_ml(), step=250)
    if backend_name == "mock":
        st.info("Demo mode: fake estimates, stored in a separate demo database.")
        if st.button("Fill with synthetic demo data"):
            with Store(config.db_path("mock")) as store:
                seed_demo(store, days=14)
            st.success("Demo data added.")
    elif not os.getenv("ANTHROPIC_API_KEY"):
        st.warning("ANTHROPIC_API_KEY is not set. Add it to a .env file or switch to mock.")

DB = config.db_path(backend_name)
tab_log, tab_day, tab_week = st.tabs(["Log a meal", "Day", "Week"])


# --------------------------------------------------------------------------- log a meal
with tab_log:
    c1, c2 = st.columns(2)
    day_for_meal = c1.date_input("Day", value=date.today(), key="meal_day")
    meal_type = c2.selectbox("Meal", MEAL_TYPES, index=1)
    hint = st.text_input(
        "What you know about it (optional)",
        placeholder="e.g. brown rice 90 g, chicken 140 g, 1 tsp oil",
        help="Weights or ingredients you know are trusted over the model's visual guess.",
    )
    uploaded = st.file_uploader("Photo", type=["jpg", "jpeg", "png", "webp", "gif"])
    with st.expander("Or take a photo with the camera"):
        camera = st.camera_input("Camera", label_visibility="collapsed")
    photo = camera or uploaded

    if photo is not None and st.button("Estimate", type="primary"):
        data = photo.getvalue()
        try:
            with st.spinner("Estimating..."):
                analysis = analyze_photo(
                    data, get_backend(backend_name), hint=hint, cache=Cache(config.cache_dir())
                )
            st.session_state["analysis"] = analysis
            st.session_state["analysis_image"] = data
            st.session_state["analysis_hint"] = hint
            st.session_state["editor_version"] = st.session_state.get("editor_version", 0) + 1
        except NotFoodError:
            st.session_state.pop("analysis", None)
            st.warning("I couldn't find food or drink in that image.")
        except ImageError as exc:
            st.error(str(exc))
        except (VisionError, EstimateError) as exc:
            st.error(f"Could not estimate this meal: {exc}")

    analysis = st.session_state.get("analysis")
    if analysis is not None:
        est = analysis.estimate
        left, right = st.columns([1, 2])
        left.image(st.session_state["analysis_image"], width="stretch")
        with right:
            st.markdown(f"**Confidence: {est.confidence}**" + ("  ·  from cache" if analysis.cached else ""))
            for q in est.questions:
                st.caption(f"Would help to know: {q}")

        st.caption("Edit anything that looks wrong before saving. Rows can be added or removed.")
        original = pd.DataFrame([i.to_dict() for i in est.items], columns=ITEM_COLUMNS)
        edited = st.data_editor(
            original,
            num_rows="dynamic",
            width="stretch",
            key=f"editor_{st.session_state.get('editor_version', 0)}",
        )
        items = items_from_rows(edited.to_dict("records"))
        current = MealEstimate(items=items, confidence=est.confidence)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("kcal", f"{current.kcal:,.0f}", f"{current.kcal_low:,.0f}-{current.kcal_high:,.0f}", delta_color="off")
        m2.metric("Protein", f"{current.protein_g:.0f} g")
        m3.metric("Carbs", f"{current.carbs_g:.0f} g")
        m4.metric("Fat", f"{current.fat_g:.0f} g")

        with st.expander("Assumptions and warnings"):
            for a in est.assumptions:
                st.write(f"- assumed: {a}")
            for w in est.warnings:
                st.write(f"- warning: {w}")
            if not est.assumptions and not est.warnings:
                st.write("Nothing to flag.")

        if st.button("Save to log", disabled=not items):
            was_edited = [i.to_dict() for i in items] != [i.to_dict() for i in est.items]
            to_save = MealEstimate(
                items=items,
                confidence=est.confidence,
                assumptions=est.assumptions,
                questions=est.questions,
                warnings=est.warnings + (["edited manually before saving"] if was_edited else []),
            )
            with Store(DB) as store:
                store.add_meal(
                    to_save,
                    day=day_for_meal.isoformat(),
                    meal_type=meal_type,
                    note=st.session_state.get("analysis_hint") or None,
                    image_sha=analysis.image_sha,
                    backend=analysis.backend,
                    model=analysis.model,
                )
            for key in ("analysis", "analysis_image", "analysis_hint"):
                st.session_state.pop(key, None)
            st.success("Saved.")
            st.rerun()


# --------------------------------------------------------------------------- day view
with tab_day:
    day = st.date_input("Day", value=date.today(), key="view_day").isoformat()

    with Store(DB) as store:
        summary = summarize_day(store, day, int(goal_kcal), int(goal_water))
        meals = store.meals(day)

    if summary.logged:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("kcal", f"{summary.kcal:,.0f}", f"{summary.kcal_low:,.0f}-{summary.kcal_high:,.0f}", delta_color="off")
        k2.metric("Protein", f"{summary.protein_g:.0f} g")
        k3.metric("Carbs", f"{summary.carbs_g:.0f} g")
        k4.metric("Fat", f"{summary.fat_g:.0f} g")
        st.progress(min(summary.kcal / summary.goal_kcal, 1.0), text=f"{summary.pct_of_goal:.0f}% of {summary.goal_kcal:,} kcal goal")
        if summary.n_low_confidence:
            st.caption(f"{summary.n_low_confidence} of {summary.n_meals} meals are low confidence.")
    else:
        st.info("No meals logged for this day.")

    st.progress(min(summary.water_ml / summary.goal_water_ml, 1.0), text=f"Water {summary.water_ml:,} / {summary.goal_water_ml:,} ml")
    w1, w2, w3, _ = st.columns(4)
    for col, ml in ((w1, 250), (w2, 500), (w3, -250)):
        if col.button(f"{ml:+d} ml", key=f"water_{ml}"):
            with Store(DB) as store:
                store.add_water(ml, day=day)
            st.rerun()

    st.subheader("Workout")
    state = {None: "not logged", True: "done", False: "skipped"}[summary.workout_done]
    st.write(f"Status: {state}")
    f1, f2 = st.columns(2)
    kind = f1.text_input("Kind", placeholder="gym, run, yoga")
    minutes = f2.number_input("Minutes", 0, 600, 0, step=5)
    b1, b2, _ = st.columns([1, 1, 2])
    if b1.button("Done", key="workout_done"):
        with Store(DB) as store:
            store.add_workout(True, kind=kind or None, minutes=int(minutes) or None, day=day)
        st.rerun()
    if b2.button("Skipped", key="workout_skipped"):
        with Store(DB) as store:
            store.add_workout(False, day=day)
        st.rerun()

    if meals:
        st.subheader("Meals")
    for m in meals:
        with st.expander(f"{m['meal_type'].title()} · {m['kcal']:,.0f} kcal · {', '.join(i.name for i in m['items'])}"):
            st.dataframe(pd.DataFrame([i.to_dict() for i in m["items"]]), width="stretch", hide_index=True)
            st.caption(f"confidence: {m['confidence']}" + (f" · note: {m['note']}" if m["note"] else ""))
            for w in m["warnings"]:
                st.caption(f"warning: {w}")
            if st.button("Delete this meal", key=f"del_{m['id']}"):
                with Store(DB) as store:
                    store.delete_meal(m["id"])
                st.rerun()


# --------------------------------------------------------------------------- week view
with tab_week:
    with Store(DB) as store:
        week = summarize_range(store, date.today().isoformat(), 7, int(goal_kcal), int(goal_water))
    if week.avg_kcal is None:
        st.info("No meals logged in the last 7 days.")
    else:
        st.write(
            f"Average **{week.avg_kcal:,.0f} kcal** and **{week.avg_protein_g:.0f} g protein** "
            f"over the {week.logged_days} of {len(week.days)} days with meals logged."
        )
        chart = pd.DataFrame(
            {"kcal": [d.kcal if d.logged else None for d in week.days]},
            index=[d.day for d in week.days],
        )
        st.bar_chart(chart)
        st.caption("Days with no meals are left blank, not counted as zero.")
    table = pd.DataFrame(
        [
            {
                "day": d.day,
                "kcal": round(d.kcal) if d.logged else None,
                "protein g": round(d.protein_g) if d.logged else None,
                "water ml": d.water_ml,
                "workout": {None: "-", True: "done", False: "skipped"}[d.workout_done],
            }
            for d in week.days
        ]
    )
    st.dataframe(table, hide_index=True, width="stretch")

st.divider()
st.caption(
    "Estimates from a single photo can be off by a wide margin. "
    "This is a logging aid, not medical or dietary advice."
)
