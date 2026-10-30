"""Prompt Coach: turn a rough prompt into a strong one. Run with `streamlit run app.py`."""
import uuid

import streamlit as st

from coach.config import active_provider_name, band_for, load_config, target_for
from coach.engine import Coach
from coach.logger import log_session
from coach.providers import CoachError, get_provider

OTHER = "Other…"
STATUS_ICON = {"pass": "✅ Pass", "fail": "❌ Fail", "n/a": "➖ N/A"}

st.set_page_config(page_title="Prompt Coach", page_icon="✍️", layout="centered")
config = load_config()
ss = st.session_state


def reset():
    for key in list(ss.keys()):
        del ss[key]


def init_state():
    defaults = {"stage": "input", "questions": [], "answers": {}, "idx": 0, "interview_done": False,
                "result": None, "error": None, "visit": 0, "return_to_review": False,
                "session_id": None, "parent_session_id": None, "rough_detailed": None}
    for key, value in defaults.items():
        ss.setdefault(key, value)


def go(stage, **updates):
    ss.stage = stage
    ss.visit += 1  # fresh widget keys, so defaults reload from stored answers
    for key, value in updates.items():
        ss[key] = value
    st.rerun()


def qa_list() -> list[dict]:
    qa = []
    for q in ss.questions:
        a = ss.answers.get(q["id"])
        if a:
            qa.append({"id": q["id"], "category": q["category"], "question": q["text"], "type": q["type"],
                       "options": q["options"], "status": a["status"], "answer": a["answer"]})
    return qa


def show_error_and_stop():
    st.error(ss.error)
    c1, c2 = st.columns(2)
    if c1.button("Try again", type="primary"):
        ss.error = None
        st.rerun()
    if c2.button("Start over"):
        reset()
        st.rerun()
    st.stop()


# ---------- screens ----------

def input_screen():
    st.title("Prompt Coach")
    st.write("Type what you want an AI to do, in your own words. I'll ask a few questions "
             "and turn it into a clear, detailed prompt you can copy.")

    rough = st.text_area("Your rough prompt", value=ss.get("rough", ""), height=160,
                         placeholder="e.g. write an email to my landlord about the broken heater")
    warn_at = config["interview"]["input_warn_chars"]
    if len(rough) > warn_at:
        st.warning(f"That's a lot of text ({len(rough):,} characters). It will still be sent, "
                   "but very long input costs more and takes longer.")

    score = st.slider("How detailed should the final prompt be?", 1, 10, value=ss.get("score", 5))
    band = band_for(score)
    count = ("no questions" if band["max_questions"] == 0
             else f"up to {band['max_questions']} questions")
    st.caption(f"**{score}/10 · {count}.** {band['description']}")

    targets = config["targets"]
    labels = [t["label"] for t in targets]
    current = labels.index(target_for(ss["target"])["label"]) if "target" in ss else 0
    label = st.selectbox("Which AI will you paste the prompt into?", labels, index=current)

    if st.button("Start", type="primary"):
        if not rough.strip():
            st.warning("Type a rough prompt first.")
            return
        try:
            provider = get_provider(active_provider_name())
        except CoachError as exc:
            st.error(str(exc))
            return
        ss.rough, ss.score = rough.strip(), score
        ss.target = next(t["key"] for t in targets if t["label"] == label)
        ss.coach = Coach(provider)
        ss.session_id = uuid.uuid4().hex[:12]
        if band["max_questions"] == 0:
            go("result")
        go("interview")


def question_widget(q, stored, key):
    """Render the answer widget; return the answer text ('' if empty)."""
    raw = (stored or {}).get("raw", {})
    if q["type"] == "single":
        choices = q["options"] + [OTHER]
        prev = raw.get("choice")
        index = choices.index(prev) if prev in choices else None
        choice = st.radio("Pick one", choices, index=index, key=f"{key}_c", label_visibility="collapsed")
        other = ""
        if choice == OTHER:
            other = st.text_input("Your answer", value=raw.get("other", ""), key=f"{key}_o")
        ss[f"raw_{q['id']}"] = {"choice": choice, "other": other}
        return other.strip() if choice == OTHER else (choice or "")
    if q["type"] == "multi":
        prev = [o for o in raw.get("selected", []) if o in q["options"]]
        selected = st.multiselect("Pick any", q["options"], default=prev, key=f"{key}_m",
                                  placeholder="Choose one or more")
        other = st.text_input("Anything else? (optional)", value=raw.get("other", ""), key=f"{key}_o")
        ss[f"raw_{q['id']}"] = {"selected": selected, "other": other}
        return "; ".join(selected + ([other.strip()] if other.strip() else []))
    text = st.text_area("Your answer", value=raw.get("text", ""), key=f"{key}_t", height=120,
                        label_visibility="collapsed")
    ss[f"raw_{q['id']}"] = {"text": text}
    return text.strip()


def save_answer(q, status, answer=""):
    raw = ss.get(f"raw_{q['id']}", {}) if status == "answered" else {}
    ss.answers[q["id"]] = {"status": status, "answer": answer, "raw": raw}
    if ss.return_to_review:
        go("review", return_to_review=False)
    go("interview", idx=ss.idx + 1)


