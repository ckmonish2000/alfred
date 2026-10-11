from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://alfred:alfred@localhost:5432/alfred"

    # LM Studio (OpenAI-compatible) server
    llm_base_url: str = "http://localhost:1234/v1"
    llm_model: str = "qwen2.5-coder-7b-instruct-mlx"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 1024
    embedding_model: str = "text-embedding-nomic-embed-text-v1.5"
    embedding_dim: int = 768
    embedding_batch_size: int = 32

    # faster-whisper
    whisper_model: str = "small"
    whisper_device: str = "cpu"
    whisper_compute_type: str = "int8"

    transcript_languages: list[str] = ["en"]
    chunk_max_chars: int = 1500
    chunk_overlap_chars: int = 200

    # RAG chat
    chat_top_k: int = 5
    chat_history_messages: int = 6

    tmp_dir: Path = Path("tmp/audio")


settings = Settings()
