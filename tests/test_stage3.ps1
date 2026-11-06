[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = "python"
if (Test-Path ".\.venv\Scripts\python.exe") { $py = ".\.venv\Scripts\python.exe" }

function Run-Py {
    & $py @args 2>&1 | ForEach-Object { Write-Host $_ }
}

$repo = ".\tests\test_repo.txt"

Write-Host "`n--- 1. Обход графа от корня A ---"
Run-Py src/Main.py --test-mode -p A -r $repo

Write-Host "`n--- 2. Фильтр --filter D исключает пакет D ---"
Run-Py src/Main.py --test-mode -p A -r $repo --filter D

Write-Host "`n--- 3. Фильтр --filter G исключает пакет G ---"
Run-Py src/Main.py --test-mode -p A -r $repo --filter G

Write-Host "`n--- 4. Фильтр корневого пакета: пустой граф ---"
Run-Py src/Main.py --test-mode -p A -r $repo --filter A

Write-Host "`n--- 5. Обход подграфа от пакета B ---"
Run-Py src/Main.py --test-mode -p B -r $repo

Write-Host "`n--- 6. Ошибка E11: пакета нет в тестовом репозитории ---"
Run-Py src/Main.py --test-mode -p Q -r $repo

Write-Host "`n--- 7. Ошибка E04: строчные буквы в тестовом режиме ---"
Run-Py src/Main.py --test-mode -p abc -r $repo

Write-Host "`n--- 8. Ошибка E06: файл тестового репозитория не найден ---"
Run-Py src/Main.py --test-mode -p A -r .\tests\missing.txt

Write-Host "`n--- 9. Реальный реестр Cargo: serde 1.0.0 ---"
Run-Py src/Main.py -p serde -r https://crates.io --version 1.0.0
