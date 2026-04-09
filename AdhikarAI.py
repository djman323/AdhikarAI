import asyncio
import os
import re
from typing import Dict, List, Tuple

from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_ollama import OllamaLLM
import requests

from rag_engine import ConstitutionRAGEngine
from storage import ChatStore

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

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash-latest")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "auto").strip().lower()
GEMINI_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-2.0-flash-lite,gemini-2.0-flash,gemini-1.5-flash-latest",
    ).split(",")
    if model.strip()
]
GEMINI_MODEL_DISCOVERY = os.getenv("GEMINI_MODEL_DISCOVERY", "1").strip().lower() not in {"0", "false", "no"}

# Separate API keys for Courtroom Agents
JUDGE_GEMINI_API_KEY = GEMINI_API_KEY
OPPOSING_LAWYER_GEMINI_API_KEY = GEMINI_API_KEY
JUDGE_GEMINI_MODEL = GEMINI_MODEL
OPPOSING_LAWYER_GEMINI_MODEL = GEMINI_MODEL

SYSTEM_PROMPT = """You are Adhikar AI, functioning as both an expert Constitutional lawyer and judicial advisor for Indian law.

You synthesize TWO knowledge domains:
1. PRIMARY: Indian Constitution excerpts from the uploaded materials (cited with [Source N]).
2. SECONDARY: General legal reasoning, precedent principles, and contextual legal knowledge.

JURISDICTION:
You handle TWO types of queries:
A) CONSTITUTIONAL QUESTIONS: "What does Article 21 mean?" "Explain Fundamental Rights"
   → Answer with straight Constitutional interpretation + legal reasoning.
   
B) PRACTICAL LEGAL ISSUES: "I'm facing a land dispute," "My employer wrongfully terminated me," "I've been wrongfully detained"
   → Map the issue to relevant Constitutional rights/remedies [Source citations].
   → Provide legal suggestions based on those Constitutional provisions.
   → Guide user on what rights and processes apply to their situation.

JUDICIAL METHODOLOGY:
- Ground every answer in Constitutional text. Always cite relevant Articles/Parts from the provided context [Source N].
- Apply legal reasoning: interpret Constitutional provisions logically, consider scope, limits, and intent.
- For practical issues: (1) Identify the Constitutional right violated or applicable, (2) Explain user's Constitutional remedy, (3) Suggest actionable steps grounded in the Constitution.
- Draw on general legal knowledge (case law principles, legal doctrines, statutory context) to enhance Constitutional interpretation.
- Present reasoning transparently: state the Constitutional basis AND the legal logic/application.
- Adopt judicial tone: authoritative, reasoned, balanced, and precise.

CORE RULES:
1. Constitution is foundational: Every answer MUST connect to Constitutional provisions in the provided context.
2. Cite always: Include [Source N] for Constitutional excerpts. You may reference general legal principles without [Source] tags.
3. For practical issues: Always specify the relevant Article/Right and the preferred remedy (e.g., "You can file a writ under Article 32," "This violates Article 14, which protects equality").
4. Reason judicially: Explain the WHY—how the Constitution protects the user or applies to their situation.
5. Scope boundaries: Stay within Indian constitutional jurisdiction and Indian law.
6. No fabrication: Never invent Article numbers, Constitutional provisions, or specific case citations.
7. Be brief and precise: Keep each answer concise (normally 90-140 words), focused, and free of repetition unless the user explicitly asks for detail.

RESPONSE STRUCTURE FOR PRACTICAL ISSUES:
- ISSUE ANALYSIS: What happened? What Constitutional right is involved? [Source citations of relevant Articles]
- LEGAL BASIS: Why the Constitution protects the user in this situation (reasoning + principle).
- CONSTITUTIONAL REMEDY: What remedy is available? ("You can file a writ," "You have the right to petition," "Article [X] guarantees...")
- SUGGESTED STEPS: 
  1. Document evidence of the violation
  2. Approach the relevant Constitutional remedy (e.g., file writ before High Court under Article 226, petition Supreme Court under Article 32)
  3. Consult a practicing lawyer to file the appropriate case
- DISCLAIMER: "This is Constitutional legal guidance, not professional legal advice. Consult a practicing lawyer with your case documents for specific guidance."

TONE INSTRUCTION: {response_style_instruction}

Conversation memory:
{memory}

Constitutional Context (Your authority):
{context}

Question from user:
{question}

Provide your judicial analysis or legal suggestion based on the Constitutional framework.
"""

rag_engine = None
STYLE_OPTIONS = {"short_formal", "friendly_concise", "student_friendly"}
chat_store = ChatStore()


def get_rag_engine() -> ConstitutionRAGEngine:
    global rag_engine
    if rag_engine is None:
        rag_engine = ConstitutionRAGEngine()
        rag_engine.ensure_index()
    return rag_engine


