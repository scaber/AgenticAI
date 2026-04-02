import structlog
from langchain_core.messages import SystemMessage, HumanMessage

from config import create_chat_llm
from services import AzureDevOpsService
from models import WorkItem

logger = structlog.get_logger()

SYSTEM_PROMPT = """Sen bir yazılım gereksinim analiz ajanısın.
Azure DevOps'tan gelen iş maddelerini (User Story, Bug) analiz ediyorsun.

Görevin:
1. İş maddesinin başlığını, açıklamasını ve kabul kriterlerini oku.
2. Teknik gereksinimleri çıkar.
3. Değişiklik kapsamını belirle (hangi modüller, dosyalar etkilenecek).
4. Yapılması gereken somut görevleri listele.

Çıktını aşağıdaki formatta ver:
- **Özet**: Kısa bir özet
- **Teknik Gereksinimler**: Madde madde
- **Etkilenen Alanlar**: Modül/dosya tahminleri
- **Görev Listesi**: Yapılması gereken adımlar
"""


class RequirementsAgent:
    def __init__(self):
        self._llm = create_chat_llm(temperature=0)
        self._devops_service = AzureDevOpsService()

    def analyze(self, work_item_id: int) -> dict:
        work_item = self._devops_service.get_work_item(work_item_id)
        logger.info("analyzing_work_item", work_item_id=work_item_id, title=work_item.title)

        prompt = self._build_prompt(work_item)
        response = self._llm.invoke([
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=prompt),
        ])

        analysis = response.content
        logger.info("requirements_analysis_complete", work_item_id=work_item_id)

        return {
            "work_item": work_item.model_dump(),
            "analysis": analysis,
        }

    def _build_prompt(self, work_item: WorkItem) -> str:
        return f"""Aşağıdaki iş maddesini analiz et:

**Tür**: {work_item.work_item_type.value}
**Başlık**: {work_item.title}

**Açıklama**:
{work_item.description}

**Kabul Kriterleri**:
{work_item.acceptance_criteria}

**Alan**: {work_item.area_path}
**İterasyon**: {work_item.iteration_path}
"""
