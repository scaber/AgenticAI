import hmac
import hashlib
import traceback
import structlog
from fastapi import APIRouter, Request, HTTPException, BackgroundTasks

from config import get_settings
from models import WebhookPayload
from orchestrator import get_compiled_graph

logger = structlog.get_logger()
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Pipeline çalıştırma sonuçlarını tutar
pipeline_runs: list[dict] = []


def verify_webhook_signature(payload_body: bytes, signature: str, secret: str) -> bool:
    if not secret:
        return True  # Skip verification if no secret configured
    expected = hmac.new(secret.encode(), payload_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def run_agent_pipeline(work_item_id: int):
    print(f"\n{'='*60}")
    print(f"🚀 PIPELINE BAŞLADI - Work Item #{work_item_id}")
    print(f"{'='*60}")

    run_info = {"work_item_id": work_item_id, "status": "running", "steps": []}
    pipeline_runs.append(run_info)

    try:
        graph = get_compiled_graph()
        initial_state = {
            "work_item_id": work_item_id,
            "retry_count": 0,
            "status": "started",
            "error": "",
        }

        # Her adımı stream ederek logla
        for step in graph.stream(initial_state):
            for node_name, node_output in step.items():
                status = node_output.get("status", "")
                print(f"\n✅ [{node_name}] tamamlandı → {status}")

                if node_name == "analyze_requirements":
                    analysis = node_output.get("analysis", "")
                    print(f"   📋 Analiz:\n{analysis[:500]}")

                elif node_name == "search_codebase":
                    results = node_output.get("search_results", [])
                    print(f"   🔍 Bulunan dosya sayısı: {len(results)}")
                    for r in results[:5]:
                        print(f"      - {r.get('file_path', '?')} (skor: {r.get('score', 0):.3f})")

                elif node_name == "generate_code":
                    changes = node_output.get("changes", [])
                    print(f"   💻 Üretilen değişiklik sayısı: {len(changes)}")
                    for c in changes:
                        print(f"      - {c.get('file_path', '?')}: {c.get('change_description', '')[:100]}")

                elif node_name == "test_code":
                    test_passed = node_output.get("test_passed", False)
                    test_result = node_output.get("test_result", "")
                    print(f"   🧪 Test sonucu: {'✅ BAŞARILI' if test_passed else '❌ BAŞARISIZ'}")
                    if test_result:
                        print(f"   {test_result[:300]}")

                elif node_name == "review_code":
                    review = node_output.get("review_result", {})
                    approved = node_output.get("review_approved", False)
                    print(f"   🔎 İnceleme sonucu: {'✅ ONAYLANDI' if approved else '❌ REDDEDİLDİ'}")
                    for issue in review.get("issues", [])[:5]:
                        print(f"      ⚠️ {issue}")

                elif node_name == "create_pr":
                    pr_id = node_output.get("pr_id", "?")
                    branch = node_output.get("branch_name", "?")
                    print(f"   🎉 PR Oluşturuldu! PR #{pr_id} → {branch}")

                run_info["steps"].append({"node": node_name, "status": status})

        run_info["status"] = "completed"
        print(f"\n{'='*60}")
        print(f"🎉 PIPELINE TAMAMLANDI - Work Item #{work_item_id}")
        print(f"{'='*60}\n")

    except Exception as e:
        run_info["status"] = "failed"
        run_info["error"] = str(e)
        print(f"\n{'='*60}")
        print(f"❌ PIPELINE HATA - Work Item #{work_item_id}")
        print(f"   Hata: {e}")
        traceback.print_exc()
        print(f"{'='*60}\n")


@router.post("/workitem-updated")
async def handle_workitem_update(
    request: Request,
    background_tasks: BackgroundTasks,
):
    settings = get_settings()
    body = await request.body()

    # Webhook imza doğrulaması
    signature = request.headers.get("X-Hub-Signature", "")
    if not verify_webhook_signature(body, signature, settings.webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = WebhookPayload.model_validate_json(body)

    work_item_id = payload.work_item_id
    if work_item_id is None:
        raise HTTPException(status_code=400, detail="Work item ID not found in payload")

    # Pipeline'ı arka planda çalıştır
    background_tasks.add_task(run_agent_pipeline, work_item_id)

    logger.info("webhook_received", work_item_id=work_item_id, event_type=payload.event_type)
    return {"status": "accepted", "work_item_id": work_item_id}


@router.post("/test/{work_item_id}")
async def manual_test(work_item_id: int, background_tasks: BackgroundTasks):
    """Manuel test: Work Item ID vererek pipeline'ı tetikler."""
    print(f"\n📨 Manuel test tetiklendi: Work Item #{work_item_id}")
    background_tasks.add_task(run_agent_pipeline, work_item_id)
    return {"status": "accepted", "work_item_id": work_item_id, "message": "Pipeline başlatıldı, sunucu loglarını takip edin"}


@router.get("/runs")
async def get_runs():
    """Son pipeline çalışmalarını gösterir."""
    return {"runs": pipeline_runs[-10:]}


@router.get("/health")
async def health_check():
    return {"status": "healthy"}
