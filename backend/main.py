from __future__ import annotations

import os
import re
import json
import hashlib
import shutil
import tempfile
from pathlib import Path
from typing import Optional, Any

from dotenv import load_dotenv

load_dotenv()


# ============================================================
# OPTIONAL / EXTERNAL IMPORTS
# ============================================================

from fastapi import (
    FastAPI,
    HTTPException,
    UploadFile,
    File,
    Header,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    JSONResponse,
    StreamingResponse,
    FileResponse,
)
from pydantic import BaseModel, Field

import chromadb
from chromadb import PersistentClient

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    import firebase_admin
    from firebase_admin import credentials, auth as firebase_auth
except Exception:
    firebase_admin = None
    credentials = None
    firebase_auth = None


# ============================================================
# PATHS / CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

PDF_DIR = BASE_DIR / "data" / "pdfs"
PDF_DIR.mkdir(parents=True, exist_ok=True)

FRONT = BASE_DIR.parent / "frontend"

CHROMA_DIR = Path(
    os.getenv(
        "CHROMA_DIR",
        str(BASE_DIR / "data" / "chroma"),
    )
)

CHROMA_DIR.mkdir(parents=True, exist_ok=True)

COLLECTION_NAME = "study_documents"

LLM_PROVIDER = os.getenv(
    "LLM_PROVIDER",
    "groq",
).lower()

LLM_MODEL = os.getenv(
    "LLM_MODEL",
    "openai/gpt-oss-20b",
)

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
XAI_API_KEY = os.getenv("XAI_API_KEY", "")

ENVIRONMENT = os.getenv(
    "ENVIRONMENT",
    "development",
).lower()

ALLOW_DEV_AUTH = os.getenv(
    "ALLOW_DEV_AUTH",
    "true",
).lower() == "true"


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="AI Study Assistant",
    version="1.0.0",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://127.0.0.1",
        "http://localhost:3000",
        "http://localhost:5173",
        "https://margin-notes-e0c49.web.app",
        "https://margin-notes-e0c49.firebaseapp.com",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# CHROMA
# ============================================================

client = PersistentClient(
    path=str(CHROMA_DIR)
)

collection = client.get_or_create_collection(
    name=COLLECTION_NAME,
    metadata={
        "hnsw:space": "cosine",
    },
)

# Alias used by tests / older code
col = collection


# ============================================================
# FIREBASE
# ============================================================

firebase_initialized = False


def init_firebase():
    global firebase_initialized

    if firebase_initialized:
        return

    if firebase_admin is None:
        return

    try:
        if firebase_admin._apps:
            firebase_initialized = True
            return

        project_id = os.getenv("FIREBASE_PROJECT_ID")

        # Firebase service account through environment JSON
        service_json = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON")

        if service_json:
            info = json.loads(service_json)

            cred = credentials.Certificate(info)

            firebase_admin.initialize_app(
                cred,
                {
                    "projectId": project_id,
                }
                if project_id
                else {},
            )

            firebase_initialized = True
            return

        # Try GOOGLE_APPLICATION_CREDENTIALS
        google_creds = os.getenv(
            "GOOGLE_APPLICATION_CREDENTIALS"
        )

        if google_creds and Path(google_creds).exists():
            cred = credentials.Certificate(
                google_creds
            )

            firebase_admin.initialize_app(
                cred,
                {
                    "projectId": project_id,
                }
                if project_id
                else {},
            )

            firebase_initialized = True
            return

    except Exception as exc:
        print(
            "Firebase initialization warning:",
            exc,
        )


init_firebase()


# ============================================================
# AUTHENTICATION
# ============================================================

