@echo off
cd /d "%~dp0"
where git >nul 2>nul || (echo Git nao encontrado. Instale em https://git-scm.com & pause & exit /b 1)
if not exist .git git init -b main
git add -A
git commit -m "README: link do video do pitch" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" -m "Claude-Session: https://claude.ai/code/session_01Q2prTxqFccQ4AwzxbZbEjS"
where gh >nul 2>nul && (gh repo create GabrielKSG7/radar-b2b-projeto-aplicado --public --source . --remote origin --push && goto fim)
git remote get-url origin >nul 2>nul || git remote add origin https://github.com/GabrielKSG7/radar-b2b-projeto-aplicado.git
git push -u origin main
:fim
echo.
echo Pronto: https://github.com/GabrielKSG7/radar-b2b-projeto-aplicado
pause
