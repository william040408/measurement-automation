# =============================================================
# AZtech 빌드 & 배포 스크립트
#
# 사용법:
#   .\deploy.ps1            → 빌드만 (dist\AZtech.exe 생성)
#   .\deploy.ps1 -Deploy    → 빌드 후 서버에 자동 복사
#
# 서버 경로 설정: 아래 $SERVER_PATH 만 수정 후 저장 (최초 1회)
# =============================================================

param(
    [switch]$Deploy
)

# ── 서버 경로 설정 ─────────────────────────────────────────────
# 예: "\\192.168.1.100\AZtech" 또는 "Z:\AZtech"
# 비워두면 수동 복사 안내로 대체
$SERVER_PATH = ""
# ──────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"
$BUILD_EXE  = "dist\AZtech.exe"
$VENV_PIP   = ".\venv38\Scripts\pyinstaller.exe"

# 버전 읽기
$version = & python -c "import importlib.util; s=importlib.util.spec_from_file_location('v','config/version.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); print(m.APP_VERSION)"
Write-Host ""
Write-Host "=============================" -ForegroundColor Cyan
Write-Host " AZtech v$version 빌드 시작" -ForegroundColor Cyan
Write-Host "=============================" -ForegroundColor Cyan

# 빌드
& $VENV_PIP AZtech.spec --noconfirm
if ($LASTEXITCODE -ne 0) {
    Write-Host "`n❌ 빌드 실패" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $BUILD_EXE)) {
    Write-Host "`n❌ 빌드 파일 없음: $BUILD_EXE" -ForegroundColor Red
    exit 1
}

$size = [math]::Round((Get-Item $BUILD_EXE).Length / 1MB, 1)
Write-Host "`n✅ 빌드 완료: $BUILD_EXE ($size MB)" -ForegroundColor Green

# 배포
if ($Deploy) {
    if ($SERVER_PATH -eq "") {
        Write-Host "`n⚠️  SERVER_PATH가 설정되지 않았습니다." -ForegroundColor Yellow
        Write-Host "    deploy.ps1 상단의 `$SERVER_PATH를 서버 경로로 수정하세요."
    } elseif (-not (Test-Path $SERVER_PATH)) {
        Write-Host "`n⚠️  서버 경로에 접근할 수 없습니다: $SERVER_PATH" -ForegroundColor Yellow
        Write-Host "    USB로 $BUILD_EXE 를 복사하세요."
    } else {
        $dest = Join-Path $SERVER_PATH "AZtech.exe"
        Copy-Item $BUILD_EXE $dest -Force
        Write-Host "`n🚀 배포 완료 → $dest" -ForegroundColor Green
        Write-Host "   모든 PC에서 다음 실행 시 v$version 이 자동 적용됩니다."
    }
} else {
    Write-Host ""
    Write-Host "배포하려면: .\deploy.ps1 -Deploy" -ForegroundColor DarkGray
    Write-Host "수동 복사:  $BUILD_EXE → 서버 AZtech 폴더 (AZtech.exe 덮어쓰기)"
}

Write-Host ""
