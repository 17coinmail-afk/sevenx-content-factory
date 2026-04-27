@echo off
echo ========================================
echo    Seven-X Content Factory
echo ========================================
echo.
echo Устанавливаем зависимости...
pip install -r requirements.txt
echo.
echo Запускаем сервер...
echo Открой в браузере: http://localhost:8000
echo.
uvicorn main:app --reload --host 0.0.0.0 --port 8000
pause
