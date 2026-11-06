# Визуализация графа зависимостей Rust-пакетов (Cargo)

**Дисциплина:** Конфигурационное управление  
**Вариант:** № 2  
**Язык реализации:** Python 3  
**Формат конфигурации:** XML

## Описание проекта

Консольное приложение для сбора, анализа и визуализации графа зависимостей пакетов Rust (Cargo). Конфигурация задаётся через XML-файл. Все пять этапов задания полностью реализованы без использования готовых менеджеров пакетов (`cargo`) и сторонних библиотек разрешения зависимостей — задействованы исключительно модули стандартной библиотеки Python (`xml.etree.ElementTree`, `urllib.request`, `json`, `html`, `subprocess`).

## Архитектура и реализованные этапы

### Этап 1. Минимальный прототип с конфигурацией (`src/main.py`)

Чтение и строгая валидация XML-файла с семью параметрами:

| Параметр | Назначение |
| --- | --- |
| `package_name` | Имя анализируемого пакета (`A-Z` при `test_mode=true`) |
| `repository` | URL репозитория Cargo или путь к файлу тестового графа |
| `test_mode` | Режим работы с файлом тестового репозитория (`true` / `false`) |
| `package_version` | Анализируемая версия пакета в формате SemVer |
| `output_file` | Имя выходного SVG-файла с изображением графа (`.svg`) |
| `ascii_tree` | Вывод зависимостей в консоль в формате ASCII-дерева (`true` / `false`) |
| `filter_substring` | Подстрока для исключения пакетов из анализа |

### Этап 2. Сбор данных (`src/cargo_repo.py`)

Получение метаданных по HTTP напрямую из реестра Cargo (`https://crates.io` API и sparse-индекс `https://index.crates.io`), фильтрация обязательных зависимостей времени выполнения (`kind = "normal"`, `optional = false`) и собственная реализация разрешения SemVer-диапазонов (`^`, `~`, `>=`, `<=`, `=`, `*`).

### Этап 3. Основные операции (`src/dep_graph.py`)

Построение полного транзитивного графа зависимостей алгоритмом **DFS без рекурсии** (на явном стеке с трёхцветной разметкой состояний вершин), исключение узлов по `filter_substring`, обнаружение циклических зависимостей (включая самозависимости) и поддержка локальных тестовых графов с пакетами `A-Z`.

### Этап 4. Дополнительные операции (`src/load_order.py`)

Расчёт порядка загрузки зависимостей волновым алгоритмом Кана (обратная топологическая сортировка от листьев к корню) с отдельной обработкой циклических графов и приближённым порядком после разрыва обратных рёбер DFS (доступен через флаг `--load-order` и на ветке `stage-4`).

### Этап 5. Визуализация (`src/visualizer.py`, `src/svg_renderer.py`)

1. Формирование текстового описания графа на языке диаграмм **D2** (`direction: down`, стилизация корня и пунктирная разметка обратных рёбер циклов).
2. Экспорт графа в файл формата **SVG** (`output_file`): автоматически используется установленный бинарник `d2` (если найден в `PATH`), либо встроенный послойный SVG-рендерер на стандартной библиотеке Python.
3. Нерекурсивное построение и вывод **ASCII-дерева** зависимостей при `ascii_tree=true` с отметкой повторно встречающихся поддеревьев `(*)` и циклов `[цикл]`.

## Коды ошибок приложения

| Код | Причина |
| --- | --- |
| `E01` | Файл конфигурации не найден или не читается |
| `E02` | Некорректный синтаксис XML |
| `E03` | Отсутствующий или неожиданный элемент в XML |
| `E04` | Недопустимое имя пакета (или не `A-Z` в тестовом режиме) |
| `E05` | Неверное булево значение (`test_mode`, `ascii_tree`) |
| `E06` | Некорректный URL или не найден файл тестового репозитория |
| `E07` | Неверный формат версии SemVer |
| `E08` | Некорректное имя выходного файла (требуется `*.svg`) |
| `E09` | Недопустимые управляющие символы в `filter_substring` |
| `E10` | Дублирование параметра в XML |
| `E11` | Пакет или подходящая версия отсутствуют в источнике |
| `E12` | Сетевая ошибка или ошибка HTTP при запросе к репозиторию |
| `E13` | Повреждённый формат JSON-метаданных репозитория |
| `E15` | Синтаксическая ошибка в файле тестового репозитория |
| `E16` | Ошибка записи выходного SVG-файла на диск |