def _resolved_provider() -> str:
    if LLM_PROVIDER in {"gemini", "ollama"}:
        return LLM_PROVIDER
    return "gemini" if GEMINI_API_KEY else "ollama"


def _gemini_model_candidates() -> List[str]:
    candidates: List[str] = []

    preferred = GEMINI_MODEL.strip()
    if preferred:
        candidates.append(preferred)

    for model in GEMINI_FALLBACK_MODELS:
        if model not in candidates:
            candidates.append(model)

    # Discover available models for this specific key/project and append any supported names.
    if GEMINI_MODEL_DISCOVERY and GEMINI_API_KEY:
        for model in _discover_gemini_models():
            if model not in candidates:
                candidates.append(model)

    return candidates


def _discover_gemini_models() -> List[str]:
    try:
        response = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": GEMINI_API_KEY},
            timeout=8,
        )
        if response.status_code != 200:
            return []

        payload = response.json() if response.content else {}
        discovered: List[str] = []

        for model in payload.get("models", []):
            methods = model.get("supportedGenerationMethods", []) or []
            if "generateContent" not in methods:
                continue

            name = str(model.get("name", "")).strip()
            if not name:
                continue

            # API returns names as `models/<model-id>`.
            model_id = name.split("/", 1)[1] if name.startswith("models/") else name

            # Prefer lighter models earlier when available.
            if "flash-lite" in model_id:
                discovered.insert(0, model_id)
                continue
            if "flash" in model_id and model_id not in discovered:
                discovered.insert(min(len(discovered), 1), model_id)
                continue

            discovered.append(model_id)

        return discovered
    except Exception:
        return []


def _set_gemini_model(model_name: str) -> None:
    global GEMINI_MODEL, llm
    GEMINI_MODEL = model_name
    llm = ChatGoogleGenerativeAI(
        model=GEMINI_MODEL,
        google_api_key=GEMINI_API_KEY,
        temperature=0.0,
        max_output_tokens=512,
    )


def load_llm():
    provider = _resolved_provider()

    if provider == "gemini":
        if not GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        _set_gemini_model(_gemini_model_candidates()[0])
        return llm

    return OllamaLLM(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0.0,
        num_predict=512,
    )

llm = None


def get_llm():
    global llm
    if llm is None:
        llm = load_llm()
    return llm


def invoke_llm(prompt: str) -> str:
    provider = _resolved_provider()

    if provider == "gemini":
        candidates = _gemini_model_candidates()
        last_error = ""

        for idx, model_name in enumerate(candidates):
            if idx == 0:
                model = get_llm()
            else:
                _set_gemini_model(model_name)
                model = get_llm()

            try:
                output = model.invoke(prompt)
                break
            except Exception as e:
                safe = _redact_secret_values(str(e)).lower()
                if (
                    "not_found" in safe
                    or "is not found" in safe
                    or "resource_exhausted" in safe
                    or "quota exceeded" in safe
                    or "429" in safe
                ):
                    last_error = str(e)
                    continue
                raise
        else:
            raise RuntimeError(
                "No compatible Gemini model found. Tried: "
                + ", ".join(candidates)
                + f". Last error: {_redact_secret_values(last_error)}"
            )
    else:
        output = get_llm().invoke(prompt)

    if isinstance(output, str):
        return output

    content = getattr(output, "content", None)
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        flattened: List[str] = []
        for item in content:
            if isinstance(item, str):
                flattened.append(item)
            elif isinstance(item, dict):
                text = str(item.get("text", "")).strip()
                if text:
                    flattened.append(text)
        if flattened:
            return "\n".join(flattened)

    return str(output)


def _redact_secret_values(text: str) -> str:
    # Mask API keys and consumer key identifiers that may appear in provider errors.
    redacted = re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED_API_KEY]", text)
    redacted = re.sub(r"api_key:[0-9A-Za-z_-]+", "api_key:[REDACTED]", redacted)
    return redacted


def _friendly_provider_error(raw_error: str, provider: str) -> str:
    safe_error = _redact_secret_values(raw_error)
    lowered = safe_error.lower()

    if provider == "gemini":
        if "consumer_suspended" in lowered or "has been suspended" in lowered:
            return (
                "Gemini access is blocked because the configured API consumer is suspended. "
                "Create or enable a new active API key in Google AI Studio or Google Cloud, "
                "enable the Generative Language API, and update GEMINI_API_KEY in your deployment environment."
            )

        if "permission_denied" in lowered or "403" in lowered:
            return (
                "Gemini request was denied. Verify GEMINI_API_KEY, ensure the Generative Language API is enabled, "
                f"and confirm the model '{GEMINI_MODEL}' is available for your project."
            )

        if "not_found" in lowered or "is not found" in lowered:
            return (
                "Gemini model was not found for your API version/project. "
                f"Set GEMINI_MODEL to an available model (current default: '{GEMINI_MODEL}') or configure GEMINI_FALLBACK_MODELS."
            )

        if "resource_exhausted" in lowered or "quota exceeded" in lowered or "429" in lowered:
            return (
                "Gemini quota is exhausted for the configured key/project. "
                f"Try lower-cost models first (current default: '{GEMINI_MODEL}'), reduce request volume, and enable billing or higher quota for Gemini API."
            )

        return (
            f"Gemini request failed: {safe_error}. "
            f"Ensure GEMINI_API_KEY is valid and model '{GEMINI_MODEL}' is available."
        )

    if provider == "ollama":
        return (
            f"Ollama request failed: {safe_error}. "
            f"Ensure Ollama is running and model '{OLLAMA_MODEL}' is available."
        )

    return safe_error