def interview_screen():
    band = band_for(ss.score)
    if ss.idx >= len(ss.questions):
        if ss.interview_done:
            go("review")
        with st.spinner("Thinking about what to ask next…"):
            try:
                step = ss.coach.next_questions(ss.rough, ss.score, ss.target, qa_list(), ss.rough_detailed)
            except CoachError as exc:
                ss.error = str(exc)
                st.rerun()
        ss.questions.extend(step.questions)
        ss.interview_done, ss.rough_detailed = step.done, step.rough_detailed
        if not step.questions:
            go("review")
        st.rerun()

    q = ss.questions[ss.idx]
    total = max(band["max_questions"], len(ss.questions))
    st.progress(min(ss.idx / total, 1.0), text=f"Question {ss.idx + 1} of up to {total}")
    st.subheader(q["text"])
    if q["example"]:
        st.caption(f"Example: {q['example']}")

    answer = question_widget(q, ss.answers.get(q["id"]), f"q{q['id']}_{ss.visit}")

    c1, c2, c3, c4 = st.columns(4)
    if c1.button("← Back", disabled=ss.idx == 0 and not ss.return_to_review, width="stretch"):
        if ss.return_to_review:
            go("review", return_to_review=False)
        go("interview", idx=ss.idx - 1)
    if c2.button("Skip", width="stretch"):
        save_answer(q, "skipped")
    if c3.button("I don't know", width="stretch"):
        save_answer(q, "unknown")
    if c4.button("Next →", type="primary", width="stretch"):
        if answer:
            save_answer(q, "answered", answer)
        else:
            st.warning("Type or pick an answer, or choose Skip or I don't know.")

    st.divider()
    if st.button("Start over", key="restart_interview"):
        reset()
        st.rerun()


def review_screen():
    st.title("Check your answers")
    st.write("Edit anything that's wrong, then I'll write your prompt.")
    with st.expander("Your rough prompt"):
        st.write(ss.rough)
    labels = {"skipped": "*(skipped)*", "unknown": "*(I don't know)*"}
    for i, q in enumerate(ss.questions):
        a = ss.answers.get(q["id"], {"status": "skipped", "answer": ""})
        c1, c2 = st.columns([5, 1])
        c1.markdown(f"**{i + 1}. {q['text']}**  \n{labels.get(a['status'], a['answer'])}")
        if c2.button("Edit", key=f"edit_{q['id']}"):
            go("interview", idx=i, return_to_review=True)
    if st.button("Write my prompt", type="primary"):
        go("result")
    if st.button("Start over"):
        reset()
        st.rerun()


def result_screen():
    if ss.result is None:
        with st.spinner("Writing your prompt and checking it…"):
            try:
                calls_before = len(ss.coach.calls)
                ss.result = ss.coach.finalize(ss.rough, ss.score, ss.target, qa_list())
            except CoachError as exc:
                ss.error = str(exc)
                st.rerun()
        provider = ss.coach.provider
        log_session({
            "session_id": ss.session_id,
            "parent_session_id": ss.parent_session_id,
            "rough_prompt": ss.rough,
            "score": ss.score,
            "target_ai": ss.target,
            "questions": ss.questions,
            "answers": qa_list(),
            "final_prompt": ss.result["final_prompt"],
            "additions": ss.result["additions"],
            "checklist": ss.result["checklist"],
            "revised": ss.result["revised"],
            "provider": provider.name,
            "model": provider.model,
            "token_usage": ss.coach.usage_totals(),
            "calls_this_step": ss.coach.calls[calls_before:],
        })

    r = ss.result
    st.title("Your prompt")
    st.caption(f"Detail {ss.score}/10 · for {target_for(ss.target)['label']} · "
               "use the copy icon in the box's top-right corner")
    st.code(r["final_prompt"], language=None, wrap_lines=True)
    st.download_button("Download as .txt", r["final_prompt"], file_name="prompt.txt", mime="text/plain")

    st.subheader("What I added and why")
    for a in r["additions"]:
        st.markdown(f"- **{a['what']}** — {a['why']}")

    st.subheader("Pre-send checklist")
    if r["revised"]:
        st.caption("The first draft failed some checks, so I revised it once.")
    for item in r["checklist"]:
        st.markdown(f"{STATUS_ICON[item['status']]} · **{item['label']}**  \n"
                    f"<span style='opacity:0.75'>{item['note']}</span>", unsafe_allow_html=True)

    st.divider()
    c1, c2 = st.columns(2)
    if ss.score < 10 and c1.button("Make it more detailed", type="primary", width="stretch"):
        new_score = min(10, ss.score + 2)
        done = band_for(new_score)["max_questions"] <= len(ss.questions)
        go("interview", score=new_score, result=None, interview_done=done, idx=len(ss.questions),
           parent_session_id=ss.session_id, session_id=uuid.uuid4().hex[:12])
    if c2.button("Start over", width="stretch"):
        reset()
        st.rerun()


# ---------- main ----------

init_state()
with st.sidebar:
    name = active_provider_name()
    model = config["providers"].get(name, {}).get("model", "?")
    st.caption(f"Provider: **{name}** · model `{model}`\n\nChange it with PROVIDER in .env.")

if ss.error:
    show_error_and_stop()
{"input": input_screen, "interview": interview_screen, "review": review_screen,
 "result": result_screen}[ss.stage]()
