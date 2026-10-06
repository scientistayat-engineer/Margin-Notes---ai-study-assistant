"""Offline tests: fake embeddings + fake LLM, so no API key or model download is needed. Run from the backend folder: python tests/test_api.py"""
import os, sys, re, json, hashlib, tempfile
os.environ["CHROMA_DIR"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import main
from chromadb import EmbeddingFunction
from fastapi.testclient import TestClient

class FakeEF(EmbeddingFunction):
    def __init__(self): pass
    def __call__(self, input):
        out = []
        for t in input:
            v = [0.0] * 256
            for w in re.findall(r"[a-z]+", t.lower()): v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 256] += 1
            n = sum(x * x for x in v) ** .5 or 1; out.append([x / n for x in v])
        return out
    @staticmethod
    def name(): return "fake"
    def get_config(self): return {}
    @staticmethod
    def build_from_config(c): return FakeEF()

class Ev:
    def __init__(s, t): s.choices = [type("C", (), {"delta": type("D", (), {"content": t})(), "message": type("M", (), {"content": t})()})()]
class FakeLLM:
    class chat:
        class completions:
            @staticmethod
            def create(**kw):
                sysm = kw["messages"][0]["content"]
                if kw.get("stream"): return iter([Ev("Hello "), Ev("world")])
                if "flashcards" in sysm: return Ev('[{"front":"f","back":"b"}]')
                if "options" in sysm: return Ev("```json\n" + json.dumps([{"q": "q", "options": list("abcd"), "answer": 1, "why": "w"}]) + "\n```")
                return Ev("summary text")
main.col = main.client.get_or_create_collection("test_notes", embedding_function=FakeEF(), metadata={"hnsw:space": "cosine"})
main.llm_client = lambda: (FakeLLM(), "fake", "grok")
c = TestClient(main.app); ok = lambda name, cond: print(("PASS " if cond else "FAIL ") + name) or (cond or sys.exit(1))

ok("ingest 5 sample PDFs", len(main.ingest_folder()) == 5)
d = c.get("/api/docs").json(); ok("docs lists 5 files + chunks", len(d["files"]) == 5 and d["chunks"] > 5)
r = c.post("/api/ask", json={"question": "What is a for loop?", "history": [], "lang": "en"}); head, _, body = r.text.partition("\n"); meta = json.loads(head)
ok("ask streams meta then tokens", body == "Hello world" and meta["chunks"]); ok("top source is loops chapter", meta["sources"][0]["file"] == "ch4_loops.pdf")
r = c.post("/api/ask", json={"question": "quantum chromodynamics banana", "history": []}); ok("guard refuses off-topic", "could not find" in r.text and json.loads(r.text.split("\n")[0])["sources"] == [])
ok("follow-up with history works", c.post("/api/ask", json={"question": "give an example", "history": [{"role": "user", "content": "What is a for loop?"}, {"role": "assistant", "content": "x"}]}).status_code == 200)
ok("quiz parses fenced JSON", c.post("/api/quiz", json={"n": 5}).json()["questions"][0]["answer"] == 1)
ok("study summary", c.post("/api/study", json={"file": "ch2_variables_datatypes.pdf", "mode": "summary"}).json()["text"] == "summary text")
ok("study flashcards", c.post("/api/study", json={"file": "ch2_variables_datatypes.pdf", "mode": "flashcards"}).json()["cards"][0]["front"] == "f")
ok("study unknown file -> 404", c.post("/api/study", json={"file": "nope.pdf"}).status_code == 404)
i = c.get("/api/inspect").json(); ok("inspect dim + samples", i["dim"] == 256 and len(i["samples"]) == 3 and len(i["per_file"]) == 5)
e = c.get("/api/eval").json(); print("eval (fake embeddings):", e["hit1"], e["hit5"], e["mrr"]); ok("eval runs on 10 questions", len(e["rows"]) == 10)
up = open(os.path.join(main.PDF_DIR, "ch4_loops.pdf"), "rb").read()
ok("upload PDF re-indexes", c.post("/api/upload", files=[("files", ("ch4_loops.pdf", up, "application/pdf"))]).status_code == 200)
ok("upload rejects non-PDF", c.post("/api/upload", files=[("files", ("a.txt", b"x", "text/plain"))]).status_code == 400)
ok("frontend served + CORS preflight", c.options("/api/ask", headers={"Origin": "https://margin-notes-e0c49.web.app", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"}).headers.get("access-control-allow-origin") == "https://margin-notes-e0c49.web.app" and all(c.get(p).status_code == 200 for p in ("/", "/style.css", "/app.js")) and "Margin Notes" in c.get("/").text)
print("ALL TESTS PASSED")