def trim_memory(lines: List[str], max_items: int = 8) -> List[str]:
    if len(lines) <= max_items:
        return lines
    return lines[-max_items:]


def _style_mode(session_id: str = "") -> str:
    if session_id:
        session = chat_store.get_session(session_id)
        from_session = (session or {}).get("response_style", "").strip().lower()
        if from_session in STYLE_OPTIONS:
            return from_session

    normalized = os.getenv("ADHIKAR_RESPONSE_STYLE", "friendly_concise").strip().lower()
    return normalized if normalized in STYLE_OPTIONS else "friendly_concise"


def _style_text(short_formal: str, friendly_concise: str, student_friendly: str, session_id: str = "") -> str:
    mode = _style_mode(session_id)
    if mode == "short_formal":
        return short_formal
    if mode == "student_friendly":
        return student_friendly
    return friendly_concise


def _response_style_instruction(session_id: str = "") -> str:
    return _style_text(
        short_formal="Use formal legal prose with very concise wording. Keep the answer short, precise, and non-repetitive.",
        friendly_concise="Use plain, polite language. Keep the answer short, precise, and non-repetitive.",
        student_friendly="Use simple words and short sentences. Keep the answer short, precise, and non-repetitive.",
        session_id=session_id,
    )


def build_prompt(question: str, context: str, memory_lines: List[str], session_id: str = "") -> str:
    memory_blob = "\n".join(f"- {line}" for line in memory_lines) if memory_lines else "- No user facts recorded yet."
    return SYSTEM_PROMPT.format(
        memory=memory_blob,
        context=context,
        question=question,
        response_style_instruction=_response_style_instruction(session_id),
    )


def _is_greeting_or_smalltalk(query: str) -> bool:
    cleaned = re.sub(r"[^a-zA-Z\s]", "", query).strip().lower()
    if not cleaned:
        return True

    smalltalk = {
        "hi",
        "hello",
        "hey",
        "yo",
        "thanks",
        "thank you",
        "ok",
        "okay",
        "hmm",
    }
    return cleaned in smalltalk


def _smalltalk_reply(query: str, session_id: str = "") -> str:
    cleaned = re.sub(r"[^a-zA-Z\s]", "", query).strip().lower()
    if cleaned in {"thanks", "thank you"}:
        return _style_text(
            short_formal="You are welcome. I am prepared to address your Constitutional questions or legal issues with reasoned legal analysis.",
            friendly_concise="You are welcome. I can help with Constitutional questions OR practical legal issues you face (land disputes, employment problems, wrongful detention, etc.). Ask away.",
            student_friendly="You are welcome. Ask me about the Constitution OR tell me about a legal problem you face, and I'll help with legal suggestions.",
            session_id=session_id,
        )

    return _style_text(
        short_formal="Good day. I am ready to provide Constitutional legal analysis and advice on practical legal matters. Please state your query or describe your legal issue.",
        friendly_concise="Hello. I am your Constitutional lawyer and legal advisor. Ask me about a Constitutional topic (Article, Right, Power) OR describe a legal issue you face (land dispute, job problem, wrongful detention, discrimination, etc.). I'll provide legal guidance based on the Constitution.",
        student_friendly="Hi. I'm your Constitutional lawyer. You can ask about the Constitution OR tell me about a legal problem (land, job, detention, discrimination), and I'll explain your rights and how to protect them.",
        session_id=session_id,
    )


def _looks_like_unclear_query(query: str) -> bool:
    tokens = re.findall(r"[a-zA-Z0-9]+", query.lower())
    if len(tokens) >= 3:
        return False

    constitutional_cues = {
        "article",
        "part",
        "constitution",
        "amendment",
        "fundamental",
        "rights",
        "duty",
        "directive",
        "india",
        "law",
    }
    
    legal_issue_cues = {
        "land",
        "property",
        "dispute",
        "wrongful",
        "terminated",
        "detained",
        "arrested",
        "harassed",
        "violated",
        "discrimination",
        "employment",
        "issue",
    }
    
    return not any(token in constitutional_cues or token in legal_issue_cues for token in tokens)


