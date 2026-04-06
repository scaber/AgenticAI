import difflib
import structlog
from langchain_core.messages import SystemMessage, HumanMessage

from config import create_chat_llm
from services import GitService
from models import ReviewResult

logger = structlog.get_logger()

SYSTEM_PROMPT = """Sen kıdemli bir kod inceleme ajanısın.
Yapılan kod değişikliklerini aşağıdaki kriterlere göre incele:

1. **Doğruluk**: Değişiklikler gereksinimleri karşılıyor mu?
2. **Güvenlik**: OWASP Top 10'a uygun mu? SQL injection, XSS, CSRF riskleri var mı?
3. **Performans**: Gereksiz döngü, N+1 sorgusu gibi sorunlar var mı?
4. **Kod Kalitesi**: SOLID, DRY, KISS prensiplerine uygun mu?
5. **Test Edilebilirlik**: Değişiklikler test edilebilir mi?

Çıktını aşağıdaki formatta ver:
- **Onay**: EVET veya HAYIR
- **Sorunlar**: (varsa) madde madde
- **Öneriler**: (varsa) madde madde
- **Özet**: Genel değerlendirme
"""


class ReviewAgent:
    def __init__(self):
        self._llm = create_chat_llm(temperature=0)
        self._git_service = GitService()

    def review(self, analysis: str, changes: list[dict]) -> ReviewResult:
        logger.info("reviewing_changes", num_changes=len(changes))

        changes_text = self._format_changes(changes)

        response = self._llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"""Gereksinim Analizi:
{analysis}

Yapılan Değişiklikler:
{changes_text}

Bu değişiklikleri incele.
"""),
        ])

        result = self._parse_review(response.content)
        logger.info("review_complete", approved=result.approved, num_issues=len(result.issues))
        return result

    def _format_changes(self, changes: list[dict]) -> str:
        """Değişiklikleri diff formatında gösterir.
        ReviewAgent'a dosyanın tamamı yerine sadece değişen satırları gönderir."""
        parts = []
        for change in changes:
            file_path = change.get("file_path", "unknown")
            parts.append(f"--- {file_path} ---")
            parts.append(f"Açıklama: {change.get('change_description', '')}")

            new_content = change.get("new_content", "")
            operation = change.get("operation", "modify")

            if operation == "create":
                # Yeni dosya — tamamını göster (kısıtlı)
                parts.append(f"[YENİ DOSYA]\n{new_content[:3000]}")
            else:
                # Mevcut dosya — diff göster
                original = self._git_service.get_file_content(file_path)
                if original:
                    diff = self._generate_diff(original, new_content, file_path)
                    parts.append(f"Değişiklikler (diff):\n{diff[:3000]}")
                else:
                    parts.append(f"Yeni İçerik:\n{new_content[:2000]}")
            parts.append("")
        return "\n".join(parts)

    def _generate_diff(self, original: str, new_content: str, file_path: str) -> str:
        """İki içerik arasındaki unified diff'i döndürür."""
        original_lines = original.splitlines(keepends=True)
        new_lines = new_content.splitlines(keepends=True)
        diff = difflib.unified_diff(
            original_lines,
            new_lines,
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            n=3,
        )
        return "".join(diff)

    def _parse_review(self, content: str) -> ReviewResult:
        approved = "EVET" in content.upper().split("ONAY")[1][:20] if "ONAY" in content.upper() else False

        issues = []
        suggestions = []

        in_issues = False
        in_suggestions = False

        for line in content.split("\n"):
            line = line.strip()
            if "sorun" in line.lower():
                in_issues = True
                in_suggestions = False
                continue
            elif "öneri" in line.lower():
                in_suggestions = True
                in_issues = False
                continue
            elif "özet" in line.lower():
                in_issues = False
                in_suggestions = False
                continue

            if line.startswith("-") or line.startswith("*"):
                item = line.lstrip("-* ").strip()
                if item:
                    if in_issues:
                        issues.append(item)
                    elif in_suggestions:
                        suggestions.append(item)

        return ReviewResult(
            approved=approved,
            issues=issues,
            suggestions=suggestions,
            summary=content,
        )