## Структура репозитория

```text
project/
├── README.md
├── .gitignore
├── config.xml
├── run.sh
├── run.bat
├── src/
│   ├── main.py
│   ├── cargo_repo.py
│   ├── dep_graph.py
│   ├── load_order.py
│   ├── visualizer.py
│   └── svg_renderer.py
├── tests/
│   └── test_main.py
└── examples/
    ├── config-cycle.xml
    ├── config-diamond.xml
    ├── config-http.xml
    ├── config-isolated.xml
    ├── config-no-deps.xml
    ├── config-test.xml
    ├── config-url.xml
    ├── test-cycle-repository.txt
    └── test-repository.txt
```

## Примеры визуализации для трёх различных пакетов Cargo (Этап 5)

### Пример 1. Пакет `serde_derive` (`1.0.210`) — граф процедурных макросов

Запуск (`config.xml`, сохраняет изображение `graph.svg`):

```bash
python src/main.py --config config.xml
```

Сформированное представление D2:

```d2
direction: down

"serde_derive": "serde_derive (1.0.210)" {style.fill: "#dbeafe"}
"proc-macro2": "proc-macro2 (1.0.106)"
"quote": "quote (1.0.45)"
"syn": "syn (1.0.109 / 2.0.x)"
"unicode-ident": "unicode-ident (1.0.24)"

"serde_derive" -> "proc-macro2"
"serde_derive" -> "quote"
"serde_derive" -> "syn"
"proc-macro2" -> "unicode-ident"
"quote" -> "proc-macro2"
"syn" -> "proc-macro2"
"syn" -> "unicode-ident"
```

Вывод ASCII-дерева (`ascii_tree=true`):

```text
serde_derive v1.0.210
├── proc-macro2 v1.0.106
│   └── unicode-ident v1.0.24
├── quote v1.0.45
│   └── proc-macro2 v1.0.106 (*)
└── syn v2.0.117
    ├── proc-macro2 v1.0.106 (*)
    └── unicode-ident v1.0.24
```

### Пример 2. Пакет `http` (`1.1.0`) — веерный граф базовых сетевых типов

Запуск (`examples/config-http.xml`, сохраняет изображение `http-graph.svg`):

```bash
python src/main.py --config examples/config-http.xml
```

Сформированное представление D2:

```d2
direction: down

"http": "http (1.1.0)" {style.fill: "#dbeafe"}
"bytes": "bytes (1.x)"
"fnv": "fnv (1.0.7)"
"itoa": "itoa (1.0.x)"

"http" -> "bytes"
"http" -> "fnv"
"http" -> "itoa"
```

Вывод ASCII-дерева (`ascii_tree=true`):

```text
http v1.1.0
├── bytes v1.11.0
├── fnv v1.0.7
└── itoa v1.0.17
```

### Пример 3. Пакет `url` (`2.5.0`) — многоуровневый граф с ромбовидной связью

Запуск (`examples/config-url.xml`, сохраняет изображение `url-graph.svg`):

```bash
python src/main.py --config examples/config-url.xml
```

Сформированное представление D2:

```d2
direction: down

"url": "url (2.5.0)" {style.fill: "#dbeafe"}
"form_urlencoded": "form_urlencoded (1.2.x)"
"idna": "idna (0.5.0)"
"percent-encoding": "percent-encoding (2.3.x)"
"tinyvec": "tinyvec (1.x)"
"unicode-bidi": "unicode-bidi (0.3.x)"
"unicode-normalization": "unicode-normalization (0.1.x)"

"url" -> "form_urlencoded"
"url" -> "idna"
"url" -> "percent-encoding"
"form_urlencoded" -> "percent-encoding"
"idna" -> "unicode-bidi"
"idna" -> "unicode-normalization"
"unicode-normalization" -> "tinyvec"
```

