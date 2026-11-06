[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = "python"
if (Test-Path ".\.venv\Scripts\python.exe") { $py = ".\.venv\Scripts\python.exe" }

function Run-Py {
    & $py @args 2>&1 | ForEach-Object { Write-Host $_ }
}

$url = "https://crates.io"

Write-Host "`n--- 1. Пакет без зависимостей: serde 1.0.0 ---"
Run-Py src/Main.py -p serde -r $url --version 1.0.0

Write-Host "`n--- 2. Пакет с зависимостями: rand 0.8.5 ---"
Run-Py src/Main.py -p rand -r $url --version 0.8.5

Write-Host "`n--- 3. Пакет с зависимостями: serde_derive 1.0.100 ---"
Run-Py src/Main.py -p serde_derive -r $url --version 1.0.100

Write-Host "`n--- 4. Ошибка E14: тестовый режим появится на этапе 3 ---"
Run-Py src/Main.py --test-mode -p A -r .\tests\test_repo.txt

Write-Host "`n--- 5. Ошибка E04: имя пакета с пробелом ---"
Run-Py src/Main.py -p "bad name" -r $url --version 1.0.0

Write-Host "`n--- 6. Ошибка E06: некорректный URL репозитория ---"
Run-Py src/Main.py -p serde -r invalid_url --version 1.0.0

Write-Host "`n--- 7. Ошибка E11: несуществующая версия пакета ---"
Run-Py src/Main.py -p serde -r $url --version 999.999.999

Write-Host "`n--- 8. Ошибка E07: версия не указана ---"
Run-Py src/Main.py -p serde -r $url

Write-Host "`n--- 9. Ошибка E07: неверный формат версии ---"
Run-Py src/Main.py -p serde -r $url --version "1.0 beta"

Write-Host "`n--- 10. Ошибка E08: файл результата без расширения .svg ---"
Run-Py src/Main.py -p serde -r $url --version 1.0.0 -o result.png
