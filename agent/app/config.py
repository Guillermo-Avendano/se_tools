"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Qdrant
    qdrant_host: str = Field(default="qdrant")
    qdrant_port: int = Field(default=6333)
    qdrant_collection: str = Field(default="schema_memory")

    # Ollama
    ollama_base_url: str = Field(default="http://ollama:11434")
    ollama_model: str = Field(default="llama3")
    ollama_embed_model: str = Field(default="nomic-embed-text")
    ollama_num_ctx: int = Field(default=32768)
    ollama_temperature: float = Field(default=0.1)

    # LLM provider: "ollama" or "llama_cpp"
    llm_provider: str = Field(default="ollama")

    # llama.cpp server (OpenAI-compatible, used when llm_provider=llama_cpp)
    llama_cpp_api_key: str = Field(default="")
    llama_cpp_model: str = Field(default="llama-3.1-8b-instruct")
    llama_cpp_base_url: str = Field(default="http://host.docker.internal:8080/v1")
    llama_cpp_temperature: float = Field(default=0.1)

    # Embeddings provider: "ollama" or "llama_cpp"
    embedding_provider: str = Field(default="ollama")

    # llama.cpp embeddings (OpenAI-compatible)
    llama_cpp_embed_model: str = Field(default="nomic-embed-text")
    llama_cpp_embed_base_url: str = Field(default="")
    llama_cpp_embed_api_key: str = Field(default="")

    # Redis (conversation history)
    redis_url: str = Field(default="redis://redis:6379/0")
    redis_chat_ttl: int = Field(default=3600)
    redis_max_turns: int = Field(default=20)

    # ContentEdge
    contentedge_yaml: str = Field(default="/workspace/conf/repository_source.yaml")
    contentedge_target_yaml: str = Field(default="/workspace/conf/repository_target.yaml")
    contentedge_work_dir: str = Field(default="/app/contentedge/files")

    # Archiving policy generation
    policy_sample_lines: int = Field(default=400)

    # Agent workspace (for filesystem & shell skills)
    agent_workspace: str = Field(default="/workspace")

    # App
    agent_name: str = Field(default="SE-Content-Agent")
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    app_base_url: str = Field(default="http://localhost:8000")
    log_level: str = Field(default="INFO")
    allowed_origins: str = Field(default="http://localhost:3000,http://localhost:8000")

    @property
    def origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
