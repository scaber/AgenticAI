import structlog
from langchain_core.messages import SystemMessage, HumanMessage

from config import create_chat_llm
from services import GitService
from context import CodeRAGEngine

logger = structlog.get_logger()

KEYWORD_PROMPT = """Aşağıdaki gereksinim analizini oku ve bu değişiklikle ilgili olabilecek
dosya/sınıf/modül isimlerini tahmin et. Sadece anahtar kelimeleri virgülle ayırarak yaz.

Örnek çıktı: Penalty, Traffic, Fine, League, Score, VAS

Analiz:
{analysis}

Anahtar kelimeler:"""

SEARCH_PROMPT = """Sen bir kod arama ajanısın.
Verilen gereksinimlere ve dosya listesine göre değiştirilmesi gereken dosyaları seç.

Çıktını aşağıdaki formatta ver (her dosya için bir satır):
DOSYA: dosya/yolu/burada.cs | SEBEP: kısa açıklama
"""


class SearchAgent:
    def __init__(self):
        self._llm = create_chat_llm(temperature=0)
        self._git_service = GitService()
        self._rag_engine = CodeRAGEngine()

    def search(self, analysis: str) -> dict:
        logger.info("searching_codebase")

        # 1. RAG ile semantik arama yap (ilk çalıştırmada index oluşturur)
        print("   🔍 RAG ile semantik arama yapılıyor...")
        rag_results = self._rag_engine.query(analysis[:1000], top_k=15)
        print(f"   📄 RAG sonuçları: {len(rag_results)} dosya bulundu")
        for r in rag_results[:5]:
            print(f"      - {r.get('file_path', '?')} (skor: {r.get('score', 0):.3f})")

        # 2. Anahtar kelimelerle ek dosya filtrele
        keyword_response = self._llm.invoke([
            HumanMessage(content=KEYWORD_PROMPT.format(analysis=analysis[:1000])),
        ])
        keywords = [k.strip().lower() for k in keyword_response.content.split(",") if k.strip()]
        print(f"   🔑 Anahtar kelimeler: {keywords}")

        all_files = self._git_service.list_files(extensions=[".cs", ".py", ".js", ".ts"])
        keyword_files = []
        for f in all_files:
            f_lower = f.lower()
            if any(kw in f_lower for kw in keywords):
                keyword_files.append(f)

        # 3. RAG + keyword sonuçlarını birleştir
        rag_paths = {r["file_path"] for r in rag_results}
        combined = list(rag_paths) + [f for f in keyword_files if f not in rag_paths]
        combined = combined[:50]
        print(f"   📁 Toplam birleşik dosya: {len(combined)}")

        # 4. Seçilen dosyaların içeriklerini al
        search_results = []
        for file_path in combined[:20]:
            content = self._git_service.get_file_content(file_path)
            if content:
                rag_match = next((r for r in rag_results if r["file_path"] == file_path), None)
                search_results.append({
                    "file_path": file_path,
                    "content": content[:2000],
                    "score": rag_match["score"] if rag_match else 0.5,
                })

        # 5. LLM ile final değerlendirme
        file_list = "\n".join(combined)
        response = self._llm.invoke([
            SystemMessage(content=SEARCH_PROMPT),
            HumanMessage(content=f"""Gereksinim Analizi:
{analysis[:1500]}

İlgili Dosyalar:
{file_list}

Hangi dosyalar değiştirilmeli?
"""),
        ])
        print(f"   📝 Search Agent yanıtı:\n{response.content[:500]}")

        logger.info("search_complete", num_results=len(search_results))

        return {
            "search_results": search_results,
            "search_analysis": response.content,
        }