def verify_auth(
    authorization: Optional[str] = Header(default=None),
):
    """
    Authentication behavior:

    Development/testing:
        Missing token is allowed.

    Production:
        Firebase ID token is required.
    """

    # --------------------------------------------------------
    # Development / test mode
    # --------------------------------------------------------

    if not authorization:

        if (
            ENVIRONMENT in {
                "development",
                "dev",
                "test",
            }
            or ALLOW_DEV_AUTH
        ):
            return {
                "uid": "dev",
                "email": "dev@localhost",
            }

        raise HTTPException(
            status_code=401,
            detail="Authorization header required.",
        )

    # --------------------------------------------------------
    # Authorization format
    # --------------------------------------------------------

    if not authorization.lower().startswith(
        "bearer "
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid Authorization header.",
        )

    token = authorization.split(
        " ",
        1,
    )[1].strip()

    if not token:
        raise HTTPException(
            status_code=401,
            detail="Invalid token.",
        )

    # Frontend development token
    if token == "dev":
        return {
            "uid": "dev",
            "email": "dev@localhost",
        }

    # --------------------------------------------------------
    # Firebase verification
    # --------------------------------------------------------

    if firebase_auth is None:
        if (
            ENVIRONMENT in {
                "development",
                "dev",
                "test",
            }
            or ALLOW_DEV_AUTH
        ):
            return {
                "uid": "dev",
                "email": "dev@localhost",
            }

        raise HTTPException(
            status_code=500,
            detail="Firebase Admin is not configured.",
        )

    try:
        decoded = firebase_auth.verify_id_token(
            token
        )

        return decoded

    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Invalid authentication token.",
        )


# ============================================================
# LLM CLIENT
# ============================================================

llm_client = None


def create_llm_client():

    provider = LLM_PROVIDER

    if provider == "groq":

        if not GROQ_API_KEY:
            print(
                "WARNING: GROQ_API_KEY is not configured."
            )
            return None, "groq", LLM_MODEL

        if OpenAI is None:
            print(
                "WARNING: openai package is unavailable."
            )
            return None, "groq", LLM_MODEL

        try:
            c = OpenAI(
                api_key=GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )

            print("Groq LLM client initialized.")

            return c, "groq", LLM_MODEL

        except Exception as exc:
            print(
                "Groq initialization error:",
                exc,
            )

            return None, "groq", LLM_MODEL

    if provider == "grok":

        if not XAI_API_KEY:
            print(
                "WARNING: XAI_API_KEY is not configured."
            )

            return None, "grok", LLM_MODEL

        if OpenAI is None:
            return None, "grok", LLM_MODEL

        try:
            c = OpenAI(
                api_key=XAI_API_KEY,
                base_url="https://api.x.ai/v1",
            )

            print("xAI Grok client initialized.")

            return c, "grok", LLM_MODEL

        except Exception as exc:
            print(
                "Grok initialization error:",
                exc,
            )

            return None, "grok", LLM_MODEL

    print(
        "WARNING: Unknown LLM_PROVIDER:",
        provider,
    )

    return None, provider, LLM_MODEL


def get_llm():

    global llm_client

    # --------------------------------------------------------
    # Important for offline tests
    # --------------------------------------------------------

    if callable(llm_client):
        result = llm_client()

        if isinstance(result, tuple):
            return result

        return (
            result,
            "fake",
            LLM_MODEL,
        )

    # --------------------------------------------------------
    # Normal client
    # --------------------------------------------------------

    if llm_client is not None:
        return (
            llm_client,
            LLM_PROVIDER,
            LLM_MODEL,
        )

    llm_client, provider, model = (
        create_llm_client()
    )

    return (
        llm_client,
        provider,
        model,
    )


# ============================================================
# PDF EXTRACTION
# ============================================================

def extract_pdf_text(path: Path) -> str:

    if PdfReader is None:
        raise RuntimeError(
            "pypdf is not installed."
        )

    reader = PdfReader(str(path))

    pages = []

    for page in reader.pages:

        try:
            txt = page.extract_text() or ""

        except Exception:
            txt = ""

        if txt.strip():
            pages.append(txt)

    return "\n".join(pages).strip()


# ============================================================
# TEXT CHUNKING
# ============================================================

def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 80,
):
    """
    Split PDF text into overlapping chunks.

    This intentionally uses a relatively small chunk size
    so the five study PDFs do not become only five chunks.
    """

    text = re.sub(
        r"\s+",
        " ",
        text or "",
    ).strip()

    if not text:
        return []

    # Very small document
    if len(text) <= 350:
        return [text]

    chunks = []

    start = 0

    while start < len(text):

        end = min(
            start + chunk_size,
            len(text),
        )

        # Prefer a natural word boundary
        if end < len(text):

            boundary = text.rfind(
                " ",
                start,
                end,
            )

            if boundary > start + 200:
                end = boundary

        chunk = text[
            start:end
        ].strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(text):
            break

        start = max(
            end - overlap,
            start + 1,
        )

    # Safety:
    # If a sufficiently large document somehow
    # produced only one chunk, split it in half.
    if (
        len(chunks) == 1
        and len(text) > 500
    ):
        mid = len(text) // 2

        first = text[:mid].strip()
        second = text[mid:].strip()

        if first and second:
            chunks = [
                first,
                second,
            ]

    return chunks


