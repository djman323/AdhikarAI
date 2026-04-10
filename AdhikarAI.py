import asyncio
import os
import re
from typing import Any, Dict, List

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv()

try:
    asyncio.get_running_loop()
except RuntimeError:
    asyncio.set_event_loop(asyncio.new_event_loop())

app = Flask(__name__)


def _cors_origins_from_env() -> str | List[str]:
    configured = os.getenv("ADHIKAR_CORS_ORIGINS", "*").strip()
    if not configured or configured == "*":
        return "*"
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


CORS(app, resources={r"/*": {"origins": _cors_origins_from_env()}})

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest").strip()
GEMINI_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-2.5-flash,gemini-2.5-pro,gemini-2.0-flash,gemini-2.0-flash-lite",
    ).split(",")
    if model.strip()
]


def _env_value(name: str) -> str:
    return os.getenv(name, "").strip()


GEMINI_API_KEY_CANDIDATES = [
    key
    for key in [
        _env_value("GEMINI_API_KEY"),
        _env_value("JUDGE_GEMINI_API_KEY"),
        _env_value("OPPOSING_LAWYER_GEMINI_API_KEY"),
        _env_value("FOURTH_GEMINI_API_KEY"),
        _env_value("FIFTH_GEMINI_API_KEY"),
    ]
    if key
]


class CourtroomStore:
    def __init__(self) -> None:
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def create_session(self, session_id: str, case_id: str, case_details: Dict[str, Any]) -> None:
        self.sessions[session_id] = {
            "session_id": session_id,
            "case_id": case_id,
            "case_details": case_details,
            "turns": [],
        }

    def get_session(self, session_id: str) -> Dict[str, Any] | None:
        return self.sessions.get(session_id)

    def add_turn(self, session_id: str, student: str, judge: str, lawyer: str) -> None:
        session = self.sessions.get(session_id)
        if not session:
            return
        session["turns"].append(
            {
                "student": student,
                "judge": judge,
                "lawyer": lawyer,
            }
        )


courtroom_store = CourtroomStore()


def _redact_error(text: str) -> str:
    redacted = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED_API_KEY]", text)
    return re.sub(r"api_key:[0-9A-Za-z_-]+", "api_key:[REDACTED]", redacted)


def _gemini_candidates() -> List[str]:
    candidates: List[str] = []
    if GEMINI_MODEL:
        candidates.append(GEMINI_MODEL)
    for model in GEMINI_FALLBACK_MODELS:
        if model not in candidates:
            candidates.append(model)

    # Always include resilient defaults in case .env pins quota-exhausted models.
    for safe_default in ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.0-flash", "gemini-2.0-flash-lite"]:
        if safe_default not in candidates:
            candidates.append(safe_default)
    return candidates


def _gemini_api_keys() -> List[str]:
    # Preserve order while removing duplicates.
    return list(dict.fromkeys(GEMINI_API_KEY_CANDIDATES))


