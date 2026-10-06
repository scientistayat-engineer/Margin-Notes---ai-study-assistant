FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV CHROMA_DIR=/app/chroma_db ANONYMIZED_TELEMETRY=False OMP_NUM_THREADS=1
# Build the vector DB at image build time (this also downloads the embedding model)
RUN python -c "import main; print(main.ingest_folder())"
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