# ============================================================
# DOCUMENT ID
# ============================================================

def make_document_id(
    filename: str,
    chunk_index: int,
    text: str,
):
    raw = (
        f"{filename}|"
        f"{chunk_index}|"
        f"{text}"
    )

    return hashlib.sha256(
        raw.encode(
            "utf-8",
            errors="ignore",
        )
    ).hexdigest()


# ============================================================
# INGEST ONE PDF
# ============================================================

def ingest_pdf(
    path: Path,
):

    text = extract_pdf_text(path)

    if not text:
        print(
            f"Skipped {path.name}: no text"
        )

        return 0

    chunks = chunk_text(text)

    if not chunks:
        print(
            f"Skipped {path.name}: no chunks"
        )

        return 0

    # Remove old chunks belonging to this file
    try:
        old = col.get(
            where={
                "file": path.name,
            },
        )

        old_ids = old.get(
            "ids",
            [],
        )

        if old_ids:
            col.delete(
                ids=old_ids
            )

    except Exception:
        pass

    ids = []
    documents = []
    metadatas = []

    for i, chunk in enumerate(chunks):

        ids.append(
            make_document_id(
                path.name,
                i,
                chunk,
            )
        )

        documents.append(chunk)

        metadatas.append(
            {
                "file": path.name,
                "chunk": i,
            }
        )

    col.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas,
    )

    print(
        f"Ingested {path.name}: "
        f"{len(chunks)} chunks"
    )

    return len(chunks)


# ============================================================
# INGEST ALL PDFs
# ============================================================

def ingest_folder():

    total = 0

    pdfs = sorted(
        PDF_DIR.glob("*.pdf")
    )

    for path in pdfs:

        try:
            total += ingest_pdf(path)

        except Exception as exc:

            print(
                f"Error ingesting "
                f"{path.name}: {exc}"
            )

    print(
        f"Total ingested chunks: {total}"
    )

    return total


# ============================================================
# SEARCH / RETRIEVAL
# ============================================================

def search(
    query: str,
    top_k: int = 5,
):
    query = (query or "").strip()

    if not query:
        return {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

    count = col.count()

    if count == 0:
        return {
            "documents": [[]],
            "metadatas": [[]],
            "distances": [[]],
        }

    # Get enough candidates for lexical re-ranking.
    k = min(max(top_k * 3, 10), count)

    result = col.query(
        query_texts=[query],
        n_results=k,
        include=[
            "documents",
            "metadatas",
            "distances",
        ],
    )

    documents = result.get("documents") or [[]]
    metadatas = result.get("metadatas") or [[]]
    distances = result.get("distances") or [[]]

    docs = documents[0] if documents else []
    metas = metadatas[0] if metadatas else []
    dists = distances[0] if distances else []

    # Important query words.
    query_words = set(
        re.findall(r"[a-z]+", query.lower())
    )

    ranked = []

    for i, doc in enumerate(docs):
        text = (doc or "").lower()

        # Count query-word matches.
        matches = sum(
            1
            for word in query_words
            if word in text
        )

        # Chroma cosine distance:
        # lower = better.
        distance = (
            float(dists[i])
            if i < len(dists)
            else 1.0
        )

        # Small lexical boost.
        score = distance - (matches * 0.15)

        ranked.append(
            (
                score,
                i,
            )
        )

    ranked.sort(key=lambda x: x[0])

    selected = ranked[:top_k]

    return {
        "documents": [[
            docs[i]
            for _, i in selected
        ]],
        "metadatas": [[
            metas[i]
            for _, i in selected
        ]],
        "distances": [[
            dists[i]
            if i < len(dists)
            else None
            for _, i in selected
        ]],
    }

# ============================================================
# RELEVANCE
# ============================================================

def is_relevant(
    result,
    threshold: float = 0.65,
):

    distances = (
        result.get("distances")
        or [[]]
    )

    if not distances:
        return False

    first = distances[0]

    if not first:
        return False

    return float(first[0]) <= threshold


# ============================================================
# CONTEXT BUILDER
# ============================================================

def build_context(
    result,
):

    documents = (
        result.get("documents")
        or [[]]
    )

    metadatas = (
        result.get("metadatas")
        or [[]]
    )

    docs = (
        documents[0]
        if documents
        else []
    )

    metas = (
        metadatas[0]
        if metadatas
        else []
    )

    pieces = []

    for i, doc in enumerate(docs):

        meta = (
            metas[i]
            if i < len(metas)
            else {}
        )

        filename = meta.get(
            "file",
            "unknown.pdf",
        )

        chunk = meta.get(
            "chunk",
            i,
        )

        pieces.append(
            f"[Source: {filename}, "
            f"chunk {chunk}]\n"
            f"{doc}"
        )

    return "\n\n".join(pieces)


# ============================================================
# SOURCES
# ============================================================

def extract_sources(
    result,
):

    metas = (
        result.get("metadatas")
        or [[]]
    )

    distances = (
        result.get("distances")
        or [[]]
    )

    metas = (
        metas[0]
        if metas
        else []
    )

    distances = (
        distances[0]
        if distances
        else []
    )

    sources = []

    for i, meta in enumerate(metas):

        sources.append(
            {
                "file": meta.get(
                    "file",
                    "unknown.pdf",
                ),
                "chunk": meta.get(
                    "chunk",
                    i,
                ),
                "distance": (
                    distances[i]
                    if i < len(distances)
                    else None
                ),
            }
        )

    return sources


# ============================================================
# LLM CALL
# ============================================================

def llm_completion(
    messages,
    stream=False,
):

    client_obj, provider, model = (
        get_llm()
    )

    if client_obj is None:
        raise RuntimeError(
            "LLM client is not configured. "
            "Please check your API key and "
            "LLM_PROVIDER settings."
        )

    return client_obj.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.2,
        stream=stream,
    )


