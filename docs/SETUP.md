# Setup guide: run locally, GitHub, LinkedIn, portal
Commands are for Windows PowerShell. This project runs on your own computer; it is not deployed online. Run commands from the repository root unless a `cd` says otherwise.

## 0. Install once
Python 3.11+, Git, and (only for step 3) Node.js LTS with `npm install -g firebase-tools`.

## 1. Test locally
```
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```
Open `backend\.env` and set `GROQ_API_KEY=...` (for xAI Grok instead: `LLM_PROVIDER=grok` and `XAI_API_KEY=...`). Leave `FIREBASE_PROJECT_ID` empty for local use.
```
python tests\test_api.py                                # expect: ALL TESTS PASSED
python -c "import main; print(main.ingest_folder())"    # first run downloads the embedding model
python evaluate.py                                      # note top-1 / top-5 / MRR for your report
uvicorn main:app --reload                               # open http://localhost:8000/?dev=1 (skips login, local only)
```
The default model is Groq `openai/gpt-oss-20b`. If Groq says the model does not exist, set `LLM_MODEL=` in `.env` to a Production model listed on the Groq models page.
To use your own PDFs, put 5 PDFs in `backend\data\pdfs` and edit `backend\data\eval_set.json` to match your file names.

## 2. Firebase project (browser)
1. https://console.firebase.google.com > Add project.
2. Build > Authentication > Get started > enable **Email/Password** and **Google**.
3. Build > Firestore Database > Create database (production mode).
4. Project settings > Your apps > Web app (`</>`) > copy the config into `frontend\firebase-config.js`.
5. Stay on the free **Spark** plan: no billing account is needed.

## 3. Let chat history be saved (free, one command)
Chat history is stored in Firestore, and it needs the security rules from this repository. From the repository root:
```
firebase login
firebase deploy --only firestore:rules
```
Without this step the app still works, but chat history is not saved between sessions.

## 4. Push to GitHub
Create an empty repository named `ai-study-assistant` on https://github.com/scientistayat-engineer, then:
```
git init
git add .
git status                         # make sure .env and venv are NOT listed
git commit -m "Margin Notes: AI Study Assistant (RAG) with FastAPI, ChromaDB, Groq and Firebase"
git branch -M main
git remote add origin https://github.com/scientistayat-engineer/ai-study-assistant.git
git push -u origin main
```
API keys live only in `backend\.env`; the Firebase web config is not a secret.

## 5. Real screenshots for the portal
Run the app (`uvicorn main:app --reload` in `backend`, then open http://localhost:8000) and save these in `images\screenshots\`:
1. PDF upload (the shelf showing 5 PDFs)
2. Embeddings creation ("Indexed 5 PDFs into N chunks")
3. Saved vector DB (RAG Inspector)
4. Three or more answers with source chips
5. The browser address bar showing localhost:8000

Close the `.env` file and any API-key pages before taking screenshots.

## 6. Finish the documents
Open `docs\Margin_Notes_Report.docx`, add your screenshots to the appendix, save, then **File > Save as PDF** to refresh `docs\Margin_Notes_Report.pdf`. The evaluation results (100% top-1, 100% top-5, MRR 1.0) are already filled in.

## 7. LinkedIn
Copy `docs\LINKEDIN_POST.md`, attach 2-3 screenshots (login, answer with sources, RAG Inspector) or a short screen recording, and post.

## 8. Portal submission
Submit the project folder (zip), the GitHub link and the screenshots from step 5. Attach the PPT and report if your teacher asks. The assignment lists a deployed application link; because this project runs locally, tell your teacher it was demonstrated locally, and consider adding a short screen recording of the app running.

## Troubleshooting
| Problem | Fix |
|---|---|
| Login button does nothing or auth errors | Firebase config not pasted into `frontend\firebase-config.js` |
| Google login popup blocked | Open `http://localhost:8000` (not 127.0.0.1) and allow popups |
| 401 "Please log in again" | Leave `FIREBASE_PROJECT_ID` empty in `backend\.env` when running locally |
| "model not found" from Groq | Set `LLM_MODEL=` in `.env` to a Production model listed on the Groq models page |
| Quiz or flashcards "failed" | The model returned bad JSON; press the button again |
| Chat history is not saved | Run step 3 (`firebase deploy --only firestore:rules`) |

## Optional: host it online later
This is not needed for the submission. A rough outline: push the repo to GitHub, create a Render Web Service (free tier, Docker, **Root Directory** `backend`) with the variables `LLM_PROVIDER=groq`, `GROQ_API_KEY` and `FIREBASE_PROJECT_ID`, put the service URL in `API_BASE_URL` in `frontend\firebase-config.js`, and run `firebase deploy --only firestore:rules,hosting`. Free Render instances have 512 MB RAM and sleep when idle, which may not be enough for the local embedding model.