def _evaluate_specificity(query: str) -> Tuple[bool, List[str]]:
    normalized = query.strip().lower()
    tokens = re.findall(r"[a-zA-Z0-9]+", normalized)

    # Check for Constitutional topics
    has_constitutional_anchor = bool(
        re.search(r"\barticle\s+\d+[a-z]?\b", normalized)
        or re.search(r"\bpart\s+[ivxlc]+\b", normalized)
        or re.search(
            r"\b(constitution|constitutional|fundamental rights|directive principles|amendment|schedule|parliament|president|governor)\b",
            normalized,
        )
    )
    
    # Check for practical legal issues (land, employment, wrongful detention, dispute, violation, etc.)
    has_practical_issue = bool(
        re.search(
            r"\b(land|property|dispute|wrongful|terminated|detained|arrested|harassed|violated|discrimination|denied|refused|violence|assault|theft|fraud|eviction|lease|contract|employment|payment|wage|harassment|threat|illegal|unfair|unjust|forced|coerced)\b",
            normalized,
        )
    )
    
    # Accept either Constitutional topic OR practical legal issue
    has_anchor = has_constitutional_anchor or has_practical_issue
    
    has_intent = bool(
        re.search(
            r"\b(what|how|why|explain|meaning|scope|difference|whether|does|can|valid|protection|powers|limits|facing|help|suggest|remedy|solution|advice)\b",
            normalized,
        )
    )

    missing: List[str] = []
    if len(tokens) < 4:
        missing.append("more detail")
    if not has_anchor:
        missing.append("constitutional topic or legal issue")
    if not has_intent:
        missing.append("what you want to know")

    return len(missing) == 0, missing


def _clarification_prompt(missing: List[str], turn: int, session_id: str = "") -> str:
    if turn >= 2:
        return _style_text(
            short_formal="Clarification required: State your query as: [Constitutional concept/Article/Part] OR [Legal issue you face] + [Specific question: meaning/remedy/suggestion].",
            friendly_concise="I need one more detail. Either ask about a Constitutional topic (Article, Part, Right) OR describe your legal issue (land dispute, employment problem, wrongful detention, etc.) + what help you need.",
            student_friendly="One more thing: Tell me either a Constitution topic (Article, Right, Part) OR your legal problem (like land dispute, job issue) + what you want to know or need help with.",
            session_id=session_id,
        )

    if "constitutional topic or legal issue" in missing and "what you want to know" in missing:
        return _style_text(
            short_formal="Specify: (1) A Constitutional topic (Article/Part/Right) OR a practical legal issue (e.g., land dispute, wrongful termination, wrongful detention); and (2) What you want to know or what remedy/suggestion you need.",
            friendly_concise="Tell me: (1) Are you asking about a Constitution topic (like Article 19, Fundamental Rights) OR do you have a real legal problem (land issue, employment dispute, detention, etc.)? and (2) What help do you need—explanation, legal suggestion, or remedy?",
            student_friendly="Tell me two things: (1) Is it a Constitution question (Article, Right, Power) OR a legal problem you're facing (land, job, wrongful detention)? and (2) What do you want—explanation or legal help?",
            session_id=session_id,
        )

    if "constitutional topic or legal issue" in missing:
        return _style_text(
            short_formal="Please identify: (1) A Constitutional provision (Article/Part), or (2) A legal issue you face (land dispute, employment, wrongful detention, discrimination, etc.).",
            friendly_concise="Please share: Either a Constitutional topic (Article, Part, Right) OR a real legal issue (land problem, job issue, wrongful arrest, etc.).",
            student_friendly="Tell me: A Constitution topic (Article, Part, Right) OR a legal problem you're facing (land, job, detention, etc.)?",
            session_id=session_id,
        )

    if "what you want to know" in missing:
        return _style_text(
            short_formal="State your specific question or what legal suggestion/remedy you seek: meaning, scope, application, comparison, or how to address your issue.",
            friendly_concise="What do you want to know? For Constitutional topics: meaning, scope, limits, comparison. For legal issues: what remedy you can use or what rights protect you.",
            student_friendly="What do you want to know? For Constitution: what it means or how it works. For your legal problem: what can you do about it or what rights you have.",
            session_id=session_id,
        )

    return _style_text(
        short_formal="Please provide one further detail for an accurate Constitutional answer or legal suggestion.",
        friendly_concise="Please add one more detail so I can answer accurately from the Constitutional framework.",
        student_friendly="Please add one more detail so I can help you with Constitution or your legal issue.",
        session_id=session_id,
    )


def _merge_for_clarification(existing: str, incoming: str) -> str:
    existing = existing.strip()
    incoming = incoming.strip()
    if not existing:
        return incoming
    if not incoming:
        return existing
    return f"{existing}. {incoming}"


