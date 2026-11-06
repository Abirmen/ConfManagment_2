[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = "python"
if (Test-Path ".\.venv\Scripts\python.exe") { $py = ".\.venv\Scripts\python.exe" }

function Run-Py {
    & $py @args 2>&1 | ForEach-Object { Write-Host $_ }
}

$url = "https://crates.io"

Write-Host "`n--- 1. Параметры по умолчанию ---"
Run-Py src/Main.py

Write-Host "`n--- 2. Все параметры заданы явно ---"
Run-Py src/Main.py -p rand -r $url --version 0.8.5 -o rand_graph.svg --ascii-tree --filter dev

Write-Host "`n--- 3. Ошибка E04: имя пакета с пробелом ---"
Run-Py src/Main.py -p "bad name"

Write-Host "`n--- 4. Ошибка E06: некорректный URL репозитория ---"
Run-Py src/Main.py -r invalid_url

Write-Host "`n--- 5. Ошибка E06: файл тестового репозитория не найден ---"
Run-Py src/Main.py --test-mode -r .\tests\missing.txt

Write-Host "`n--- 6. Ошибка E07: неверный формат версии ---"
Run-Py src/Main.py --version "1.0 beta"

Write-Host "`n--- 7. Ошибка E08: файл результата без расширения .svg ---"
Run-Py src/Main.py -o graph.jpg

Write-Host "`n--- 8. Ошибка E09: перевод строки в подстроке фильтра ---"
Run-Py src/Main.py --filter "A`nB"
