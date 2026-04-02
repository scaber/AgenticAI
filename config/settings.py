from pydantic_settings import BaseSettings
from functools import lru_cache
from typing import Literal


class Settings(BaseSettings):
    # Azure DevOps
    azure_devops_pat: str
    azure_devops_org_url: str
    azure_devops_project: str

    # LLM Provider: "ollama" or "azure_openai"
    llm_provider: Literal["ollama", "azure_openai"] = "azure_openai"

    # Ollama (optional)
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1"
    ollama_embedding_model: str = "nomic-embed-text"

    # Azure OpenAI (optional)
    azure_openai_endpoint: str = ""
    azure_openai_api_key: str = ""
    azure_openai_deployment: str = "gpt-5-nano"
    azure_openai_api_version: str = "2024-12-01-preview"
    azure_openai_embedding_deployment: str = "text-embedding-ada-002"

    # Git
    git_repo_path: str
    git_remote_url: str

    # App
    webhook_secret: str = ""
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
