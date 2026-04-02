# 🤖 AI-Powered Azure DevOps Agent: Autonomous PR Engine

Bu proje, Azure Boards üzerindeki iş maddelerini (Work Items) otomatik olarak analiz eden, ilgili kod değişikliklerini Azure Repos üzerinde gerçekleştiren ve uçtan uca bir Pull Request (PR) süreci yöneten otonom bir yapay zeka ajanıdır.

## 🚀 Genel Bakış

Sistem, yazılım geliştirme yaşam döngüsündeki (SDLC) manuel süreçleri minimize etmek için tasarlanmıştır. Bir iş maddesi belirli bir duruma geldiğinde tetiklenir, kod tabanını anlar, gerekli güncellemeleri yapar ve insan incelemesine hazır bir PR oluşturur.

### Temel Özellikler

- **Akıllı Analiz**: Azure Boards maddelerindeki (User Story, Bug) gereksinimleri ve kabul kriterlerini doğal dil işleme ile anlar.
- **Kod Farkındalığı (RAG)**: Mevcut kod tabanını tarayarak değişikliğin yapılacağı en doğru noktaları tespit eder.
- **Otonom Geliştirme**: Python tabanlı ajanlar aracılığıyla kod üretimi ve dosya güncellemelerini gerçekleştirir.
- **Git Otomasyonu**: Otomatik branch yönetimi, commit ve PR süreçlerini yönetir.
- **İnsan Denetimi (Human-in-the-loop)**: Oluşturulan tüm değişiklikler insan onayı için PR aşamasında bekletilir.

## 🏗️ Mimari Yapı

Proje, çoklu ajan (Multi-Agent) prensibiyle çalışmaktadır:

| Katman | Teknoloji | Görev |
|--------|-----------|-------|
| **Trigger Layer** | Azure DevOps Webhooks + FastAPI | Gelen sinyalleri yakalar |
| **Orchestrator** | LangGraph | İş akışını yönetir, ajanları koordine eder |
| **Context Engine** | LlamaIndex (Code RAG) | Kod tabanını vektörize eder, bağlam sağlar |
| **Action Layer** | Azure DevOps SDK + GitPython | Branch, commit, PR işlemlerini yapar |

## 📂 Proje Yapısı

```
├── main.py                         # FastAPI giriş noktası
├── config/
│   └── settings.py                 # Pydantic settings (.env)
├── models/
│   └── schemas.py                  # WorkItem, CodeChange, PRDetails, vb.
├── agents/
│   ├── requirements_agent.py       # İş maddesini analiz eder
│   ├── search_agent.py             # Kod tabanında ilgili dosyaları bulur
│   ├── coding_agent.py             # Kod değişikliklerini üretir
│   ├── review_agent.py             # Üretilen kodu inceler
│   └── git_agent.py                # Branch açar, PR oluşturur
├── orchestrator/
│   ├── state.py                    # LangGraph state tanımı
│   └── graph.py                    # LangGraph iş akışı grafiği
├── context/
│   └── code_rag.py                 # LlamaIndex ile Code RAG
├── services/
│   ├── azure_devops.py             # Azure DevOps SDK wrapper
│   └── git_service.py              # GitPython wrapper
└── webhooks/
    └── handlers.py                 # Webhook endpoint'leri
```

## 🛠️ Teknoloji Yığını

| Bileşen | Teknoloji |
|---------|-----------|
| Dil | Python 3.10+ |
| AI Framework | LangGraph |
| LLM | Azure OpenAI (GPT-4o) |
| Web Framework | FastAPI |
| SDK | azure-devops, GitPython |
| Veri Bağlamı | LlamaIndex (Code RAG) |

## ⚙️ Kurulum

### 1. Gereksinimler

- Azure DevOps Personal Access Token (PAT)
- Azure OpenAI API Key & Endpoint
- Python 3.10+ sanal ortamı

### 2. Yükleme

```bash
git clone <repo-url>
cd AgenticAI
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -r requirements.txt
```

### 3. Yapılandırma

`.env.example` dosyasını `.env` olarak kopyalayıp bilgileri doldurun:

```bash
cp .env.example .env
```

```env
AZURE_DEVOPS_PAT=your_pat_here
AZURE_DEVOPS_ORG_URL=https://dev.azure.com/your-org
AZURE_DEVOPS_PROJECT=your-project
AZURE_OPENAI_API_KEY=your_key
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_DEPLOYMENT=gpt-4o
GIT_REPO_PATH=C:/repos/target-repo
GIT_REMOTE_URL=https://dev.azure.com/your-org/your-project/_git/your-repo
```

### 4. Çalıştırma

```bash
python main.py
# veya
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

API dökümantasyonu: `http://localhost:8000/docs`

## 📋 İş Akışı (LangGraph Pipeline)

```
┌─────────────────────┐
│  Webhook Trigger     │  Azure DevOps Work Item güncellenir
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Requirements Agent   │  İş maddesini analiz eder
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Search Agent         │  RAG ile ilgili kod dosyalarını bulur
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Coding Agent         │  Kod değişikliklerini üretir
└─────────┬───────────┘
          ▼
┌─────────────────────┐
│ Review Agent         │  Kodu güvenlik/kalite açısından inceler
└─────────┬───────────┘
          │
     ┌────┴────┐
     │ Onay?   │
     └────┬────┘
    EVET  │  HAYIR (max 2 deneme)
     ▼    └──► Coding Agent'a geri döner
┌─────────────────────┐
│ Git Agent            │  Branch açar, commit yapar, PR oluşturur
└─────────────────────┘
```

## ⚠️ Önemli Notlar

- Bu araç bir **yardımcıdır**; üretilen kodlar her zaman kıdemli bir yazılımcı tarafından incelenmelidir.
- Ajanın yetkileri Azure DevOps üzerinde **"Contribute to pull requests"** ile sınırlandırılmalıdır.
- Review Agent onaylamasa bile maksimum 2 denemeden sonra PR oluşturulur (insan incelemesi için).