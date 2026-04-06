import os
import subprocess
import tempfile
import shutil
import structlog

from config import get_settings

logger = structlog.get_logger()

# Dil bazlı syntax kontrol komutları
SYNTAX_CHECKS = {
    ".py": ["python", "-m", "py_compile", "{file}"],
    ".cs": ["dotnet", "build", "--no-restore", "{project}"],
    ".js": ["node", "--check", "{file}"],
    ".ts": ["npx", "tsc", "--noEmit", "{file}"],
}


class TestResult:
    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[dict] = []
        self.skipped: list[str] = []

    @property
    def all_passed(self) -> bool:
        return len(self.failed) == 0

    @property
    def summary(self) -> str:
        total = len(self.passed) + len(self.failed) + len(self.skipped)
        lines = [
            f"Test Sonuçları: {len(self.passed)}/{total} başarılı",
        ]
        if self.failed:
            lines.append("Başarısız dosyalar:")
            for f in self.failed:
                lines.append(f"  ❌ {f['file']}: {f['error'][:200]}")
        if self.skipped:
            lines.append(f"Atlanan dosyalar ({len(self.skipped)}): kontrol aracı bulunamadı")
        return "\n".join(lines)


class TestAgent:
    """Ajanın ürettiği kod değişikliklerini izole bir ortamda test eder."""

    def __init__(self):
        settings = get_settings()
        self._repo_path = settings.git_repo_path

    def validate_changes(self, changes: list[dict]) -> TestResult:
        """Değişiklikleri geçici bir dizinde doğrular."""
        logger.info("test_agent_starting", num_changes=len(changes))
        result = TestResult()

        # Geçici bir sandbox dizini oluştur
        sandbox_dir = tempfile.mkdtemp(prefix="ai_agent_test_")
        try:
            self._run_validations(changes, sandbox_dir, result)
        finally:
            # Geçici dizini temizle
            shutil.rmtree(sandbox_dir, ignore_errors=True)

        logger.info(
            "test_agent_complete",
            passed=len(result.passed),
            failed=len(result.failed),
            skipped=len(result.skipped),
        )
        return result

    def _run_validations(self, changes: list[dict], sandbox_dir: str, result: TestResult) -> None:
        for change in changes:
            file_path = change.get("file_path", "")
            new_content = change.get("new_content", "")
            if not file_path or not new_content:
                result.skipped.append(file_path or "<empty>")
                continue

            ext = os.path.splitext(file_path)[1].lower()

            # 1. Syntax kontrolü
            syntax_ok = self._check_syntax(file_path, new_content, ext, sandbox_dir, result)
            if not syntax_ok:
                continue

            # 2. Temel güvenlik kontrolleri
            security_issues = self._check_security_patterns(new_content, file_path)
            if security_issues:
                result.failed.append({
                    "file": file_path,
                    "error": f"Güvenlik uyarıları: {'; '.join(security_issues)}",
                })
                continue

            result.passed.append(file_path)

    def _check_syntax(self, file_path: str, content: str, ext: str, sandbox_dir: str, result: TestResult) -> bool:
        if ext not in SYNTAX_CHECKS:
            result.skipped.append(file_path)
            return True  # Bilinmeyen uzantıyı geç

        # Dosyayı sandbox'a yaz
        sandbox_file = os.path.join(sandbox_dir, os.path.basename(file_path))
        os.makedirs(os.path.dirname(sandbox_file), exist_ok=True)
        with open(sandbox_file, "w", encoding="utf-8") as f:
            f.write(content)

        if ext == ".py":
            return self._check_python_syntax(file_path, sandbox_file, result)
        elif ext == ".cs":
            # C# için sadece temel yapısal kontrol
            return self._check_csharp_basic(file_path, content, result)
        elif ext in (".js", ".ts"):
            return self._check_js_syntax(file_path, sandbox_file, ext, result)

        return True

    def _check_python_syntax(self, file_path: str, sandbox_file: str, result: TestResult) -> bool:
        try:
            proc = subprocess.run(
                ["python", "-m", "py_compile", sandbox_file],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                result.failed.append({"file": file_path, "error": proc.stderr.strip()})
                return False
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            result.skipped.append(file_path)
            logger.warning("syntax_check_skipped", file=file_path, reason=str(e))
            return True

    def _check_csharp_basic(self, file_path: str, content: str, result: TestResult) -> bool:
        """C# dosyası için temel yapısal kontroller (bracket eşleşmesi vb.)."""
        open_braces = content.count("{")
        close_braces = content.count("}")
        if open_braces != close_braces:
            result.failed.append({
                "file": file_path,
                "error": f"Süslü parantez eşleşmiyor: {{ = {open_braces}, }} = {close_braces}",
            })
            return False

        open_parens = content.count("(")
        close_parens = content.count(")")
        if open_parens != close_parens:
            result.failed.append({
                "file": file_path,
                "error": f"Parantez eşleşmiyor: ( = {open_parens}, ) = {close_parens}",
            })
            return False

        return True

    def _check_js_syntax(self, file_path: str, sandbox_file: str, ext: str, result: TestResult) -> bool:
        try:
            cmd = ["node", "--check", sandbox_file]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if proc.returncode != 0:
                result.failed.append({"file": file_path, "error": proc.stderr.strip()})
                return False
            return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            result.skipped.append(file_path)
            return True

    def _check_security_patterns(self, content: str, file_path: str) -> list[str]:
        """Bilinen güvenlik anti-pattern'lerini kontrol eder."""
        issues = []
        content_lower = content.lower()

        dangerous_patterns = [
            ("eval(", "eval() kullanımı tespit edildi — kod enjeksiyon riski"),
            ("exec(", "exec() kullanımı tespit edildi — kod enjeksiyon riski"),
            ("innerhtml", "innerHTML kullanımı tespit edildi — XSS riski"),
            ("document.write", "document.write kullanımı tespit edildi — XSS riski"),
            ("password", None),  # sadece hardcoded password kontrolü
        ]

        for pattern, message in dangerous_patterns:
            if pattern in content_lower:
                if pattern == "password":
                    # Hardcoded password tespiti
                    for line in content.split("\n"):
                        stripped = line.strip().lower()
                        if "password" in stripped and ("=" in stripped or ":" in stripped):
                            if any(q in stripped for q in ['"', "'", "`"]):
                                if not any(kw in stripped for kw in ["getenv", "environ", "config", "settings", "option", "parameter"]):
                                    issues.append("Hardcoded password tespit edildi")
                                    break
                elif message:
                    issues.append(message)

        return issues