# ============================================================
# RESPONSE TEXT HELPER
# ============================================================

def extract_message_text(
    response,
):

    # OpenAI-style object
    try:
        content = (
            response.choices[0]
            .message.content
        )

        if content:
            return content

    except Exception:
        pass

    # Fake test object
    try:
        content = (
            response.choices[0]
            .delta.content
        )

        if content:
            return content

    except Exception:
        pass

    return ""


# ============================================================
# STREAM HELPER
# ============================================================

def stream_llm(
    messages,
):

    response = llm_completion(
        messages,
        stream=True,
    )

    for event in response:

        text = ""

        try:
            text = (
                event.choices[0]
                .delta.content
                or ""
            )

        except Exception:
            pass

        if not text:

            try:
                text = (
                    event.choices[0]
                    .message.content
                    or ""
                )

            except Exception:
                pass

        if text:
            yield text


# ============================================================
# MODELS
# ============================================================

class AskRequest(BaseModel):

    question: str

    history: list[dict[str, Any]] = Field(
        default_factory=list
    )

    lang: str = "en"


class StudyRequest(BaseModel):

    file: str

    mode: str = "summary"

    lang: str = "en"


class QuizRequest(BaseModel):

    n: int = 5


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return {
        "ok": True,
        "service": "AI Study Assistant",
        "version": "1.0.0",
    }


# ============================================================
# DOCS
# ============================================================

@app.get("/api/docs")
def api_docs(
    user=verify_auth,
):

    try:

        data = col.get(
            include=["metadatas"]
        )

        metas = data.get(
            "metadatas",
            [],
        )

        files = sorted(
            {
                m.get("file")
                for m in metas
                if m and m.get("file")
            }
        )

        return {
            "files": files,
            "chunks": len(metas),
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )


# ============================================================
# ASK
# ============================================================

