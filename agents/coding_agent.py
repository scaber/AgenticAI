import json
import structlog
from langchain_core.messages import SystemMessage, HumanMessage

from config import create_chat_llm
from services import GitService

logger = structlog.get_logger()

# Approximate token limit for context (leaving room for system prompt + response)
MAX_CONTEXT_CHARS = 60_000  # ~15k tokens
MAX_FILE_CHARS = 8_000      # per-file limit
MAX_TOTAL_FILES = 15

SYSTEM_PROMPT = """Sen bir otonom yazılım geliştirme ajanısın.
Verilen gereksinimlere ve kod bağlamına göre değişiklikleri uyguluyorsun.

Kurallar:
1. Mevcut kod stiline ve konvansiyonlara uy.
2. Güvenlik açıkları oluşturma (SQL injection, XSS, vs.).
3. SOLID prensiplerine dikkat et.
4. Gereksiz kod ekleme, minimal değişiklik yap.
5. Değişikliklerin test edilebilir olmasına dikkat et.

ÖNEMLİ — Değişiklik Formatı:
- Mevcut dosyalarda SADECE değişen kısımları belirt. Dosyanın tamamını yazma!
- Her değişiklik için "search" (mevcut kod bloğu) ve "replace" (yeni kod bloğu) belirt.
- "search" bloğu dosyada birebir eşleşmeli. Yeterli bağlam satırı ekle (en az 3 satır önce/sonra).
- Yeni dosya oluşturulacaksa operation: "create" kullan ve new_content ver.
- Bir dosyada birden fazla değişiklik varsa, her biri ayrı bir search/replace bloğu olsun.

Çıktını aşağıdaki JSON formatında ver:
```json
{
  "changes": [
    {
      "file_path": "path/to/existing_file.cs",
      "operation": "modify",
      "search_replace_blocks": [
        {
          "search": "değiştirilecek mevcut kod bloğu (birebir eşleşmeli)",
          "replace": "yerine yazılacak yeni kod bloğu"
        }
      ],
      "change_description": "Bu dosyada ne değişti ve neden"
    },
    {
      "file_path": "path/to/new_file.cs",
      "operation": "create",
      "new_content": "yeni dosyanın tam içeriği",
      "change_description": "Bu dosya neden oluşturuldu"
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

        # Mevcut dosya içeriklerini al (token-aware)
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

        # Toplam bağlamı kontrol et
        prompt = self._truncate_to_limit(prompt, MAX_CONTEXT_CHARS)

        response = self._llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])

        result = self._parse_response(response.content)

        # search/replace bloklarını uygulayarak nihai dosya içeriklerini oluştur
        result = self._resolve_changes(result)

        logger.info("code_changes_generated", num_changes=len(result.get("changes", [])))
        return result

    def _get_relevant_file_contents(self, search_results: str) -> str:
        """Dosya içeriklerini token limitine uygun şekilde döndürür.
        Büyük dosyalarda sadece ilgili snippet'ları gönderir."""
        parts = []
        total_chars = 0
        file_count = 0

        for line in search_results.split("\n"):
            line = line.strip()
            if line.startswith("Dosya:") or line.startswith("**Dosya**:") or line.startswith("DOSYA:"):
                if file_count >= MAX_TOTAL_FILES:
                    break

                file_path = line.split(":", 1)[1].strip().strip("`").split("|")[0].strip()
                content = self._git_service.get_file_content(file_path)
                if not content:
                    continue

                # Dosya çok büyükse sadece önemli kısımları al
                truncated = self._smart_truncate_file(content, file_path)
                if total_chars + len(truncated) > MAX_CONTEXT_CHARS:
                    remaining = MAX_CONTEXT_CHARS - total_chars
                    if remaining > 500:
                        truncated = truncated[:remaining] + "\n... [token limiti nedeniyle kesildi]"
                    else:
                        break

                parts.append(f"--- {file_path} ---\n{truncated}\n")
                total_chars += len(truncated)
                file_count += 1

        if not parts:
            return "Mevcut dosya içeriği bulunamadı."

        logger.info("file_context_prepared", file_count=file_count, total_chars=total_chars)
        return "\n".join(parts)

    def _smart_truncate_file(self, content: str, file_path: str) -> str:
        """Dosya büyükse class/method imzalarını ve önemli bloklarını koruyarak kısaltır."""
        if len(content) <= MAX_FILE_CHARS:
            return content

        lines = content.split("\n")
        important_lines = []
        context_window = 3  # Önemli satırdan önce/sonra kaç satır dahil edilsin

        important_indices = set()
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Class, method, function tanımları ve using/import satırları
            if any(stripped.startswith(kw) for kw in [
                "class ", "public ", "private ", "protected ", "internal ",
                "def ", "async ", "namespace ", "using ", "import ", "from ",
                "interface ", "enum ", "struct ", "[",  # attributes/decorators
            ]):
                for j in range(max(0, i - context_window), min(len(lines), i + context_window + 1)):
                    important_indices.add(j)

        if not important_indices:
            # Fallback: dosyanın başı ve sonu
            return content[:MAX_FILE_CHARS // 2] + "\n\n... [orta kısım atlandı] ...\n\n" + content[-(MAX_FILE_CHARS // 2):]

        sorted_indices = sorted(important_indices)
        result_lines = []
        prev_idx = -1
        total_chars = 0

        for idx in sorted_indices:
            if total_chars >= MAX_FILE_CHARS:
                result_lines.append("... [token limiti nedeniyle kesildi]")
                break
            if prev_idx >= 0 and idx > prev_idx + 1:
                result_lines.append(f"    ... [{idx - prev_idx - 1} satır atlandı] ...")
            result_lines.append(lines[idx])
            total_chars += len(lines[idx])
            prev_idx = idx

        return "\n".join(result_lines)

    def _truncate_to_limit(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        logger.warning("prompt_truncated", original_len=len(text), limit=limit)
        return text[:limit] + "\n\n... [token limiti nedeniyle bağlam kesildi]"

    def _resolve_changes(self, result: dict) -> dict:
        """search/replace bloklarını mevcut dosya içeriği üzerinde uygulayarak
        her change için nihai new_content oluşturur. Böylece LLM dosyanın
        tamamını yeniden yazmak zorunda kalmaz, sadece değişen kısımları belirtir."""
        resolved_changes = []

        for change in result.get("changes", []):
            file_path = change.get("file_path", "")
            operation = change.get("operation", "modify")

            if operation == "create":
                # Yeni dosya — zaten new_content var
                resolved_changes.append(change)
                continue

            # modify işlemi — search/replace bloklarını uygula
            blocks = change.get("search_replace_blocks", [])
            if not blocks:
                # Eski format (new_content) ile gelmiş olabilir, olduğu gibi geç
                if change.get("new_content"):
                    resolved_changes.append(change)
                    continue
                logger.warning("no_search_replace_blocks", file=file_path)
                continue

            # Mevcut dosya içeriğini oku
            current_content = self._git_service.get_file_content(file_path)
            if current_content is None:
                # Dosya bulunamadı — belki yeni dosya olarak değerlendirmeli
                logger.warning("file_not_found_for_modify", file=file_path)
                if blocks:
                    # İlk bloğun replace'ini new_content olarak kullan
                    change["operation"] = "create"
                    change["new_content"] = blocks[0].get("replace", "")
                    resolved_changes.append(change)
                continue

            # Her search/replace bloğunu sırayla uygula
            modified_content = current_content
            all_applied = True

            for i, block in enumerate(blocks):
                search_text = block.get("search", "")
                replace_text = block.get("replace", "")

                if not search_text:
                    logger.warning("empty_search_block", file=file_path, block_index=i)
                    continue

                if search_text in modified_content:
                    # Birebir eşleşme bulundu
                    modified_content = modified_content.replace(search_text, replace_text, 1)
                    logger.info("search_replace_applied", file=file_path, block_index=i)
                else:
                    # Eşleşme bulunamadı — normalize ederek dene
                    matched = self._fuzzy_search_replace(modified_content, search_text, replace_text)
                    if matched is not None:
                        modified_content = matched
                        logger.info("search_replace_applied_fuzzy", file=file_path, block_index=i)
                    else:
                        logger.error(
                            "search_block_not_found",
                            file=file_path,
                            block_index=i,
                            search_preview=search_text[:100],
                        )
                        all_applied = False

            if not all_applied:
                logger.warning("partial_changes_applied", file=file_path)

            resolved_changes.append({
                "file_path": file_path,
                "operation": "modify",
                "new_content": modified_content,
                "change_description": change.get("change_description", ""),
            })

        result["changes"] = resolved_changes
        return result

    def _fuzzy_search_replace(self, content: str, search: str, replace: str) -> str | None:
        """Whitespace farklarını tolere ederek eşleşme dener."""
        # Normalizasyon: satır sonu ve fazla boşlukları düzelt
        def normalize(text: str) -> str:
            lines = text.replace("\r\n", "\n").split("\n")
            return "\n".join(line.rstrip() for line in lines)

        norm_content = normalize(content)
        norm_search = normalize(search)

        if norm_search in norm_content:
            # Normalize edilmiş eşleşme bulundu, orijinal içerikte
            # eşleşen bölgeyi bul ve değiştir
            idx = norm_content.index(norm_search)

            # Orijinal content'te aynı karakter aralığını bul
            # (normalize sadece trailing whitespace kaldırdığı için
            # satır sayıları eşleşmeli)
            search_lines = norm_search.split("\n")
            content_lines = content.replace("\r\n", "\n").split("\n")
            norm_content_lines = norm_content.split("\n")

            # Başlangıç satırını bul
            start_line = norm_content[:idx].count("\n")
            end_line = start_line + len(search_lines)

            if end_line <= len(content_lines):
                before = "\n".join(content_lines[:start_line])
                after = "\n".join(content_lines[end_line:])
                parts = [p for p in [before, replace, after] if p]
                return "\n".join(parts)

        return None

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
