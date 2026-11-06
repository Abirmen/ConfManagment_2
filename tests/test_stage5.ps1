[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = "python"
if (Test-Path ".\.venv\Scripts\python.exe") { $py = ".\.venv\Scripts\python.exe" }

function Run-Py {
    & $py @args 2>&1 | ForEach-Object { Write-Host $_ }
}

$diamond = ".\tests\test_repo5.txt"
$mainRepo = ".\tests\test_repo4.txt"
$cycleRepo = ".\tests\test_repo3.txt"

Write-Host "`n--- 1. Параметры по умолчанию (тестовый репозиторий, корень A) ---"
Run-Py src/Main.py --test-mode

Write-Host "`n--- 2. Ромбовидный граф: D2, SVG и ASCII-дерево ---"
Run-Py src/Main.py --test-mode -p A -r $diamond -o stage5_diamond.svg

Write-Host "`n--- 3. Граф с версиями, списком смежности и порядком загрузки ---"
Run-Py src/Main.py --test-mode -p A -r $mainRepo -o stage5_main.svg --show-graph --load-order

Write-Host "`n--- 4. Циклический граф: пометки циклов в D2, SVG и дереве ---"
Run-Py src/Main.py --test-mode -p A -r $cycleRepo -o stage5_cycle.svg --show-graph --load-order

Write-Host "`n--- 5. Отключение ASCII-дерева ---"
Run-Py src/Main.py --test-mode -p A -r $diamond -o stage5_no_tree.svg --no-ascii-tree

Write-Host "`n--- 6. Ошибка E06: файл тестового репозитория не найден ---"
Run-Py src/Main.py --test-mode -p A -r .\tests\missing.txt -o stage5_err.svg

Write-Host "`n--- 7. Ошибка E08: файл результата без расширения .svg ---"
Run-Py src/Main.py --test-mode -p A -r $diamond -o stage5_err.png

Write-Host "`n--- 8. Реальный реестр Cargo: serde 1.0.0 ---"
Run-Py src/Main.py -p serde -r https://crates.io --version 1.0.0 -o stage5_serde.svg