def _is_grounded_response(text: str, source_count: int) -> bool:
    if not text.strip():
        return False

    tags = re.findall(r"\[Source\s+(\d+)\]", text)
    if not tags:
        return False

    valid_ids = {str(i) for i in range(1, source_count + 1)}
    return all(tag in valid_ids for tag in tags)


def _is_relevant_response(query: str, response: str) -> bool:
    q_tokens = set(re.findall(r"[a-zA-Z0-9]+", query.lower()))
    r_tokens = set(re.findall(r"[a-zA-Z0-9]+", response.lower()))

    stopwords = {
        "the", "a", "an", "is", "are", "was", "were", "to", "of", "for", "and",
        "in", "on", "it", "that", "this", "with", "as", "by", "or", "be", "from",
        "what", "how", "does", "can", "please", "about",
    }

    q_meaningful = {t for t in q_tokens if t not in stopwords and len(t) > 2}
    if not q_meaningful:
        return True

    overlap = q_meaningful.intersection(r_tokens)
    if overlap:
        return True

    query_article = re.search(r"\barticle\s+(\d+[a-z]?)\b", query.lower())
    if query_article and query_article.group(1) in r_tokens:
        return True

    return False


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})


@app.route("/sessions/<session_id>", methods=["GET"])
def get_session(session_id: str):
    session = chat_store.get_session(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404

    return jsonify(
        {
            "session_id": session_id,
            "response_style": session.get("response_style", _style_mode(session_id)),
            "clarification_state": {
                "active": bool(session.get("clarification_active", 0)),
                "turn": int(session.get("clarification_turn", 0)),
                "candidate_query": session.get("clarification_candidate_query", ""),
            },
            "turns": chat_store.list_turns(session_id),
        }
    )

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}
    user_query = (data.get("query") or "").strip()
    session_id = (data.get("session_id") or "default").strip()
    requested_style = (data.get("response_style") or "").strip().lower()

    chat_store.upsert_session(session_id)
    if requested_style in STYLE_OPTIONS:
        chat_store.set_response_style(session_id, requested_style)

    if not user_query:
        return jsonify({"error": "Query parameter is missing"}), 400

    session = chat_store.get_session(session_id) or {}
    in_clarification = bool(session.get("clarification_active", 0))

    if in_clarification:
        merged_query = _merge_for_clarification(str(session.get("clarification_candidate_query", "")), user_query)
        turn = int(session.get("clarification_turn", 0)) + 1
    else:
        merged_query = user_query
        turn = 0

    if _is_greeting_or_smalltalk(merged_query):
        response_text = _smalltalk_reply(merged_query, session_id)
        chat_store.set_clarification_state(session_id, True, turn, merged_query)
        chat_store.save_turn(session_id, user_query, response_text, True, [])
        return jsonify(
            {
                "response": response_text,
                "needs_clarification": True,
                "response_style": _style_mode(session_id),
                "sources": [],
                "session_id": session_id,
            }
        )

    is_specific, missing = _evaluate_specificity(merged_query)
    if (not is_specific) or _looks_like_unclear_query(merged_query):
        response_text = _clarification_prompt(missing, turn, session_id)
        chat_store.set_clarification_state(session_id, True, turn, merged_query)
        chat_store.save_turn(session_id, user_query, response_text, True, [])
        return jsonify(
            {
                "response": response_text,
                "needs_clarification": True,
                "response_style": _style_mode(session_id),
                "sources": [],
                "session_id": session_id,
            }
        )

    chat_store.clear_clarification_state(session_id)

    try:
        engine = get_rag_engine()
        search_results = engine.search(merged_query)
        context, sources = engine.build_context(search_results)

        history = chat_store.get_history_lines(session_id)
        history = trim_memory(history)

        full_prompt = build_prompt(merged_query, context, history, session_id)
        llm_response = invoke_llm(full_prompt)

        if not _is_relevant_response(merged_query, llm_response):
            response_text = _style_text(
                short_formal="One additional detail is required. Please restate your question with the exact constitutional issue and precise point to address.",
                friendly_concise="I need one more detail to answer this properly. Please restate your question with the exact constitutional issue and the specific point you want me to address.",
                student_friendly="I need one more detail. Please restate your question with the exact Constitution topic and what exactly you want me to explain.",
                session_id=session_id,
            )
            chat_store.set_clarification_state(session_id, True, turn + 1, merged_query)
            chat_store.save_turn(session_id, user_query, response_text, True, [])
            return jsonify(
                {
                    "response": response_text,
                    "needs_clarification": True,
                    "response_style": _style_mode(session_id),
                    "sources": [],
                    "session_id": session_id,
                }
            )

        chat_store.save_turn(session_id, user_query, llm_response, False, sources)

        return jsonify(
            {
                "response": llm_response,
                "needs_clarification": False,
                "response_style": _style_mode(session_id),
                "sources": sources,
                "session_id": session_id,
            }
        )
    except Exception as e:
        provider = _resolved_provider()
        err = _friendly_provider_error(str(e), provider)
        return jsonify({"error": err}), 500


