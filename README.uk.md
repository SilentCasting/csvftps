<div align="center">

<img src="src/csvftps/assets/icon.png" width="96" alt="Іконка CSV FTPS Uploader">

# CSV FTPS Uploader

**Перетворює CSV або Excel за вашими правилами й вивантажує на FTPS-сервер за розкладом.**

[![CI](https://github.com/SilentCasting/csvftps/actions/workflows/ci.yml/badge.svg)](https://github.com/SilentCasting/csvftps/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/SilentCasting/csvftps)](https://github.com/SilentCasting/csvftps/releases/latest)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

[English](README.md) · Українська

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/screenshot-dark.png">
  <img src="docs/screenshot-light.png" width="820" alt="Вікно CSV FTPS Uploader з книгою Excel на вході й журналом завершеного перетворення">
</picture>

</div>

## Навіщо

Прайс-лист чи вивантаження залишків часто треба кожні кілька хвилин
відправляти на FTP-сервер партнера, а партнер хоче бачити деякі значення
у своєму форматі: не `7.5`, а `6-10 inch`. CSV FTPS Uploader робить цей цикл
за вас:

1. читає ваш CSV або Excel і перетворює числа в одній колонці на іменовані діапазони;
2. зберігає результат як CSV або Excel і вивантажує його разом з іншими файлами на FTPS-сервер;
3. чекає й повторює, кожні 10 хвилин або як ви налаштуєте.

## Можливості

- 🔁 **Працює за розкладом** і не зупиняється, коли зникає мережа чи сервер
- 🧮 **Власні діапазони**: `від ≤ значення < до` → будь-яка назва; також порожні клітинки й `NULL`
- 🏷️ Колонка **за номером або назвою**; файли з кількома секціями та повторними заголовками
- 📊 **CSV і Excel** (`.xlsx`, `.xlsm`) на вході, CSV або `.xlsx` на виході, будь-який аркуш
- 🔒 **Шифроване вивантаження**: TLS і для входу, *і* для даних, сертифікат перевіряється
- 🔑 **Пароль у системному сховищі** (Диспетчер облікових даних Windows), а не у файлі
- ♻️ **Повторні спроби** після обриву зв'язку, без повторного надсилання вже вивантаженого
- 🛡️ **Ніколи не вивантажує половину файлу**: CSV спочатку пишеться в тимчасовий файл
- 🌗 Застосунок зі світлою й темною темою, а також **інструмент командного рядка**
- 💾 **Портативний `.exe`** для Windows; Python не потрібен

## Завантаження

Завантажте **`CsvFtps.exe`** з
[останнього релізу](https://github.com/SilentCasting/csvftps/releases/latest)
і запустіть. Встановлювати нічого не треба.

> Windows SmartScreen може попередити про невідомого видавця, бо exe не
> підписаний. Натисніть **Докладніше → Усе одно запустити** або зберіть його
> самостійно з вихідного коду (див. нижче).

## Встановлення з вихідного коду

Потрібен Python 3.10+.

```bash
git clone https://github.com/SilentCasting/csvftps.git
cd csvftps
pip install .
```

Буде встановлено дві команди: `csvftps-gui` (застосунок) і `csvftps` (CLI).

## Використання

### Застосунок

```bash
csvftps-gui
```

1. **Files**: оберіть вхідний файл (CSV або Excel) і куди зберегти
   перетворений; формат визначає розширення `.csv` або `.xlsx`. Додайте інші
   файли, які треба вивантажувати без змін.
2. **Conversion**: оберіть колонку (і аркуш Excel, якщо не перший) та
   налаштуйте діапазони. За замовчуванням це групи розмірів `None`,
   `2-5 inch`, `6-10 inch` і `> 10 inch`.
3. **Server**: введіть хост, користувача й пароль, потім **Test connection**.
4. Натисніть **Start**. Застосунок одразу перетворить і вивантажить файли,
   а потім повторюватиме це кожні *N* хвилин. **Run once** робить один запуск,
   **Convert only** тільки перетворює, без вивантаження.

Налаштування зберігаються автоматично. Щоб розклад починався одразу після
відкриття застосунку, наприклад з папки автозавантаження Windows, запускайте
його з `--start`:

```bash
CsvFtps.exe --start
```

### Командний рядок

```bash
csvftps init              # створити файл налаштувань зі значеннями за замовчуванням
csvftps set-password      # зберегти пароль FTPS у системному сховищі
csvftps test              # перевірити вхід на сервер
csvftps run               # перетворити й вивантажити зараз, потім кожні `interval` секунд
csvftps run --once        # один запуск, наприклад з Планувальника завдань чи cron
csvftps convert           # тільки перетворити, без вивантаження
csvftps convert -i stock.xlsx -o stock.csv   # Excel на вході, CSV на виході
```

```text
2026-10-12 09:30:00 INFO    Converted input.csv -> output.csv: 8 row(s), 7 converted, 1 empty, 0 kept as is
2026-10-12 09:30:01 INFO    Uploaded prices.csv (21 B)
2026-10-12 09:30:01 INFO    Uploaded output.csv (348 B)
2026-10-12 09:30:01 INFO    Uploaded 2 file(s) to ftp.example.com
2026-10-12 09:30:01 INFO    Next run at 09:40:00
```

| Параметр | Опис |
| --- | --- |
| `-c, --config FILE` | Файл налаштувань (за замовчуванням див. нижче) |
| `-q, --quiet` | Виводити тільки попередження й помилки |
| `--log-file FILE` | Додатково дописувати журнал у `FILE` |
| `run --once` | Один запуск і вихід |
| `run --no-upload` | Тільки перетворити |
| `run --interval SECONDS` | Інший інтервал між запусками |
| `convert -i CSV -o CSV` | Інші вхідний і вихідний файли |
| `set-password --delete` | Видалити збережений пароль |

Коди виходу: `0` успіх, `1` запуск не вдався (або бракувало деяких файлів),
`2` неправильні налаштування чи аргументи.

## Налаштування

Застосунок і CLI використовують один TOML-файл:

- Windows: `%APPDATA%\csvftps\config.toml`
- Linux/macOS: `~/.config/csvftps/config.toml`

Щоб узяти інший файл, використайте `-c` (CLI), передайте шлях застосунку або
задайте `CSVFTPS_CONFIG`. Відносні шляхи в ньому рахуються від його папки.
Приклад з коментарями лежить у [`examples/csvftps.toml`](examples/csvftps.toml);
його можна спробувати без сервера:

```bash
csvftps convert -c examples/csvftps.toml
```

```toml
interval = 600                    # секунд між запусками

[files]
input = "input.csv"
output = "output.csv"
extra = ["prices.csv"]            # вивантажуються без змін

[csv]
delimiter = ";"                   # тільки для CSV
header_column = 3                 # рядки з маркером у цій колонці вважаються заголовками
header_markers = ["Name Exchange"]

[excel]
sheet = "Stock"                   # тільки для Excel на вході: назва або номер з 1; якщо не задано, перший аркуш

[convert]
column = "Size"                   # або індекс з 0, наприклад 4
empty_values = ["", "NULL"]
empty_label = "None"

[[convert.ranges]]                # min <= значення < max, спрацьовує перший збіг
min = 2
max = 6
label = "2-5 inch"

[server]
host = "ftp.example.com"
port = 21
user = "dealer"
remote_dir = "/upload"
verify_certificate = true         # false тільки для сервера із самопідписаним сертифікатом, якому ви довіряєте
```

### Як перетворюються значення

- Перший рядок і кожен рядок, у якого в `header_column` стоїть один із
  `header_markers`, є заголовком і копіюється без змін. Якщо `column` задано
  назвою, її шукають у кожному заголовку заново.
- Клітинки зі списку `empty_values` замінюються на `empty_label`.
- Числа (`7.5` і `7,5` однаково) отримують назву першого діапазону, в який
  вони потрапляють.
- Решта (текст, короткі рядки) лишається як є і згадується в журналі.

### Файли Excel

Формат кожного файлу визначається розширенням: `.xlsx` і `.xlsm` читаються
як Excel, `.xlsx` записується як Excel, усе інше вважається CSV. Тому
працює будь-яка комбінація: Excel у CSV, CSV в Excel або Excel в Excel.

- Клітинки читаються так, як їх показав би експорт у CSV: `12`, `7.5`,
  `2026-10-25`, `TRUE`. Для формул береться значення, яке Excel обчислив
  востаннє.
- У вихідному Excel звичайні числа зберігаються як числа, рядки-заголовки
  виділяються жирним, а перший рядок закріплюється. Текст на зразок `007`
  лишається текстом, а текст, що починається з `=`, ніколи не стає формулою.
- Старі книги `.xls` не підтримуються: спочатку збережіть їх як `.xlsx`.
  Книги з макросами (`.xlsm`) можна читати, але не записувати.
- `delimiter` і кодування стосуються тільки CSV-файлів.

### Пароль

Пароль ніколи не записується у файл налаштувань. Він береться зі змінної
середовища `CSVFTPS_PASSWORD`, якщо вона є, інакше із системного сховища
(Диспетчер облікових даних Windows, Keychain на macOS, Secret Service на Linux).
Зберегти його можна командою `csvftps set-password` або галочкою
**Remember password** у застосунку.

## Розробка

```bash
python -m venv .venv
.venv\Scripts\activate          # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev,build]"

pytest                          # запустити тести
ruff check . && ruff format .   # лінтер і форматування
python packaging/build_exe.py   # зібрати dist/CsvFtps.exe
```

Тести звіряють діапазони за замовчуванням з оригінальним скриптом 2022 року
на тисячах значень, перетворюють справжні книги Excel в обидва боки й
проганяють код вивантаження через фейковий FTPS-сервер.

### Реліз

Збільште `__version__` у `src/csvftps/__init__.py`, оновіть `CHANGELOG.md`,
потім надішліть тег:

```bash
git tag v1.0.0
git push origin v1.0.0
```

GitHub Actions запустить тести, збере exe й опублікує реліз.

### Структура проєкту

```text
src/csvftps/
├── config.py       # налаштування: dataclass-и, читання/запис TOML, перевірка
├── transform.py    # перетворення: заголовки, діапазони, атомарний запис
├── excel.py        # читання й запис книг .xlsx
├── upload.py       # вивантаження FTPS з TLS, повторами й продовженням
├── credentials.py  # пароль зі змінної середовища або системного сховища
├── runner.py       # один запуск (перетворення + вивантаження) і цикл за розкладом
├── cli.py          # інтерфейс командного рядка
├── gui.py          # застосунок на CustomTkinter
└── assets/         # іконка
examples/           # приклад CSV, книги Excel і налаштувань з коментарями
tests/              # тести pytest
packaging/          # скрипт збирання PyInstaller
```

## Ліцензія

[MIT](LICENSE) © SilentCasting
