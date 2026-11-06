[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location (Split-Path -Parent $PSScriptRoot)
$py = "python"
if (Test-Path ".\.venv\Scripts\python.exe") { $py = ".\.venv\Scripts\python.exe" }

function Run-Py {
    & $py @args 2>&1 | ForEach-Object { Write-Host $_ }
}

$mainRepo = ".\tests\test_repo4.txt"
$cycleRepo = ".\tests\test_repo3.txt"

Write-Host "`n--- 1. Порядок загрузки от корня A ---"
Run-Py src/Main.py --test-mode -p A -r $mainRepo --load-order -o stage4_a.svg

Write-Host "`n--- 2. Порядок загрузки с фильтром --filter D ---"
Run-Py src/Main.py --test-mode -p A -r $mainRepo --filter D --load-order -o stage4_filter_d.svg

Write-Host "`n--- 3. Порядок загрузки от подграфа B ---"
Run-Py src/Main.py --test-mode -p B -r $mainRepo --load-order -o stage4_b.svg

Write-Host "`n--- 4. Порядок загрузки изолированного пакета Z ---"
Run-Py src/Main.py --test-mode -p Z -r $mainRepo --load-order -o stage4_z.svg

Write-Host "`n--- 5. Циклический граф (A -> B -> C -> A) ---"
Run-Py src/Main.py --test-mode -p A -r $cycleRepo --load-order -o stage4_cycle.svg

Write-Host "`n--- 6. Циклический граф от C и список смежности ---"
Run-Py src/Main.py --test-mode -p C -r $cycleRepo --load-order --show-graph -o stage4_cycle_c.svg

Write-Host "`n--- 7. Реальный реестр Cargo: serde 1.0.0 ---"
Run-Py src/Main.py -p serde -r https://crates.io --version 1.0.0 --load-order -o stage4_serde.svg
