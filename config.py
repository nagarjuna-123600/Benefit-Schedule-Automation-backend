
import os
from dotenv import load_dotenv

load_dotenv()

# PostgreSQL database
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:YOUR_PASSWORD@localhost:5432/benefit_automation",
)

# Ollama configuration
OLLAMA_BASE_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://localhost:11434"
).rstrip("/")

OLLAMA_MODEL = os.getenv(
    "OLLAMA_MODEL",
    "llama3.2:latest"
)

OLLAMA_EMBED_MODEL = os.getenv(
    "OLLAMA_EMBED_MODEL",
    "nomic-embed-text:latest"
)

# Maximum wait time for each Ollama request
OLLAMA_TIMEOUT_SECONDS = int(
    os.getenv("OLLAMA_TIMEOUT_SECONDS", "600")
)

# File upload limit
MAX_UPLOAD_MB = int(
    os.getenv("MAX_UPLOAD_MB", "25")
)

# Maximum document text processed
MAX_TEXT_CHARS = int(
    os.getenv("MAX_TEXT_CHARS", "60000")
)

# Text chunking configuration
CHUNK_SIZE = int(
    os.getenv("CHUNK_SIZE", "6000")
)

CHUNK_OVERLAP = int(
    os.getenv("CHUNK_OVERLAP", "300")
)
