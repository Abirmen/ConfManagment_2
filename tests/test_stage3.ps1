[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = "python"
if (Test-Path ".\.venv\Scripts\python.exe") { $py = ".\.venv\Scripts\python.exe" }

function Run-Py {
    & $py @args 2>&1 | ForEach-Object { Write-Host $_ }
}

$repo = ".\tests\test_repo3.txt"

Write-Host "`n--- 1. Обход графа от корня A (циклы A -> C -> A и D -> D) ---"
Run-Py src/Main.py --test-mode -p A -r $repo -o stage3_a.svg --show-graph

Write-Host "`n--- 2. Фильтр --filter C исключает пакет C ---"
Run-Py src/Main.py --test-mode -p A -r $repo --filter C -o stage3_filter_c.svg --show-graph

Write-Host "`n--- 3. Фильтр --filter D исключает пакет D ---"
Run-Py src/Main.py --test-mode -p A -r $repo --filter D -o stage3_filter_d.svg --show-graph

Write-Host "`n--- 4. Фильтр корневого пакета: пустой граф ---"
Run-Py src/Main.py --test-mode -p A -r $repo --filter A -o stage3_filter_root.svg --show-graph

Write-Host "`n--- 5. Ошибка E11: пакета нет в тестовом репозитории ---"
Run-Py src/Main.py --test-mode -p Z -r $repo -o stage3_err.svg --show-graph

Write-Host "`n--- 6. Ошибка E04: строчные буквы в тестовом режиме ---"
Run-Py src/Main.py --test-mode -p abc -r $repo -o stage3_err.svg --show-graph

Write-Host "`n--- 7. Ошибка E06: файл тестового репозитория не найден ---"
Run-Py src/Main.py --test-mode -p A -r .\tests\missing.txt -o stage3_err.svg

Write-Host "`n--- 8. Реальный реестр Cargo: serde 1.0.0 ---"
Run-Py src/Main.py -p serde -r https://crates.io --version 1.0.0 -o stage3_serde.svg --show-graph
