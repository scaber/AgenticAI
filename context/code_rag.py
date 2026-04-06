import os
import json
import hashlib
import structlog
from llama_index.core import (
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
    load_index_from_storage,
    Document,
)
from llama_index.core import Settings as LlamaSettings

from config import get_settings, create_llama_llm, create_llama_embedding

logger = structlog.get_logger()

INDEX_PERSIST_DIR = ".index_store"
HASH_MANIFEST_FILE = ".index_store/file_hashes.json"

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
        hash_path = os.path.join(self._repo_path, HASH_MANIFEST_FILE)

        if force_rebuild:
            self._full_rebuild(persist_path, hash_path)
            return

        if os.path.exists(persist_path) and os.path.exists(hash_path):
            # Incremental indexing: sadece değişen dosyaları güncelle
            self._incremental_update(persist_path, hash_path)
        else:
            self._full_rebuild(persist_path, hash_path)

    def _collect_source_files(self) -> list[str]:
        src_path = os.path.join(self._repo_path, "src")
        index_path = src_path if os.path.isdir(src_path) else self._repo_path

        all_files = []
        for root, dirs, files in os.walk(index_path):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if any(f.endswith(ext) for ext in CODE_EXTENSIONS):
                    all_files.append(os.path.join(root, f))
        return all_files

    @staticmethod
    def _file_hash(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def _compute_hashes(self, files: list[str]) -> dict[str, str]:
        return {f: self._file_hash(f) for f in files}

    def _load_hash_manifest(self, hash_path: str) -> dict[str, str]:
        if not os.path.exists(hash_path):
            return {}
        with open(hash_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _save_hash_manifest(self, hash_path: str, hashes: dict[str, str]) -> None:
        os.makedirs(os.path.dirname(hash_path), exist_ok=True)
        with open(hash_path, "w", encoding="utf-8") as f:
            json.dump(hashes, f, indent=2)

    def _full_rebuild(self, persist_path: str, hash_path: str) -> None:
        logger.info("building_code_index", repo_path=self._repo_path)

        all_files = self._collect_source_files()
        print(f"   📂 RAG index dizini: {self._repo_path}")
        print(f"   📄 İndexlenecek dosya sayısı: {len(all_files)}")

        documents = SimpleDirectoryReader(
            input_files=all_files,
            file_metadata=lambda path: {"file_path": os.path.relpath(path, self._repo_path)},
        ).load_data()

        self._index = VectorStoreIndex.from_documents(documents)
        self._index.storage_context.persist(persist_dir=persist_path)

        # Hash manifest kaydet
        hashes = self._compute_hashes(all_files)
        self._save_hash_manifest(hash_path, hashes)

        logger.info("code_index_built", num_documents=len(documents))

    def _incremental_update(self, persist_path: str, hash_path: str) -> None:
        logger.info("incremental_index_update_start")

        # Mevcut index'i yükle
        storage_context = StorageContext.from_defaults(persist_dir=persist_path)
        self._index = load_index_from_storage(storage_context)

        old_hashes = self._load_hash_manifest(hash_path)
        current_files = self._collect_source_files()
        new_hashes = self._compute_hashes(current_files)

        current_set = set(current_files)
        old_set = set(old_hashes.keys())

        added = current_set - old_set
        removed = old_set - current_set
        modified = {f for f in current_set & old_set if new_hashes[f] != old_hashes[f]}

        changed_count = len(added) + len(removed) + len(modified)

        if changed_count == 0:
            logger.info("index_up_to_date", message="Değişiklik yok, index güncel.")
            print("   ✅ RAG index güncel, değişiklik yok.")
            return

        print(f"   🔄 Incremental update: +{len(added)} eklenen, ~{len(modified)} değişen, -{len(removed)} silinen")

        # Silinen/değiştirilen dosyaların eski doc_id'lerini kaldır
        files_to_remove = removed | modified
        if files_to_remove:
            rel_paths_to_remove = {os.path.relpath(f, self._repo_path) for f in files_to_remove}
            doc_ids_to_delete = []
            for doc_id, doc_info in self._index.ref_doc_info.items():
                doc_file = doc_info.metadata.get("file_path", "")
                if doc_file in rel_paths_to_remove:
                    doc_ids_to_delete.append(doc_id)

            for doc_id in doc_ids_to_delete:
                self._index.delete_ref_doc(doc_id)

            logger.info("docs_removed_from_index", count=len(doc_ids_to_delete))

        # Eklenen/değiştirilen dosyaları indeksle
        files_to_add = list(added | modified)
        if files_to_add:
            new_docs = SimpleDirectoryReader(
                input_files=files_to_add,
                file_metadata=lambda path: {"file_path": os.path.relpath(path, self._repo_path)},
            ).load_data()

            for doc in new_docs:
                self._index.insert(doc)

            logger.info("docs_added_to_index", count=len(new_docs))

        # Persist
        self._index.storage_context.persist(persist_dir=persist_path)
        self._save_hash_manifest(hash_path, new_hashes)

        logger.info("incremental_index_update_complete", changes=changed_count)

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
