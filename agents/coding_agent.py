import json
import structlog
from langchain_core.messages import SystemMessage, HumanMessage

from config import create_chat_llm
from services import GitService

logger = structlog.get_logger()

SYSTEM_PROMPT = """Sen bir otonom yazılım geliştirme ajanısın.
Verilen gereksinimlere ve kod bağlamına göre değişiklikleri uyguluyorsun.

Kurallar:
1. Mevcut kod stiline ve konvansiyonlara uy.
2. Güvenlik açıkları oluşturma (SQL injection, XSS, vs.).
3. SOLID prensiplerine dikkat et.
4. Gereksiz kod ekleme, minimal değişiklik yap.
5. Değişikliklerin test edilebilir olmasına dikkat et.

Çıktını aşağıdaki JSON formatında ver:
```json
{
  "changes": [
    {
      "file_path": "path/to/file.py",
      "new_content": "dosyanın tam yeni içeriği",
      "change_description": "Bu dosyada ne değişti ve neden"
    }
  ],
  "commit_message": "feat: kısa açıklama"
}
```

SADECE JSON döndür, başka bir şey yazma.
"""


class CodingAgent:
    def __init__(self):
        self._llm = create_chat_llm(temperature=0.1)
        self._git_service = GitService()

    def generate_changes(self, analysis: str, search_results: str, work_item_title: str) -> dict:
        logger.info("generating_code_changes", title=work_item_title)

        # Mevcut dosya içeriklerini al
        existing_files = self._get_relevant_file_contents(search_results)

        prompt = f"""İş Maddesi: {work_item_title}

Gereksinim Analizi:
{analysis}

Arama Sonuçları ve Etkilenen Dosyalar:
{search_results}

Mevcut Dosya İçerikleri:
{existing_files}

Yukarıdaki bilgilere göre gerekli kod değişikliklerini yap.
"""

        response = self._llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])

        result = self._parse_response(response.content)
        logger.info("code_changes_generated", num_changes=len(result.get("changes", [])))
        return result

    def _get_relevant_file_contents(self, search_results: str) -> str:
        parts = []
        # Dosya yollarını search_results'tan çıkar
        for line in search_results.split("\n"):
            line = line.strip()
            if line.startswith("Dosya:") or line.startswith("**Dosya**:"):
                file_path = line.split(":", 1)[1].strip().strip("`")
                content = self._git_service.get_file_content(file_path)
                if content:
                    parts.append(f"--- {file_path} ---\n{content}\n")
        return "\n".join(parts) if parts else "Mevcut dosya içeriği bulunamadı."

    def _parse_response(self, content: str) -> dict:
        # Extract JSON from markdown code blocks if present
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        try:
            return json.loads(content.strip())
        except json.JSONDecodeError:
            logger.error("failed_to_parse_coding_response", content=content[:200])
            return {"changes": [], "commit_message": "chore: automated changes"}