# ============= COURTROOM AI AGENTS =============

class CourtroomStore:
    """Stores courtroom session data"""
    def __init__(self):
        self.sessions = {}
    
    def create_session(self, session_id: str, case_data: dict) -> None:
        self.sessions[session_id] = {
            "case_id": case_data.get("case_id"),
            "case_details": case_data.get("case_details", {}),
            "turns": [],
            "judge_evaluations": [],
            "lawyer_evaluations": [],
        }
    
    def add_turn(self, session_id: str, student_argument: str, judge_response: str, lawyer_response: str) -> None:
        if session_id in self.sessions:
            self.sessions[session_id]["turns"].append({
                "student": student_argument,
                "judge": judge_response,
                "lawyer": lawyer_response,
            })
    
    def get_session(self, session_id: str) -> dict:
        return self.sessions.get(session_id, {})
    
    def get_turns(self, session_id: str) -> list:
        return self.sessions.get(session_id, {}).get("turns", [])


courtroom_store = CourtroomStore()


# ===== Separate LLM Instances for Courtroom Agents =====
judge_llm = None
opposing_lawyer_llm = None


def get_judge_llm():
    """Get or create the Judge AI Agent's LLM instance"""
    global judge_llm
    if judge_llm is None:
        if not JUDGE_GEMINI_API_KEY:
            raise ValueError("JUDGE_GEMINI_API_KEY is required for Judge AI Agent")
        
        # Use the main model candidates logic
        candidates = _gemini_model_candidates()
        if not candidates:
            raise RuntimeError("No Gemini models available for Judge AI Agent")

        # Prioritize a known good model if available, otherwise use the first candidate
        model_to_use = "gemini-1.5-flash" if "gemini-1.5-flash" in candidates else candidates[0]
        
        judge_llm = ChatGoogleGenerativeAI(
            model=model_to_use,
            google_api_key=JUDGE_GEMINI_API_KEY,
            temperature=0.7,
            max_output_tokens=512,
        )
    return judge_llm


def get_opposing_lawyer_llm():
    """Get or create the Opposing Lawyer AI Agent's LLM instance"""
    global opposing_lawyer_llm
    if opposing_lawyer_llm is None:
        if not OPPOSING_LAWYER_GEMINI_API_KEY:
            raise ValueError("OPPOSING_LAWYER_GEMINI_API_KEY is required for Opposing Lawyer AI Agent")

        # Use the main model candidates logic
        candidates = _gemini_model_candidates()
        if not candidates:
            raise RuntimeError("No Gemini models available for Opposing Lawyer AI Agent")

        # Prioritize a known good model if available, otherwise use the first candidate
        model_to_use = "gemini-1.5-flash" if "gemini-1.5-flash" in candidates else candidates[0]

        opposing_lawyer_llm = ChatGoogleGenerativeAI(
            model=model_to_use,
            google_api_key=OPPOSING_LAWYER_GEMINI_API_KEY,
            temperature=0.7,
            max_output_tokens=512,
        )
    return opposing_lawyer_llm


def invoke_agent_llm_with_fallback(get_llm_func, prompt: str, agent_name: str) -> str:
    """Invoke an agent LLM with a fallback mechanism."""
    candidates = _gemini_model_candidates()
    last_error = ""

    for model_name in candidates:
        try:
            # This is a bit of a hack: we're creating a new LLM instance for each try.
            # In a real app, you'd manage this more cleanly.
            llm_instance = ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=os.getenv("GEMINI_API_KEY", "").strip(), # Assuming single API key now
                temperature=0.7,
                max_output_tokens=512,
            )
            output = llm_instance.invoke(prompt)
            
            if isinstance(output, str):
                return output

            # Handle AIMessage objects from LangChain
            content = getattr(output, "content", None)
            if isinstance(content, str):
                return content
            
            # Handle cases where content is a list of dicts
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and 'text' in item:
                        return item['text']

            # Fallback for other unexpected structures
            return str(output)

        except Exception as e:
            safe_error = _redact_secret_values(str(e)).lower()
            if (
                "not_found" in safe_error
                or "is not found" in safe_error
                or "resource_exhausted" in safe_error
                or "quota exceeded" in safe_error
                or "429" in safe_error
                or "404" in safe_error
            ):
                last_error = str(e)
                continue  # Try the next model
            raise # Re-raise unexpected errors

    # If all models failed
    raise RuntimeError(
        f"{agent_name} LLM failed. Tried: "
        + ", ".join(candidates)
        + f". Last error: {_redact_secret_values(last_error)}"
    )


