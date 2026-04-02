import os
import structlog
from llama_index.core import (
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
)
from llama_index.core import Settings as LlamaSettings

from config import get_settings, create_llama_llm, create_llama_embedding

logger = structlog.get_logger()

INDEX_PERSIST_DIR = ".index_store"

# Only index actual source code files
CODE_EXTENSIONS = [".cs"]

# Skip generated/build folders
EXCLUDE_DIRS = {"bin", "obj", "Migrations", "node_modules", ".git", "packages", "TestResults"}


class CodeRAGEngine:
    def __init__(self):
        settings = get_settings()

        self._llm = create_llama_llm()
        self._embed_model = create_llama_embedding()

        LlamaSettings.llm = self._llm
        LlamaSettings.embed_model = self._embed_model

        self._repo_path = settings.git_repo_path
        self._index: VectorStoreIndex | None = None

    def build_index(self, force_rebuild: bool = False) -> None:
        persist_path = os.path.join(self._repo_path, INDEX_PERSIST_DIR)

        if not force_rebuild and os.path.exists(persist_path):
            logger.info("loading_existing_index", path=persist_path)
            storage_context = StorageContext.from_defaults(persist_dir=persist_path)
            self._index = load_index_from_storage(storage_context)
            return

        logger.info("building_code_index", repo_path=self._repo_path)

        src_path = os.path.join(self._repo_path, "src")
        index_path = src_path if os.path.isdir(src_path) else self._repo_path
        print(f"   📂 RAG index dizini: {index_path}")

        # Exclude dirs filter
        def should_include(path: str) -> bool:
            parts = path.replace("\\", "/").split("/")
            return not any(d in EXCLUDE_DIRS for d in parts)

        all_files = []
        for root, dirs, files in os.walk(index_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if any(f.endswith(ext) for ext in CODE_EXTENSIONS):
                    all_files.append(os.path.join(root, f))

        print(f"   📄 İndexlenecek dosya sayısı: {len(all_files)}")

        documents = SimpleDirectoryReader(
            input_files=all_files,
            file_metadata=lambda path: {"file_path": os.path.relpath(path, self._repo_path)},
        ).load_data()

        self._index = VectorStoreIndex.from_documents(documents)
        self._index.storage_context.persist(persist_dir=persist_path)
        logger.info("code_index_built", num_documents=len(documents))

    def query(self, question: str, top_k: int = 5) -> list[dict]:
        if self._index is None:
            self.build_index()

        retriever = self._index.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(question)

        results = [
            {
                "file_path": node.metadata.get("file_path", "unknown"),
                "content": node.text,
                "score": node.score,
            }
            for node in nodes
        ]

        logger.info("rag_query_completed", question=question[:100], num_results=len(results))
        return results

    def search_similar_code(self, code_snippet: str, top_k: int = 5) -> list[dict]:
        if self._index is None:
            self.build_index()

        retriever = self._index.as_retriever(similarity_top_k=top_k)
        nodes = retriever.retrieve(code_snippet)

        return [
            {
                "file_path": node.metadata.get("file_path", "unknown"),
                "content": node.text,
                "score": node.score,
            }
            for node in nodes
        ]
