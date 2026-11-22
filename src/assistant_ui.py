"""Session-scoped sidebar chat; no routing or manager-action callbacks."""
import os

import streamlit as st

from src import assistant as A

HISTORY_KEY = "assistant_history"
ERROR_KEY = "assistant_error"
SUGGESTIONS = (
    ("Explain the program", "How does this program score and assign leads?"),
    ("Explain Manager Review", "Why are leads sent to Manager Review, and what should I check?"),
    ("Summarize this run", "Summarize the current results and the reasons leads need Manager Review."),
)
SIDEBAR_CSS = """<style>
[data-testid="stSidebar"] {background:var(--page-bg) !important; color:var(--page-text);
  border-right:1px solid var(--border);}
[data-testid="stSidebar"] h3 {color:var(--strong);}
[data-testid="stSidebar"] [data-testid="stChatMessage"],
[data-testid="stSidebar"] [data-testid="stChatInput"],
[data-testid="stSidebar"] [data-testid="stChatInput"] > div,
[data-testid="stSidebar"] [data-testid="stAlertContainer"] {
  background:var(--card) !important; color:var(--page-text); border:1px solid var(--border);}
[data-testid="stSidebar"] textarea {background:var(--card) !important; color:var(--text) !important;
  -webkit-text-fill-color:var(--text);}
[data-testid="stSidebar"] textarea::placeholder {color:var(--muted) !important; -webkit-text-fill-color:var(--muted);}
[data-testid="stSidebar"] [data-testid="stChatInputSubmitButton"] {color:var(--btn-text);background:var(--card2);}
[data-testid="stSidebar"] [data-testid="stIconMaterial"] {font-family:"Material Symbols Rounded" !important;}
</style>"""


def clear_assistant_history():
    for key in (HISTORY_KEY, ERROR_KEY):
        st.session_state.pop(key, None)


def _setting(name, default=""):
    value = os.environ.get(name)
    if value is None:
        try:
            value = st.secrets.get(name, default)
        except Exception:
            # Absent or malformed local secrets must not break the dashboard;
            # never display configuration exceptions that may contain secrets.
            value = default
    return value.strip() if isinstance(value, str) else default


def _message(item):
    with st.chat_message(item["role"]):
        st.markdown(item["content"])
        if item.get("sources"):
            st.caption("Based on: " + " · ".join(item["sources"]))


def render_assistant():
    api_key = _setting("GEMINI_API_KEY")
    model = _setting("GEMINI_MODEL", A.DEFAULT_MODEL)
    st.markdown(SIDEBAR_CSS, unsafe_allow_html=True)
    with st.sidebar:
        st.subheader("Ask Assistant")
        st.caption("Ask about scoring, routing, or your current results. Answers only; chat does not change data.")
        st.caption(st.session_state.get("dataset") or "No dataset loaded · program help is available")
        st.caption("Questions, recent chat, and selected result details are sent to Google Gemini.")
        if not api_key:
            st.info("Chat is not configured yet. The app administrator can add GEMINI_API_KEY in the environment "
                    "or Streamlit secrets. The dashboard works without it.")
        history = st.session_state.setdefault(HISTORY_KEY, [])
        suggested = None
        with st.expander("Try a question"):
            for i, (label, question) in enumerate(SUGGESTIONS):
                if st.button(label, key=f"assistant_suggestion_{i}", disabled=not api_key, use_container_width=True):
                    suggested = question
        st.button("Clear chat", key="assistant_clear", on_click=clear_assistant_history,
                  disabled=not history, help="Clear this session's conversation.")
        conversation = st.container(height=350 if history else 100)
        with conversation:
            if not history:
                st.caption("Start with a suggested question, or ask about a lead ID, review reason, or available capacity.")
            for item in history:
                _message(item)
        failed = st.session_state.get(ERROR_KEY)
        retry = False
        if failed:
            st.error(failed)
            retry = st.button("Retry question", key="assistant_retry", disabled=not api_key)
        typed = st.chat_input("Ask about the program or results…", key="assistant_input",
                              max_chars=A.MAX_QUESTION, disabled=not api_key)
        question = typed or suggested
        if retry and history and history[-1]["role"] == "user":
            question = history[-1]["content"]
        elif question:
            if failed and history and history[-1]["role"] == "user":
                history.pop()  # replace the unanswered question, preserving complete turns
            del history[:max(0, len(history) - A.MAX_MESSAGES + 2)]
            history.append({"role": "user", "content": question})
        if not question or not api_key:
            return
        st.session_state.pop(ERROR_KEY, None)
        try:
            with st.spinner("Checking the program and current results…"):
                reply = A.answer_question(question, history[:-1], st.session_state.get("results"),
                                          st.session_state.get("dataset"), api_key=api_key, model=model)
            history.append({"role": "assistant", "content": reply["answer"], "sources": reply["sources"]})
            st.session_state[HISTORY_KEY] = history[-A.MAX_MESSAGES:]
        except A.AssistantError as error:
            st.session_state[ERROR_KEY] = str(error)
        except Exception:
            st.session_state[ERROR_KEY] = "The assistant could not answer right now. Please retry or clear chat."
        st.rerun()