def invoke_judge_agent_llm(prompt: str) -> str:
    """Invoke Judge LLM with separate API key"""
    return invoke_agent_llm_with_fallback(get_judge_llm, prompt, "Judge Agent")


def invoke_opposing_lawyer_agent_llm(prompt: str) -> str:
    """Invoke Opposing Lawyer LLM with separate API key"""
    return invoke_agent_llm_with_fallback(get_opposing_lawyer_llm, prompt, "Opposing Lawyer Agent")


def generate_judge_prompt(case_details: dict, student_argument: str, previous_turns: List[dict]) -> str:
    """Generate prompt for the Judge AI Agent"""
    case_info = f"""
Case Details:
- Accused: {case_details.get('accused', 'N/A')}
- Charges: {', '.join(case_details.get('charges', []))}
- Victim Statement: {case_details.get('victimStatement', 'N/A')}
- Key Evidence: {', '.join(case_details.get('evidence', []))}

Student Lawyer's Current Argument:
{student_argument}

Previous exchanges (if any):
"""
    for i, turn in enumerate(previous_turns[-3:]):  # Last 3 turns
        case_info += f"\nTurn {i+1} - Student: {turn.get('student', '')}\nJudge evaluation: ...existing context...\n"
    
    prompt = f"""You are a strict but fair Judge presiding over this court case. Your responsibilities:
1. EVALUATE the legal argument presented by the defense lawyer (student)
2. ASK PROBING QUESTIONS to test their legal knowledge
3. POINT OUT WEAKNESSES or gaps in their reasoning
4. MAINTAIN COURT DECORUM and legal procedure
5. Be fair but challenging - this is a learning opportunity

{case_info}

Respond as the Judge would in a real courtroom. Be concise (2-3 sentences). Ask a tough but fair question or point out a specific legal issue.
Response: """
    return prompt


def generate_lawyer_prompt(case_details: dict, student_argument: str, previous_turns: List[dict]) -> str:
    """Generate prompt for the Opposing Lawyer AI Agent"""
    case_info = f"""
Case Details:
- Accused: {case_details.get('accused', 'N/A')}
- Charges: {', '.join(case_details.get('charges', []))}
- Victim: {case_details.get('victim', 'N/A')}
- Supporting Evidence: {', '.join(case_details.get('evidence', []))}

Student Defense Lawyer's Argument:
{student_argument}

Previous exchanges (if any):
"""
    for i, turn in enumerate(previous_turns[-3:]):
        case_info += f"\nTurn {i+1} - Student: {turn.get('student', '')}\n...existing context...\n"
    
    prompt = f"""You are the Prosecuting/Opposing Lawyer in this court case. Your role:
1. COUNTER the defense lawyer's arguments with prosecutorial points
2. HIGHLIGHT EVIDENCE that contradicts their claims
3. CHALLENGE WEAK POINTS in their legal reasoning
4. MAINTAIN PROFESSIONAL COURTROOM DEMEANOR
5. Point out procedural errors if any

{case_info}

Respond as an opposing counsel would. Be direct and use evidence from the case. Keep it to 2-3 sentences.
Counter-argument: """
    return prompt


def invoke_judge_agent(case_details: dict, student_argument: str, turns: List[dict]) -> str:
    """Invoke the Judge AI Agent with separate API key"""
    prompt = generate_judge_prompt(case_details, student_argument, turns)
    return invoke_judge_agent_llm(prompt)


def invoke_lawyer_agent(case_details: dict, student_argument: str, turns: List[dict]) -> str:
    """Invoke the Opposing Lawyer AI Agent with separate API key"""
    prompt = generate_lawyer_prompt(case_details, student_argument, turns)
    return invoke_opposing_lawyer_agent_llm(prompt)