@app.post("/api/ask")
def api_ask(
    request: AskRequest,
    user=verify_auth,
):

    question = (
        request.question or ""
    ).strip()

    if not question:

        raise HTTPException(
            status_code=400,
            detail="Question is required.",
        )

    result = search(
        question,
        top_k=5,
    )

    if not is_relevant(result):

        metadata = {
            "sources": [],
            "chunks": [],
        }

        body = (
            json.dumps(metadata)
            + "\n"
            + "I could not find relevant "
              "information in your study "
              "notes for this question."
        )

        return StreamingResponse(
            iter([body]),
            media_type="text/plain",
        )

    context = build_context(result)

    sources = extract_sources(result)

    metadata = {
        "sources": sources,
        "chunks": (
            result.get(
                "documents",
                [[]],
            )[0]
            if result.get("documents")
            else []
        ),
    }

    history_text = ""

    for item in request.history[-6:]:

        role = item.get(
            "role",
            "",
        )

        content = item.get(
            "content",
            "",
        )

        if content:
            history_text += (
                f"\n{role}: {content}"
            )

    system_prompt = f"""
You are an AI Study Assistant.

Answer the student's question using
ONLY the provided study material.

If the answer is not supported by
the material, clearly say that the
information is not available in the
uploaded notes.

Be educational, clear and beginner
friendly.

Use simple language.

Study material:

{context}
"""

    user_prompt = f"""
Question:

{question}

Previous conversation:

{history_text}

Answer in language:
{request.lang}
"""

    messages = [
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ]

    def generator():

        yield (
            json.dumps(metadata)
            + "\n"
        )

        try:

            for token in stream_llm(
                messages
            ):
                yield token

        except Exception as exc:

            yield (
                "\n\nError generating "
                f"answer: {exc}"
            )

    return StreamingResponse(
        generator(),
        media_type="text/plain",
    )


# ============================================================
# QUIZ
# ============================================================

@app.post("/api/quiz")
def api_quiz(
    request: QuizRequest,
    user=verify_auth,
):

    n = max(
        1,
        min(
            int(request.n),
            20,
        ),
    )

    count = col.count()

    if count == 0:

        raise HTTPException(
            status_code=400,
            detail="No study documents found.",
        )

    result = col.get(
        limit=min(
            count,
            20,
        ),
    )

    docs = result.get(
        "documents",
        [],
    )

    context = "\n\n".join(
        docs
    )

    system_prompt = f"""
Create {n} multiple-choice quiz
questions from the study notes below.

Return ONLY valid JSON.

Each question must have:

q
options
answer
why

"options" must contain exactly
4 choices.

"answer" must be the zero-based
index of the correct option.

Study notes:

{context}
"""

    try:

        response = llm_completion(
            [
                {
                    "role": "system",
                    "content": system_prompt,
                }
            ],
            stream=False,
        )

        text = extract_message_text(
            response
        )

        # Remove markdown fences
        text = re.sub(
            r"^```json\s*",
            "",
            text.strip(),
            flags=re.I,
        )

        text = re.sub(
            r"\s*```$",
            "",
            text.strip(),
        )

        questions = json.loads(text)

        if isinstance(
            questions,
            dict,
        ):
            questions = questions.get(
                "questions",
                [],
            )

        return {
            "questions": questions,
            "quiz": questions,
        }

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=f"Quiz generation failed: {exc}",
        )


# ============================================================
# STUDY
# ============================================================

@app.post("/api/study")
def api_study(
    request: StudyRequest,
    user=verify_auth,
):

    filename = (
        request.file or ""
    ).strip()

    if not filename:

        raise HTTPException(
            status_code=400,
            detail="file is required.",
        )

    safe_name = Path(
        filename
    ).name

    path = PDF_DIR / safe_name

    if not path.exists():

        raise HTTPException(
            status_code=404,
            detail=f"File not found: {safe_name}",
        )

    try:

        text = extract_pdf_text(path)

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=str(exc),
        )

    if not text:

        raise HTTPException(
            status_code=400,
            detail="PDF contains no readable text.",
        )

    mode = (
        request.mode or "summary"
    ).lower()

    chunks = chunk_text(text)

    context = "\n\n".join(
        chunks
    )

    if mode == "flashcards":

        system_prompt = f"""
Create useful study flashcards
from the following study notes.

Return ONLY valid JSON.

Format:

[
  {{
    "front": "question",
    "back": "answer"
  }}
]

Study notes:

{context}
"""

    elif mode == "summary":

        system_prompt = f"""
Create a clear beginner-friendly
summary of these study notes.

Include the important concepts,
definitions and examples.

Study notes:

{context}
"""

    else:

        system_prompt = f"""
Help the student study these notes.

Mode:
{mode}

Provide useful, accurate and
beginner-friendly study material.

Study notes:

{context}
"""

    try:

        response = llm_completion(
            [
                {
                    "role": "system",
                    "content": system_prompt,
                }
            ],
            stream=False,
        )

        output = extract_message_text(
            response
        )

    except Exception as exc:

        raise HTTPException(
            status_code=500,
            detail=f"Study generation failed: {exc}",
        )

    if mode == "flashcards":

        try:

            cleaned = re.sub(
                r"^```json\s*",
                "",
                output.strip(),
                flags=re.I,
            )

            cleaned = re.sub(
                r"\s*```$",
                "",
                cleaned,
            )

            cards = json.loads(
                cleaned
            )

            return {
                "file": safe_name,
                "mode": mode,
                "cards": cards,
                "text": output,
            }

        except Exception:

            return {
                "file": safe_name,
                "mode": mode,
                "cards": [],
                "text": output,
            }

    return {
        "file": safe_name,
        "mode": mode,
        "text": output,
    }