def _extract_text(output: Any) -> str:
    if isinstance(output, str):
        return output

    content = getattr(output, "content", None)
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        chunks: List[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
            elif isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                if text:
                    chunks.append(text)
        if chunks:
            return "\n".join(chunks)

    return str(output)


def invoke_llm_with_fallback(prompt: str, fallback_text: str, temperature: float = 0.6) -> str:
    api_keys = _gemini_api_keys()
    if not api_keys:
        return fallback_text

    model_candidates = _gemini_candidates()
    last_error = ""

    for api_key in api_keys:
        for model_name in model_candidates:
            try:
                llm = ChatGoogleGenerativeAI(
                    model=model_name,
                    google_api_key=api_key,
                    temperature=temperature,
                    max_output_tokens=512,
                    thinking_budget=0,
                )
                output = llm.invoke(prompt)
                text = _extract_text(output).strip()
                if text:
                    return text
            except Exception as exc:
                safe = _redact_error(str(exc)).lower()
                last_error = safe
                if (
                    "resource_exhausted" in safe
                    or "quota exceeded" in safe
                    or "429" in safe
                    or "not_found" in safe
                    or "404" in safe
                    or "permission_denied" in safe
                    or "403" in safe
                    or "consumer_suspended" in safe
                ):
                    continue
                continue

    print(f"[WARN] LLM fallback used. Last error: {last_error}")
    return fallback_text


def _case_facts(case_details: Dict[str, Any]) -> str:
    charges = ", ".join(case_details.get("charges", [])) or "N/A"
    evidence = ", ".join(case_details.get("evidence", [])) or "N/A"
    victim = case_details.get("victim", "N/A")
    accused = case_details.get("accused", "N/A")
    return (
        f"Victim: {victim}\n"
        f"Accused: {accused}\n"
        f"Charges: {charges}\n"
        f"Evidence: {evidence}"
    )


def generate_judge_opening(case_details: Dict[str, Any]) -> str:
    facts = _case_facts(case_details)
    fallback = (
        "Court is now in session. The defense may proceed with its opening argument, "
        "and the court will examine the evidence and charges on record with due fairness."
    )
    prompt = (
        "You are a Judge in an Indian courtroom. Give a formal opening statement in 2-3 sentences.\n\n"
        f"Case facts:\n{facts}\n"
    )
    return invoke_llm_with_fallback(prompt, fallback, temperature=0.4)


def generate_judge_turn(case_details: Dict[str, Any], student_argument: str, turns: List[Dict[str, str]]) -> str:
    facts = _case_facts(case_details)
    previous = "\n".join(
        [
            f"Turn {idx + 1} Student: {turn.get('student', '')}"
            for idx, turn in enumerate(turns[-3:])
        ]
    )
    fallback = (
        "The court notes your submission. Clarify how your argument addresses the evidentiary record "
        "and the specific statutory elements of the alleged offense."
    )
    prompt = (
        "You are a strict but fair Judge in an Indian courtroom.\n"
        "Assess the student advocate's argument, point out one weakness, and ask one probing legal question in 2-3 sentences.\n\n"
        f"Case facts:\n{facts}\n\n"
        f"Previous turns:\n{previous or 'None'}\n\n"
        f"Student argument:\n{student_argument}\n"
    )
    return invoke_llm_with_fallback(prompt, fallback)


def generate_opposing_lawyer_turn(case_details: Dict[str, Any], student_argument: str, turns: List[Dict[str, str]]) -> str:
    facts = _case_facts(case_details)
    previous = "\n".join(
        [
            f"Turn {idx + 1} Lawyer: {turn.get('lawyer', '')}"
            for idx, turn in enumerate(turns[-3:])
        ]
    )
    fallback = (
        "The defense contention is unconvincing as stated. The prosecution relies on documentary and witness "
        "material that directly supports the pleaded charges."
    )
    prompt = (
        "You are the opposing lawyer in an Indian courtroom.\n"
        "Respond with 2-3 sentences that challenge the student advocate's argument with legal counter-points.\n\n"
        f"Case facts:\n{facts}\n\n"
        f"Previous turns:\n{previous or 'None'}\n\n"
        f"Student argument:\n{student_argument}\n"
    )
    return invoke_llm_with_fallback(prompt, fallback)


def evaluate_session(turns: List[Dict[str, str]]) -> Dict[str, Any]:
    if not turns:
        return {
            "overall_score": 0,
            "argument_clarity": 0,
            "legal_reasoning": 0,
            "evidence_usage": 0,
            "courtroom_manner": 0,
            "summary": "No arguments were submitted.",
            "strengths": [],
            "improvements": ["Present at least one structured legal argument."],
        }

    count = len(turns)
    base = min(10, 4 + count)
    return {
        "overall_score": base,
        "argument_clarity": max(1, base - 1),
        "legal_reasoning": base,
        "evidence_usage": max(1, base - 2),
        "courtroom_manner": min(10, base + 1),
        "summary": "Your submissions addressed the dispute and engaged with courtroom dialogue.",
        "strengths": [
            "Maintained participation across multiple turns.",
            "Responded to judicial prompts.",
        ],
        "improvements": [
            "Cite specific legal provisions in each argument.",
            "Link each claim directly to available evidence.",
        ],
    }


@app.route("/health", methods=["GET"])
def health() -> Any:
    return jsonify({"status": "ok", "backend_version": "chat-fallback-fix-v1"})


@app.route("/courtroom/start", methods=["POST"])
def courtroom_start() -> Any:
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", "")).strip()
    case_id = str(data.get("case_id", "")).strip()
    case_details = data.get("case_details")

    if not session_id or not isinstance(case_details, dict):
        return jsonify({"error": "Session ID and case details are required"}), 400

    courtroom_store.create_session(session_id, case_id, case_details)
    opening = generate_judge_opening(case_details)

    return jsonify(
        {
            "session_id": session_id,
            "opening": [
                {
                    "speaker": "Judge",
                    "text": opening,
                    "type": "judge",
                }
            ],
        }
    )


@app.route("/courtroom/turn", methods=["POST"])
def courtroom_turn() -> Any:
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", "")).strip()
    student_argument = str(data.get("student_argument") or data.get("argument") or "").strip()

    if not session_id or not student_argument:
        return jsonify({"error": "Session ID and argument are required"}), 400

    session = courtroom_store.get_session(session_id)
    if not session:
        return jsonify({"error": "Courtroom session not found"}), 404

    case_details = session.get("case_details", {})
    turns = session.get("turns", [])

    judge_response = generate_judge_turn(case_details, student_argument, turns)
    lawyer_response = generate_opposing_lawyer_turn(case_details, student_argument, turns)

    courtroom_store.add_turn(session_id, student_argument, judge_response, lawyer_response)

    return jsonify(
        {
            "judge_response": judge_response,
            "lawyer_response": lawyer_response,
        }
    )


@app.route("/courtroom/evaluate", methods=["POST"])
def courtroom_evaluate() -> Any:
    data = request.get_json(silent=True) or {}
    session_id = str(data.get("session_id", "")).strip()

    if not session_id:
        return jsonify({"error": "Session ID is required"}), 400

    session = courtroom_store.get_session(session_id)
    if not session:
        return jsonify({"error": "Courtroom session not found"}), 404

    stats = evaluate_session(session.get("turns", []))
    return jsonify({"stats": stats})


@app.route("/chat", methods=["POST"])
def chat() -> Any:
    data = request.get_json(silent=True) or {}
    query = str(data.get("query", "")).strip()
    if not query:
        return jsonify({"error": "Query parameter is missing"}), 400

    fallback = (
        "I could not reach the legal model right now. Please retry in a few moments. "
        "If this persists, switch to another Gemini key or model in your environment settings."
    )
    prompt = (
        "You are Adhikar AI, an Indian constitutional legal assistant. "
        "Answer in concise plain English with practical legal direction.\n\n"
        f"User query: {query}"
    )
    response_text = invoke_llm_with_fallback(prompt, fallback, temperature=0.3)

    return jsonify(
        {
            "response": response_text,
            "needs_clarification": False,
            "response_style": "friendly_concise",
            "sources": [],
            "session_id": str(data.get("session_id") or "default"),
        }
    )


if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "5000"))
    print(f"[INFO] Starting Adhikar AI backend on http://{host}:{port}")
    app.run(debug=True, host=host, port=port)