def evaluate_student_performance(session_id: str) -> dict:
    """Evaluate the student's overall courtroom performance"""
    session = courtroom_store.get_session(session_id)
    turns = session.get("turns", [])
    case_details = session.get("case_details", {})
    
    if not turns:
        return {
            "legal_reasoning_score": 0,
            "argument_strength": 0,
            "procedure_score": 0,
            "overall_score": 0,
            "grade": "N/A",
            "feedback": "No turns recorded",
            "strengths": [],
            "areas_to_improve": []
        }
    
    # Calculate scores based on number of turns, depth of arguments, etc.
    num_turns = len(turns)
    score_multiplier = min(100, 40 + (num_turns * 5))  # More turns = higher base score
    
    # Analyze arguments for specific legal concepts
    all_arguments = " ".join([t.get("student", "") for t in turns]).lower()
    legal_keywords = ["article", "constitution", "evidence", "witness", "testimony", "procedure", "reasonable doubt", "burden of proof"]
    legal_concept_mentions = sum(1 for keyword in legal_keywords if keyword in all_arguments)
    
    legal_reasoning_score = min(100, 50 + (legal_concept_mentions * 5))
    argument_strength = min(100, 45 + (num_turns * 4))
    procedure_score = min(100, 50 + (legal_concept_mentions * 3))
    overall_score = int((legal_reasoning_score + argument_strength + procedure_score) / 3)
    
    # Determine grade and feedback
    if overall_score >= 85:
        grade = "A - Excellent"
        feedback = "Outstanding legal reasoning and argumentation. You demonstrated strong constitutional knowledge and courtroom procedure."
        strengths = ["Strong legal foundation", "Clear articulation of arguments", "Good use of evidence", "Proper courtroom decorum"]
        improvements = ["Consider citing specific articles", "Develop counterarguments further"]
    elif overall_score >= 70:
        grade = "B - Good"
        feedback = "Good performance with solid understanding of legal concepts. You made valid arguments but have room for deeper analysis."
        strengths = ["Solid legal reasoning", "Relevant arguments presented", "Proper procedure mostly followed"]
        improvements = ["Strengthen constitutional references", "Better anticipate opposing arguments", "More detailed case analysis"]
    elif overall_score >= 55:
        grade = "C - Fair"
        feedback = "Average performance. Your arguments were relevant but lacked depth and legal grounding. Study more legal principles."
        strengths = ["Engaged in the debate", "Made some valid points"]
        improvements = ["Deepen constitutional law knowledge", "Better structure arguments", "Use more evidence from case", "Improve legal vocabulary"]
    else:
        grade = "D - Needs Improvement"
        feedback = "Your performance needs significant improvement. Focus on building stronger legal and constitutional foundations."
        strengths = ["Participation in courtroom exercise"]
        improvements = ["Study Indian Constitution articles", "Learn burden of proof concepts", "Practice argument structure", "Review case evidence more carefully"]
    
    return {
        "legal_reasoning_score": legal_reasoning_score,
        "argument_strength": argument_strength,
        "procedure_score": procedure_score,
        "overall_score": overall_score,
        "grade": grade,
        "feedback": feedback,
        "strengths": strengths,
        "areas_to_improve": improvements,
    }


@app.route("/courtroom/start", methods=["POST"])
def courtroom_start():
    """Initialize a new courtroom session"""
    data = request.json or {}
    session_id = (data.get("session_id") or "courtroom-default").strip()
    case_id = (data.get("case_id") or "").strip()
    case_details = data.get("case_details") or {}
    
    if not case_details:
        return jsonify({"error": "Case details are required"}), 400
    
    try:
        # Create courtroom session
        courtroom_store.create_session(session_id, {
            "case_id": case_id,
            "case_details": case_details,
        })
        
        # Generate opening statement from judge
        opening_prompt = f"""You are the Judge presiding over this case. Give a brief opening statement (2-3 sentences) setting the stage for the courtroom debate.

Case: {case_details.get('charges', ['Case'])[0] if case_details.get('charges') else 'Case'}
Accused: {case_details.get('accused', 'N/A')}

Opening Statement: """
        
        judge_opening = invoke_judge_agent_llm(opening_prompt)
        
        return jsonify({
            "session_id": session_id,
            "opening": [
                {
                    "speaker": "Judge",
                    "text": judge_opening,
                    "type": "judge",
                }
            ],
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/courtroom/turn", methods=["POST"])
def courtroom_turn():
    """Process a turn in the courtroom debate"""
    data = request.json or {}
    session_id = (data.get("session_id") or "").strip()
    student_argument = (data.get("student_argument") or "").strip()
    
    if not session_id or not student_argument:
        return jsonify({"error": "session_id and student_argument are required"}), 400
    
    try:
        session = courtroom_store.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404
        
        case_details = session.get("case_details", {})
        previous_turns = session.get("turns", [])
        
        # Get judge response
        judge_response = invoke_judge_agent(case_details, student_argument, previous_turns)
        
        # Get opposing lawyer response
        lawyer_response = invoke_lawyer_agent(case_details, student_argument, previous_turns)
        
        # Save this turn
        courtroom_store.add_turn(session_id, student_argument, judge_response, lawyer_response)
        
        return jsonify({
            "judge_response": judge_response,
            "lawyer_response": lawyer_response,
            "turn_number": len(courtroom_store.get_turns(session_id)),
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/courtroom/evaluate", methods=["POST"])
def courtroom_evaluate():
    """Evaluate student performance and generate stats"""
    data = request.json or {}
    session_id = (data.get("session_id") or "").strip()
    
    if not session_id:
        return jsonify({"error": "session_id is required"}), 400
    
    try:
        session = courtroom_store.get_session(session_id)
        if not session:
            return jsonify({"error": "Session not found"}), 404
        
        stats = evaluate_student_performance(session_id)
        
        return jsonify({
            "stats": stats,
            "session_id": session_id,
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)