# ============================================================
# INSPECT
# ============================================================

def ingest_folder():

    ingested_files = []
    total_chunks = 0

    pdfs = sorted(
        PDF_DIR.glob("*.pdf")
    )

    for path in pdfs:

        try:

            count = ingest_pdf(path)

            if count > 0:

                ingested_files.append(
                    path.name
                )

                total_chunks += count

        except Exception as exc:

            print(
                f"Error ingesting "
                f"{path.name}: {exc}"
            )

    print(
        f"Total ingested chunks: "
        f"{total_chunks}"
    )

    return ingested_files

# ============================================================
# EVALUATION
# ============================================================

EVAL_QUESTIONS = [
    (
        "What is Python?",
        "ch1_intro_python.pdf",
    ),
    (
        "What are variables?",
        "ch2_variables_datatypes.pdf",
    ),
    (
        "What are data types in Python?",
        "ch2_variables_datatypes.pdf",
    ),
    (
        "What is an if statement?",
        "ch3_conditionals.pdf",
    ),
    (
        "What are conditional statements?",
        "ch3_conditionals.pdf",
    ),
    (
        "What is a for loop?",
        "ch4_loops.pdf",
    ),
    (
        "What is a while loop?",
        "ch4_loops.pdf",
    ),
    (
        "What are loops used for?",
        "ch4_loops.pdf",
    ),
    (
        "What is a Python function?",
        "ch5_functions.pdf",
    ),
    (
        "Why do we use functions?",
        "ch5_functions.pdf",
    ),
]


def run_eval():

    rows = []

    hit1 = 0
    hit5 = 0
    reciprocal_sum = 0.0

    for question, expected_file in EVAL_QUESTIONS:

        result = search(
            question,
            top_k=5,
        )

        sources = extract_sources(
            result
        )

        ranked_files = [
            s["file"]
            for s in sources
        ]

        rank = None

        for i, filename in enumerate(
            ranked_files,
            start=1,
        ):

            if filename == expected_file:

                rank = i
                break

        if rank == 1:
            hit1 += 1

        if rank is not None and rank <= 5:
            hit5 += 1

        if rank is not None:
            reciprocal_sum += 1.0 / rank

        rows.append(
            {
                "question": question,
                "expected": expected_file,
                "rank": rank,
                "top5": ranked_files,
            }
        )

    total = len(
        EVAL_QUESTIONS
    )

    return {
        "hit1": hit1 / total if total else 0,
        "hit5": hit5 / total if total else 0,
        "mrr": reciprocal_sum / total if total else 0,
        "rows": rows,
    }


@app.get("/api/eval")
def api_eval(
    user=verify_auth,
):

    return run_eval()

# ============================================================
# RAG INSPECTOR
# ============================================================

