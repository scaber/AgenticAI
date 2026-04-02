"""LLM factory — creates the right LLM/embedding based on llm_provider setting."""

from config.settings import get_settings


def create_chat_llm(temperature: float = 0):
    """Create a LangChain chat LLM (ChatOllama or AzureChatOpenAI)."""
    settings = get_settings()

    if settings.llm_provider == "azure_openai":
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            azure_deployment=settings.azure_openai_deployment,
            api_version=settings.azure_openai_api_version,
            temperature=temperature,
            timeout=120,
        )
    else:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            temperature=temperature,
            timeout=120,
        )


def create_llama_llm():
    """Create a LlamaIndex LLM (Ollama or AzureOpenAI)."""
    settings = get_settings()

    if settings.llm_provider == "azure_openai":
        from llama_index.llms.azure_openai import AzureOpenAI

        return AzureOpenAI(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            azure_deployment=settings.azure_openai_deployment,
            api_version=settings.azure_openai_api_version,
        )
    else:
        from llama_index.llms.ollama import Ollama

        return Ollama(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            request_timeout=120.0,
        )


def create_llama_embedding():
    """Create a LlamaIndex embedding model."""
    settings = get_settings()

    if settings.llm_provider == "azure_openai":
        from llama_index.embeddings.azure_openai import AzureOpenAIEmbedding

        return AzureOpenAIEmbedding(
            azure_endpoint=settings.azure_openai_endpoint,
            api_key=settings.azure_openai_api_key,
            azure_deployment=settings.azure_openai_embedding_deployment,
            api_version=settings.azure_openai_api_version,
        )
    else:
        from llama_index.embeddings.ollama import OllamaEmbedding

        return OllamaEmbedding(
            base_url=settings.ollama_base_url,
            model_name=settings.ollama_embedding_model,
            request_timeout=120.0,
        )