Вывод ASCII-дерева (`ascii_tree=true`):

```text
url v2.5.0
├── form_urlencoded v1.2.2
│   └── percent-encoding v2.3.2
├── idna v0.5.0
│   ├── unicode-bidi v0.3.18
│   └── unicode-normalization v0.1.25
│       └── tinyvec v1.10.0
└── percent-encoding v2.3.2
```

## Сравнение со штатными инструментами визуализации Cargo

Штатным средством визуализации структуры зависимостей в менеджере пакетов Rust выступает команда **`cargo tree`** (а для машиночитаемой выгрузки графа — `cargo metadata --format-version 1`; встроенной генерации D2 или SVG в базовой поставке `cargo` нет).

Сопоставление результатов на трёх рассмотренных пакетах:

1. **`http 1.1.0` — полное совпадение:** как `cargo tree -e normal`, так и наш инструмент строят идентичное дерево из трёх листьев (`bytes`, `fnv`, `itoa`).
2. **`serde_derive 1.0.210` — различие в одном опциональном ребре:** в `cargo tree` у пакета `syn` дополнительно отображается ребро `syn -> quote`, тогда как в нашем выводе у `syn` присутствуют только `proc-macro2` и `unicode-ident`. В `Cargo.toml` пакета `syn` зависимость `quote` объявлена с флагом `optional = true` и активируется через `default`-фичу `printing`.
3. **`url 2.5.0` — различие при передаче фич вниз по дереву:** в `cargo tree` под пакетом `tinyvec` появляется узел `tinyvec_macros`, поскольку `unicode-normalization` запрашивает `tinyvec` с фичей `alloc`, включающей опциональную зависимость `tinyvec_macros`.

Обобщённые причины возможных расхождений между нашим анализатором и `cargo` / `cargo tree`:

- **Объединение фич (`features` и `default-features`):** `cargo` вычисляет транзитивное замыкание активированных фич и подключает связанные с ними `optional = true` зависимости; наш инструмент без интерпретатора фич учитывает строго обязательные зависимости (`optional = false`).
- **Сборочные и тестовые зависимости (`build` / `dev`):** `cargo tree` по умолчанию включает `[build-dependencies]` (скрипты `build.rs`, например `cc`, `autocfg`), тогда как наш инструмент анализирует исключительно зависимости времени выполнения (`kind = "normal"`).
- **Целевая платформа (`cfg(...)` / `--target`):** `cargo` отфильтровывает платформенные ветви под текущую ОС и архитектуру, а в сырых метаданных реестра все такие записи имеют `kind = "normal"`.
- **Глобальное разрешение версий и `Cargo.lock`:** `cargo` решает систему ограничений глобально и допускает сосуществование разных SemVer-несовместимых мажорных версий одного пакета в одном графе, тогда как наш итеративный обход выбирает наибольшую подходящую версию при первом обращении.

## Запуск и дополнительные режимы

Стандартный запуск (визуализация D2, генерация SVG и опциональное ASCII-дерево):

```bash
python src/main.py --config config.xml
```

Дополнительный вывод списка смежности (этап 3) и порядка загрузки (этап 4):

```bash
python src/main.py --config examples/config-diamond.xml --show-graph --load-order
python src/main.py --config examples/config-cycle.xml --show-graph --load-order
```

## Тестирование

```bash
python -m unittest discover -s tests -v
```

## Работа с Git

Каждый этап разработан в отдельной ветке (`stage-2` … `stage-5`) и зафиксирован коммитом формата `feat: Этап N. <Название этапа>`:

```bash
git checkout -b stage-5
git add .
git commit -m "feat: Этап 5. Визуализация"
```