@app.get("/api/inspect")
def api_inspect(user=verify_auth):
    count = int(col.count())

    samples = []
    per_file = {}
    dimension = 0

    if count > 0:
        data = col.get(
            include=["documents", "metadatas", "embeddings"],
            limit=min(count, 3),
        )

        docs = data.get("documents")
        if docs is None:
            docs = []

        metas = data.get("metadatas")
        if metas is None:
            metas = []

        embeddings = data.get("embeddings")
        if embeddings is None:
            embeddings = []

        # Convert embeddings safely to normal Python lists
        safe_embeddings = []

        for emb in embeddings:
            if emb is None:
                safe_embeddings.append([])
            elif hasattr(emb, "tolist"):
                safe_embeddings.append(emb.tolist())
            else:
                safe_embeddings.append(list(emb))

        # Build 3 sample chunks
        for i, doc in enumerate(docs):
            meta = metas[i] if i < len(metas) and metas[i] else {}

            if i < len(safe_embeddings):
                embedding = safe_embeddings[i]
            else:
                embedding = []

            if embedding:
                dimension = len(embedding)

            samples.append({
                "id": f"{str(meta.get('file', 'unknown'))}:{int(meta.get('chunk', i))}",
                "file": str(meta.get("file", "unknown.pdf")),
                "chunk": int(meta.get("chunk", i)),
                "text": str(doc or "")[:300],
                "vec": embedding[:8],
            })

        # Count chunks per PDF
        all_data = col.get(
            include=["metadatas"]
        )

        all_meta = all_data.get("metadatas")

        if all_meta is None:
            all_meta = []

        for meta in all_meta:
            if not meta:
                continue

            filename = str(
                meta.get("file", "unknown.pdf")
            )

            per_file[filename] = (
                per_file.get(filename, 0) + 1
            )

    return {
        "chunks": count,
        "dim": int(dimension),
        "chunk_size": 500,
        "overlap": 80,
        "model": str(LLM_MODEL),
        "store": "ChromaDB",
        "samples": samples,
        "per_file": per_file,
    }

# ============================================================
# UPLOAD
# ============================================================

@app.post("/api/upload")
async def api_upload(
    files: list[UploadFile] = File(...),
    user=verify_auth,
):

    uploaded = []

    for upload in files:

        filename = (
            upload.filename
            or ""
        ).strip()

        if not filename.lower().endswith(
            ".pdf"
        ):

            raise HTTPException(
                status_code=400,
                detail="Only PDF files are allowed.",
            )

        safe_name = Path(
            filename
        ).name

        destination = (
            PDF_DIR / safe_name
        )

        content = await upload.read()

        with open(
            destination,
            "wb",
        ) as f:
            f.write(content)

        try:

            count = ingest_pdf(
                destination
            )

        except Exception as exc:

            raise HTTPException(
                status_code=500,
                detail=(
                    f"Could not ingest "
                    f"{safe_name}: {exc}"
                ),
            )

        uploaded.append(
            {
                "file": safe_name,
                "chunks": count,
            }
        )

    return {
        "ok": True,
        "files": uploaded,
    }


# ============================================================
# FRONTEND
# ============================================================

@app.get("/")
def frontend_index():

    index = FRONT / "index.html"

    if not index.exists():

        return JSONResponse(
            {
                "ok": True,
                "service": "AI Study Assistant",
                "message": (
                    "Frontend index.html "
                    "was not found."
                ),
            }
        )

    return FileResponse(
        index
    )


@app.get("/app.js")
def frontend_app():

    path = FRONT / "app.js"

    if not path.exists():

        raise HTTPException(
            status_code=404,
            detail="app.js not found.",
        )

    return FileResponse(
        path,
        media_type="application/javascript",
    )


@app.get("/style.css")
def frontend_css():

    path = FRONT / "style.css"

    if not path.exists():

        raise HTTPException(
            status_code=404,
            detail="style.css not found.",
        )

    return FileResponse(
        path,
        media_type="text/css",
    )


@app.get("/firebase-config.js")
def frontend_firebase_config():

    path = FRONT / "firebase-config.js"

    if not path.exists():

        raise HTTPException(
            status_code=404,
            detail="firebase-config.js not found.",
        )

    return FileResponse(
        path,
        media_type="application/javascript",
    )


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup_event():

    print("=" * 60)
    print("AI Study Assistant starting...")
    print("PDF DIR:", PDF_DIR)
    print("CHROMA DIR:", CHROMA_DIR)
    print("COLLECTION:", COLLECTION_NAME)
    print("LLM PROVIDER:", LLM_PROVIDER)
    print("LLM MODEL:", LLM_MODEL)
    print("=" * 60)

    try:

        count = col.count()

        if count == 0:

            print(
                "Chroma collection is empty."
            )

            ingest_folder()

        else:

            print(
                f"Existing Chroma chunks: {count}"
            )

    except Exception as exc:

        print(
            "Startup ingestion warning:",
            exc,
        )