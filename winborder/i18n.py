"""The languages the interface is shown in.

English is the source language, and the English text of a label is the key: the
tables below map it to the text of one language, and :func:`t` returns the text
it was given when it has no entry. A missing translation can therefore only show
English, never an empty label.

Only the window is translated. The log lines the host produces are
diagnostic output and stay in English, so they can be searched for and compared
between versions.

How the text is written, in every language -- the rules come from reviewing the
wording with the person who uses the program:

* Say what a setting *is*, not what the reader should do with it. Noun phrases,
  not instructions: "Interval before the same edge can be crossed again", not
  "Wait this long before crossing again".
* No second person and no imperatives. "Click a field and press a key" describes
  the author's own UI; "Key remapping for the target device; right-click a field
  to choose from the full list" describes the field.
* No rhetorical questions in titles or descriptions. A dialog that really asks
  something asks it formally: "Reset all settings to their default values?".
* One name per thing. The machine this program runs on is the *PC*; the device it
  drives is the *target device*, or just the target where a label is short. Never
  "host": the word named both sides of the link on this page and its opposite on
  that one, and it is gone from the strings entirely. Nor a synonym invented
  halfway through, nor 被控端 in one label and 目标设备 in the next. Chinese also
  uses 此, never 这个.
* Technical phrasing, not conversational: "the current value is {kind}", not
  "got {kind}"; "see the Log", not "the Log will tell you why".
* Short is a feature, not a compromise. A note that repeats what the page title
  already says is a note that will not be read.
"""

from __future__ import annotations

DEFAULT_LANGUAGE = "en"

# Code, and the name of the language written in that language.
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("en", "English"),
    ("ru", "Русский"),
    ("zh", "简体中文"),
    ("ja", "日本語"),
    ("ko", "한국어"),
)

_NAME_BY_CODE = dict(LANGUAGES)
_CODE_BY_NAME = {name: code for code, name in LANGUAGES}

_LANGUAGE = DEFAULT_LANGUAGE


def codes() -> tuple[str, ...]:
    """Every language code, in the order they are offered."""
    return tuple(code for code, _name in LANGUAGES)


def native_name(code: str) -> str:
    """The name of a language in that language."""
    return _NAME_BY_CODE.get(code, _NAME_BY_CODE[DEFAULT_LANGUAGE])


def name_for_code(code: object) -> str:
    """The name to show for a value of the language setting."""
    return native_name(code if isinstance(code, str) else DEFAULT_LANGUAGE)


def code_for_name(name: object) -> str | None:
    """The code a shown name stands for, or None when it names no language."""
    if not isinstance(name, str):
        return None
    if name in _CODE_BY_NAME:
        return _CODE_BY_NAME[name]
    for code, native in LANGUAGES:              # codes are accepted as well
        if name.strip().lower() == code:
            return code
    return None


def is_supported(code: object) -> bool:
    return isinstance(code, str) and code in _NAME_BY_CODE


def language() -> str:
    """The language in use."""
    return _LANGUAGE


def set_language(code: object) -> str:
    """Use a language. An unknown code leaves English in place."""
    global _LANGUAGE
    _LANGUAGE = code if is_supported(code) else DEFAULT_LANGUAGE
    return _LANGUAGE


def t(text: str) -> str:
    """The text in the language in use, or the text itself."""
    if _LANGUAGE == DEFAULT_LANGUAGE:
        return text
    return TRANSLATIONS.get(_LANGUAGE, {}).get(text, text)


TRANSLATIONS: dict[str, dict[str, str]] = {
    "ru": {
        # Pages
    "Devices": "Устройства",
    "What this PC can see over Bluetooth LE": "Что этот ПК видит по Bluetooth LE",
    "The target connects from its own Bluetooth settings, where this PC is listed under its Bluetooth name. The list below only shows what is nearby: this PC never appears in it.": "Цель подключается из своих настроек Bluetooth, где этот ПК указан под своим именем Bluetooth. Список ниже показывает только то, что рядом: сам этот ПК в нём не появляется.",
    "Scan": "Сканировать",
    "Stop scanning": "Остановить сканирование",
    "not advertising yet — the Log says why": "пока не вещает — причина в журнале",
    "the advertisement was cut short — see the Log": "вещание было прервано — см. журнал",
    "advertising as {name} — waiting for the target device to pair": "вещание как {name} — ждём сопряжения с целевым устройством",
    "advertising as a keyboard and mouse — waiting for the target device to pair": "вещание как клавиатура и мышь — ждём сопряжения с целевым устройством",
    "connected since {time} — the target device is subscribed": "подключено с {time} — целевое устройство подписано",
    "last connected at {time}": "последнее подключение в {time}",
    "unnamed": "без имени",
    "No devices seen yet": "Пока устройств не видно",
    "cannot write {path}: {error}": "не удалось записать {path}: {error}",
    "Everything Winborder reports": "Всё, что сообщает Winborder",
    "Reports the target accepted": "Принятых целью отчётов",
        "Status": "Состояние",
        "What the bridge is doing right now": "Что мост делает прямо сейчас",
        "Edge": "Край",
        "Where the target sits, and where the keyboard and mouse change hands": "Где находится цель и где клавиатура с мышью переходят к ней",
        "Pointer": "Указатель",
        "How mouse movement reaches the target":
            "Как движение мыши доходит до цели",
        "Keyboard": "Клавиатура",
        "Keys the PC keeps for itself, and what the target receives":
            "Клавиши, которые остаются у ПК, и то, что получает цель",
        "Log": "Журнал",
        "Generic": "Общие",
        "Startup, maintenance and what is running":
            "Автозапуск, обслуживание и сведения о среде",

        # Navigation
        "Settings file": "Файл настроек",
        "Open settings": "Открыть настройки",
        "Reload settings": "Перечитать настройки",
        "Quit": "Выход",

        # Groups
        "Connection": "Подключение",
        "Movement": "Перемещение",
        "Returning": "Возврат",
        "Scrolling": "Прокрутка",
        "Crossing": "Пересечение",
        "PC keys": "Клавиши ПК",
        "Target keyboard": "Клавиатура цели",
        "Startup": "Запуск",
        "Interface": "Интерфейс",
        "About": "О программе",
        "Developer": "Разработчик",
        "Author of Winborder": "Автор Winborder",
        "Repository": "Репозиторий",
        "Source code and releases": "Исходный код и выпуски",
        "License": "Лицензия",
        "Terms for use and redistribution": "Условия использования и распространения",

        # Values of the target side
        "Left": "Слева",
        "Right": "Справа",
        "Top": "Сверху",
        "Bottom": "Снизу",

        # Settings
        "Target side": "Сторона цели",
        "Which side of the PC the target device sits on":
            "С какой стороны от ПК находится целевое устройство",
        "Pointer gain": "Усиление указателя",
        "1.0 moves the target pointer as far as the PC cursor":
            "1.0 — указатель цели смещается на столько же, сколько курсор ПК",
        "Speed gain": "Усиление по скорости",
        "Extra pointer gain proportional to how fast the mouse moves":
            "Добавочное усиление, пропорциональное скорости движения мыши",
        "Damping": "Демпфирование",
        "How far you have to pull back towards the PC before control returns. "
        "Raise it if a return arrives while the target pointer still looks "
        "inside its screen":
            "Насколько потянуть к ПК, чтобы вернуть управление. Увеличьте, если "
            "возврат происходит, пока указатель цели ещё в пределах экрана",
        "Invert vertical scroll": "Инвертировать вертикальную прокрутку",
        "Vertical scrolling is reversed on the target":
            "Вертикальная прокрутка на цели идёт в обратном направлении",
        "Horizontal scrolling is reversed on the target":
            "Горизонтальная прокрутка на цели идёт в обратном направлении",
        "Invert horizontal scroll": "Инвертировать горизонтальную прокрутку",
        "Scroll step up": "Шаг прокрутки вверх",
        "Scroll step down": "Шаг прокрутки вниз",
        "Lines per wheel detent": "Строк за один щелчок колеса",
        "Cross at the screen edge": "Пересекать край экрана",
        "The toggle key switches this while running":
            "Во время работы переключается клавишей-переключателем",
        "Edge inset": "Отступ от края",
        "How close to the PC screen edge the cursor has to get":
            "Насколько близко курсор должен подойти к краю экрана ПК",
        "Exit clearance": "Отступ при выходе",
        "How far the cursor is placed back inside the PC screen on exit":
            "Насколько курсор возвращается внутрь экрана ПК при выходе",
        "Enter cooldown": "Задержка входа",
        "Seconds before the same edge can be crossed again":
            "Сколько секунд до повторного пересечения того же края",
        "Return by pulling back": "Возврат обратной протяжкой",
        "Pulling the pointer towards the PC returns control":
            "Потяните указатель к ПК, чтобы вернуть управление",
        "Release control": "Освободить управление",
        "Toggle edge crossing": "Переключить пересечение края",
        "Comma separated key names, for example F1":
            "Имена клавиш через запятую, например F1",
        "Comma separated key names, for example F2":
            "Имена клавиш через запятую, например F2",
        "Forward media keys": "Передавать мультимедиа-клавиши",
        "Volume and transport keys go to the target":
            "Клавиши громкости и управления воспроизведением уходят цели",
        "Capture mouse buttons": "Захватывать кнопки мыши",
        "Clicks go to the target while it has control":
            "Пока управление у цели, щелчки уходят ей",
        "Start with Windows": "Запускать с Windows",
        "One value under HKCU Software\\Microsoft\\Windows\\CurrentVersion\\Run, "
        "holding the command line; nothing else is written":
            "Одно значение в HKCU Software\\Microsoft\\Windows\\CurrentVersion\\Run "
            "с командной строкой; больше ничего не записывается",
        "Start hidden": "Запускать скрытым",
        "Open with the notification area icon only, without this window":
            "Только значок в области уведомлений, без этого окна",
        "Remap keys": "Переназначение клавиш",
        "Click a field and press the key, or right-click it to pick from the "
        "full list. The PC is unaffected":
            "Щёлкните по полю и нажмите клавишу; правый щелчок открывает "
            "полный список. На ПК это не влияет",
        "Search keys": "Поиск клавиш",
        "to": "в",
        "No keys remapped": "Клавиши не переназначены",
        "Press a key": "Нажмите клавишу",
        "Language": "Язык",
        "The language of this window. Changes apply immediately":
            "Язык этого окна. Изменения применяются сразу",

        # Status page
        "Mode": "Режим",
        "Which side has the keyboard and mouse":
            "У кого сейчас клавиатура и мышь",
        "PC cursor": "Курсор ПК",
        "Fraction of the PC screen": "Доля экрана ПК",
        "Target pointer": "Указатель цели",
        "Fraction of the tracked surface": "Доля отслеживаемой области",
        "Travel": "Смещение",
        "Motion since the target was entered, negative on the way back":
            "Смещение с момента входа, при возврате отрицательное",
    "Device link": "Связь с устройством",
        "pc": "ПК",
        "target": "цель",
        "up": "есть",
        "down": "нет",
        "written": "отправлено",
        "bad": "ошибки",

        # About
        "Version": "Версия",
        "Shared by the window and the background service": "Общая для окна и фоновой службы",
        "Running from": "Запущено из",
        "An executable, or Python": "Исполняемый файл или Python",
        "executable": "исполняемый файл",
        "The file on disk that holds the current configuration": "Файл на диске, в котором хранится текущая конфигурация",
        "Open settings file": "Открыть файл настроек",
        "Reset to defaults": "Сбросить к значениям по умолчанию",

        # Holding the bridge still
        "Pause": "Пауза",
        "Resume": "Продолжить",
        "Paused": "Мост на паузе",
        "Running": "Мост работает",
        "Pause log": "Пауза журнала",
        "Resume log": "Продолжить журнал",

        # Log page
        "Auto-scroll": "Автопрокрутка",
        "{count} new lines": "новых строк: {count}",
        "Clear": "Очистить",

        # Messages
        "Saved": "Сохранено",
        "Settings reset to defaults":
            "Настройки сброшены к значениям по умолчанию",
        "Reset every setting to its default value?":
            "Сбросить все настройки к значениям по умолчанию?",
        "Reloaded {path}": "Загружено из {path}",
        "Cannot write {path}: {error}": "Не удаётся записать {path}: {error}",
        "Could not change the startup entry":
            "Не удалось изменить запись автозапуска",

        # Rejected input
        "{label} must be a number": "{label}: должно быть числом",
        "{label}: unknown key {name}": "{label}: неизвестная клавиша {name}",
        "{label}: every row needs a key on both sides":
            "{label}: в каждой строке нужны обе клавиши",

        # Settings file
        "settings file not found: {path}": "файл настроек не найден: {path}",
        "{path} is not valid JSON: {error}": "{path} — некорректный JSON: {error}",
        "{path} must contain a JSON object":
            "{path} должен содержать объект JSON",
        "{path}: unknown setting(s): {names}":
            "{path}: неизвестные параметры: {names}",
        "{path}: {name} must be true or false":
            "{path}: {name} — должно быть true или false",
        "{path}: language must be one of {options}":
            "{path}: language — одно из {options}",
        "side must be a string, got {kind}":
            "side — должно быть строкой, а не {kind}",
        "side must be one of {options}, got {value}":
            "side — одно из {options}, а не {value}",
        "{name} must be true or false": "{name} — должно быть true или false",
        "{name} must be a number": "{name} — должно быть числом",
        "{name} cannot be set from the settings file":
            "{name} нельзя задать в файле настроек",
        "{name} must be a list of key names":
            "{name} — список имён клавиш",
        "remap must be an object of {from: to} key names":
            "remap — объект из пар имён клавиш {from: to}",
        "remap values must be key names": "значения remap — имена клавиш",
    },

    "zh": {
        # Pages
    "Devices": "设备",
    "What this PC can see over Bluetooth LE": "此 PC 通过蓝牙 LE 能看到的设备",
        "The target connects from its own Bluetooth settings, where this PC is listed under its Bluetooth name. The list below only shows what is nearby: this PC never appears in it.": "附近 BLE 不包含此 PC",
    "Scan": "扫描",
    "Stop scanning": "停止扫描",
        "not advertising yet — the Log says why": "尚未广播 — 见日志",
    "the advertisement was cut short — see the Log": "广播被中断 — 见日志",
    "advertising as {name} — waiting for the target device to pair": "正在以 {name} 广播 — 等待目标设备配对",
    "advertising as a keyboard and mouse — waiting for the target device to pair": "正在作为键盘和鼠标广播 — 等待目标设备配对",
    "connected since {time} — the target device is subscribed": "已连接，自 {time} — 目标设备已订阅",
    "last connected at {time}": "上次连接 {time}",
    "unnamed": "未命名",
    "No devices seen yet": "尚未发现设备",
    "cannot write {path}: {error}": "无法写入 {path}：{error}",
    "Everything Winborder reports": "Winborder 报告的全部内容",
    "Reports the target accepted": "目标已接受的报告数",
        "Status": "状态",
        "What the bridge is doing right now": "桥接此刻的工作情况",
        "Edge": "边缘",
        "Where the target sits, and where the keyboard and mouse change hands": "目标设备的位置，以及控制权交接的位置",
        "Pointer": "指针",
        "How mouse movement reaches the target": "鼠标于目标设备的行为",
        "Keyboard": "键盘",
        "Keys the PC keeps for itself, and what the target receives": "PC 保留的按键，以及目标设备收到的按键",
        "Log": "日志",
        "Generic": "通用",
        "Startup, maintenance and what is running": "开机启动、维护与运行环境",

        # Navigation
        "Settings file": "设置文件",
        "Open settings": "打开设置",
        "Reload settings": "重新载入设置",
        "Quit": "退出",

        # Groups
        "Connection": "连接",
        "Movement": "移动",
        "Returning": "返回",
        "Scrolling": "滚动",
        "Crossing": "穿越",
        "PC keys": "PC 按键",
        "Target keyboard": "目标设备键盘",
        "Startup": "启动",
        "Interface": "界面",
        "About": "关于",
        "Developer": "开发者",
        "Author of Winborder": "Winborder 的作者",
        "Repository": "代码仓库",
        "Source code and releases": "源代码与发行版",
        "License": "开源协议",
        "Terms for use and redistribution": "使用与再发布的条款",

        # Values of the target side
        "Left": "左侧",
        "Right": "右侧",
        "Top": "上方",
        "Bottom": "下方",

        # Settings
        "Target side": "目标方位",
        "Which side of the PC the target device sits on": "目标设备相对于 PC 的位置",
        "Pointer gain": "指针增益",
        "1.0 moves the target pointer as far as the PC cursor": "目标设备指针移动距离与 PC 光标的比值，1.0 表示两者相同",
        "Speed gain": "速度增益",
        "Extra pointer gain proportional to how fast the mouse moves":
            "随鼠标移动速度额外叠加的指针增益",
        "Damping": "阻尼",
        "How far you have to pull back towards the PC before control returns. Raise it if a return arrives while the target pointer still looks inside its screen": "交还控制权所需的回拉距离",
        "Invert vertical scroll": "反转垂直滚动",
        "Vertical scrolling is reversed on the target": "在目标设备上纵向滚动方向相反",
        "Horizontal scrolling is reversed on the target": "在目标设备上横向滚动方向相反",
        "Invert horizontal scroll": "反转水平滚动",
        "Scroll step up": "向上滚动步长",
        "Scroll step down": "向下滚动步长",
        "Lines per wheel detent": "滚轮每格滚动的行数",
        "Cross at the screen edge": "在屏幕边缘穿越",
        "The toggle key switches this while running": "运行中可以用切换键改变",
        "Edge inset": "边缘内缩",
        "How close to the PC screen edge the cursor has to get": "光标发生穿越时所需的最大距离",
        "Exit clearance": "退出余量",
        "How far the cursor is placed back inside the PC screen on exit": "光标退出后离开屏幕边缘的距离",
        "Enter cooldown": "进入冷却",
        "Seconds before the same edge can be crossed again": "光标进行下一次边缘穿越所需的时间间隔",
        "Return by pulling back": "拉动返回",
        "Pulling the pointer towards the PC returns control":
            "回拉超过阻尼值即交还控制权",
        "Release control": "释放控制权",
        "Toggle edge crossing": "切换边缘穿越",
        "Comma separated key names, for example F1":
            "用逗号分隔的按键名，例如 F1",
        "Comma separated key names, for example F2":
            "用逗号分隔的按键名，例如 F2",
        "Forward media keys": "转发媒体键",
        "Volume and transport keys go to the target": "音量和播放控制键发送到目标设备",
        "Capture mouse buttons": "捕获鼠标按键",
        "Clicks go to the target while it has control": "是否传递鼠标按键",
        "Start with Windows": "开机自动启动",
        "One value under HKCU Software\\Microsoft\\Windows\\CurrentVersion\\Run, holding the command line; nothing else is written": "于 HKCU Software\\Microsoft\\Windows\\CurrentVersion\\Run 注册启动项",
        "Start hidden": "启动时隐藏",
        "Open with the notification area icon only, without this window": "只显示通知区域图标，不打开窗口",
        "Remap keys": "按键重映射",
        "Click a field and press the key, or right-click it to pick from the full list. The PC is unaffected": "于目标设备时，按键的重映射，右键可从完整列表里选择",
        "Search keys": "搜索按键",
        "to": "至",
        "No keys remapped": "尚未重映射任何键",
        "Press a key": "按一个键",
        "Language": "语言",
        "The language of this window. Changes apply immediately": "设置窗口语言",

        # Status page
        "Mode": "模式",
        "Which side has the keyboard and mouse": "键盘和鼠标所处的位置",
        "PC cursor": "PC 光标",
        "Fraction of the PC screen": "占 PC 屏幕的比例",
        "Target pointer": "目标设备指针",
        "Fraction of the tracked surface": "占被跟踪区域的比例",
        "Travel": "位移",
        "Motion since the target was entered, negative on the way back": "进入目标设备之后的净移动量，返回时为负",
        "Device link": "设备连接",
        "pc": "PC",
        "target": "目标设备",
        "up": "已连接",
        "down": "未连接",
        "written": "已写入",
        "bad": "错误",

        # About
        "Version": "版本",
        "Shared by the window and the background service": "窗口与后台服务共用此版本",
        "Running from": "运行方式",
        "An executable, or Python": "可执行文件或 Python",
        "executable": "可执行文件",
        "The file on disk that holds the current configuration": "用于保存当前配置的持久化文件",
        "Open settings file": "打开设置文件",
        "Reset to defaults": "恢复默认值",

        # Holding the bridge still
        "Pause": "暂停",
        "Resume": "继续",
        "Paused": "桥接已暂停",
        "Running": "桥接已恢复",
        "Pause log": "暂停日志",
        "Resume log": "继续日志",

        # Log page
        "Auto-scroll": "自动滚动",
        "{count} new lines": "{count} 行新日志",
        "Clear": "清空",

        # Messages
        "Saved": "已保存",
        "Settings reset to defaults": "设置已恢复默认值",
        "Reset every setting to its default value?": "是否将所有设置恢复为默认值？",
        "Reloaded {path}": "已重新载入 {path}",
        "Cannot write {path}: {error}": "无法写入 {path}：{error}",
        "Could not change the startup entry": "无法修改开机启动项",

        # Rejected input
        "{label} must be a number": "{label} 必须是数字",
        "{label}: unknown key {name}": "{label}：未知的按键 {name}",
        "{label}: every row needs a key on both sides":
            "{label}：每行两边的键都要选",

        # Settings file
        "settings file not found: {path}": "找不到设置文件：{path}",
        "{path} is not valid JSON: {error}": "{path} 不是有效的 JSON：{error}",
        "{path} must contain a JSON object": "{path} 必须包含一个 JSON 对象",
        "{path}: unknown setting(s): {names}": "{path}：未知的设置项：{names}",
        "{path}: {name} must be true or false":
            "{path}：{name} 必须是 true 或 false",
        "{path}: language must be one of {options}":
            "{path}：language 必须是 {options} 之一",
        "side must be a string, got {kind}": "side 必须是字符串，当前结果为 {kind}",
        "side must be one of {options}, got {value}": "side 必须是 {options} 之一，当前结果为 {value}",
        "{name} must be true or false": "{name} 必须是 true 或 false",
        "{name} must be a number": "{name} 必须是数字",
        "{name} cannot be set from the settings file":
            "{name} 不能通过设置文件修改",
        "{name} must be a list of key names": "{name} 必须是按键名列表",
        "remap must be an object of {from: to} key names":
            "remap 必须是 {from: to} 形式的按键名对象",
        "remap values must be key names": "remap 的值必须是按键名",
    },

    "ja": {
        # Pages
    "Devices": "デバイス",
    "What this PC can see over Bluetooth LE": "この PC が Bluetooth LE で見つけられるもの",
    "The target connects from its own Bluetooth settings, where this PC is listed under its Bluetooth name. The list below only shows what is nearby: this PC never appears in it.": "ターゲットは自身の Bluetooth 設定から接続します。そこではこの PC は Bluetooth 名で表示されます。下の一覧は近くにあるものだけを示し、この PC は表示されません。",
    "Scan": "スキャン",
    "Stop scanning": "スキャンを停止",
    "not advertising yet — the Log says why": "まだアドバタイズしていません — 理由はログにあります",
    "the advertisement was cut short — see the Log": "アドバタイズが中断されました — ログを見てください",
    "advertising as {name} — waiting for the target device to pair": "{name} としてアドバタイズ中 — 接続先のペアリング待ち",
    "advertising as a keyboard and mouse — waiting for the target device to pair": "キーボードとマウスとしてアドバタイズ中 — 接続先のペアリング待ち",
    "connected since {time} — the target device is subscribed": "{time} から接続中 — 接続先が購読しています",
    "last connected at {time}": "最後の接続 {time}",
    "unnamed": "名称なし",
    "No devices seen yet": "まだデバイスが見つかりません",
    "cannot write {path}: {error}": "{path} に書き込めません: {error}",
    "Everything Winborder reports": "Winborder が報告するすべて",
    "Reports the target accepted": "ターゲットが受け取ったレポート",
        "Status": "状態",
        "What the bridge is doing right now": "ブリッジの現在の動作",
        "Edge": "エッジ",
        "Where the target sits, and where the keyboard and mouse change hands": "ターゲットの位置と、キーボードとマウスを受け渡す場所",
        "Pointer": "ポインター",
        "How mouse movement reaches the target":
            "マウスの動きが接続先へ届くまで",
        "Keyboard": "キーボード",
        "Keys the PC keeps for itself, and what the target receives":
            "PC 側で使うキーと、接続先へ送られるキー",
        "Log": "ログ",
        "Generic": "一般",
        "Startup, maintenance and what is running":
            "スタートアップ、メンテナンス、実行環境",

        # Navigation
        "Settings file": "設定ファイル",
        "Open settings": "設定を開く",
        "Reload settings": "設定を再読み込み",
        "Quit": "終了",

        # Groups
        "Connection": "接続",
        "Movement": "移動",
        "Returning": "戻り",
        "Scrolling": "スクロール",
        "Crossing": "越え方",
        "PC keys": "PC のキー",
        "Target keyboard": "接続先のキーボード",
        "Startup": "スタートアップ",
        "Interface": "インターフェイス",
        "About": "このアプリについて",
        "Developer": "開発者",
        "Author of Winborder": "Winborder の作者",
        "Repository": "リポジトリ",
        "Source code and releases": "ソースコードとリリース",
        "License": "ライセンス",
        "Terms for use and redistribution": "使用と再配布の条件",

        # Values of the target side
        "Left": "左",
        "Right": "右",
        "Top": "上",
        "Bottom": "下",

        # Settings
        "Target side": "接続先の位置",
        "Which side of the PC the target device sits on":
            "接続先が PC のどちら側にあるか",
        "Pointer gain": "ポインターの倍率",
        "1.0 moves the target pointer as far as the PC cursor":
            "1.0 で PC のカーソルと同じ距離だけ動きます",
        "Speed gain": "速度の倍率",
        "Extra pointer gain proportional to how fast the mouse moves":
            "マウスの速さに比例して加算される倍率",
        "Damping": "ダンピング",
        "How far you have to pull back towards the PC before control returns. "
        "Raise it if a return arrives while the target pointer still looks "
        "inside its screen":
            "PC 側へどれだけ引くと操作を戻すか。接続先のポインターが画面内に"
            "あるのに戻ってしまう場合は大きくします",
        "Invert vertical scroll": "垂直スクロールを反転",
        "Vertical scrolling is reversed on the target":
            "接続先では垂直スクロールが逆向きになります",
        "Horizontal scrolling is reversed on the target":
            "接続先では水平スクロールが逆向きになります",
        "Invert horizontal scroll": "水平スクロールを反転",
        "Scroll step up": "上スクロール量",
        "Scroll step down": "下スクロール量",
        "Lines per wheel detent": "ホイール 1 目盛りあたりの行数",
        "Cross at the screen edge": "画面の端で越える",
        "The toggle key switches this while running":
            "実行中は切り替えキーで変更できます",
        "Edge inset": "端からの余白",
        "How close to the PC screen edge the cursor has to get":
            "カーソルが PC 画面の端へどれだけ近づく必要があるか",
        "Exit clearance": "退出時の余白",
        "How far the cursor is placed back inside the PC screen on exit":
            "退出時にカーソルを PC 画面の内側へどれだけ戻すか",
        "Enter cooldown": "進入の間隔",
        "Seconds before the same edge can be crossed again":
            "同じ端を再び越えられるようになるまでの秒数",
        "Return by pulling back": "引き戻しで戻る",
        "Pulling the pointer towards the PC returns control":
            "ポインターを PC 側へ引くと操作を戻します",
        "Release control": "操作を戻す",
        "Toggle edge crossing": "エッジ越えの切り替え",
        "Comma separated key names, for example F1":
            "カンマ区切りのキー名、例: F1",
        "Comma separated key names, for example F2":
            "カンマ区切りのキー名、例: F2",
        "Forward media keys": "メディアキーを転送",
        "Volume and transport keys go to the target":
            "音量キーと再生キーを接続先へ送ります",
        "Capture mouse buttons": "マウスボタンを取り込む",
        "Clicks go to the target while it has control":
            "接続先が操作権を持つ間はクリックを送ります",
        "Start with Windows": "Windows と同時に起動",
        "One value under HKCU Software\\Microsoft\\Windows\\CurrentVersion\\Run, "
        "holding the command line; nothing else is written":
            "HKCU Software\\Microsoft\\Windows\\CurrentVersion\\Run に値を 1 つ書き、"
            "内容はコマンドラインです。それ以外は書き込みません",
        "Start hidden": "起動時に隠す",
        "Open with the notification area icon only, without this window":
            "このウィンドウを開かず、通知領域のアイコンだけにします",
        "Remap keys": "キーの割り当て変更",
        "Click a field and press the key, or right-click it to pick from the "
        "full list. The PC is unaffected":
            "フィールドをクリックしてキーを押します。右クリックで一覧から選べます。"
            "PC 側は変わりません",
        "Search keys": "キーを検索",
        "to": "→",
        "No keys remapped": "再マップされたキーはありません",
        "Press a key": "キーを押してください",
        "Language": "言語",
        "The language of this window. Changes apply immediately":
            "このウィンドウの言語。変更はすぐに反映されます",

        # Status page
        "Mode": "モード",
        "Which side has the keyboard and mouse":
            "キーボードとマウスがどちら側にあるか",
        "PC cursor": "PC のカーソル",
        "Fraction of the PC screen": "PC 画面に対する割合",
        "Target pointer": "接続先のポインター",
        "Fraction of the tracked surface": "追跡領域に対する割合",
        "Travel": "移動量",
        "Motion since the target was entered, negative on the way back":
            "接続先へ入ってからの移動量、戻る向きは負",
        "Device link": "デバイス接続",
        "pc": "PC",
        "target": "接続先",
        "up": "接続中",
        "down": "未接続",
        "written": "送信",
        "bad": "エラー",

        # About
        "Version": "バージョン",
        "Shared by the window and the background service": "ウィンドウとバックグラウンド サービスで共通",
        "Running from": "実行元",
        "An executable, or Python": "実行ファイルか Python",
        "executable": "実行ファイル",
        "The file on disk that holds the current configuration": "現在の構成を保存するディスク上のファイル",
        "Open settings file": "設定ファイルを開く",
        "Reset to defaults": "既定値に戻す",

        # Holding the bridge still
        "Pause": "一時停止",
        "Resume": "再開",
        "Paused": "ブリッジを一時停止しました",
        "Running": "ブリッジを再開しました",
        "Pause log": "ログを一時停止",
        "Resume log": "ログを再開",

        # Log page
        "Auto-scroll": "自動スクロール",
        "{count} new lines": "新しいログ {count} 件",
        "Clear": "クリア",

        # Messages
        "Saved": "保存しました",
        "Settings reset to defaults": "設定を既定値に戻しました",
        "Reset every setting to its default value?":
            "すべての設定を既定値に戻しますか？",
        "Reloaded {path}": "{path} を再読み込みしました",
        "Cannot write {path}: {error}": "{path} に書き込めません: {error}",
        "Could not change the startup entry":
            "スタートアップ項目を変更できませんでした",

        # Rejected input
        "{label} must be a number": "{label} は数値でなければなりません",
        "{label}: unknown key {name}": "{label}: 不明なキー {name}",
        "{label}: every row needs a key on both sides":
            "{label}: 各行で両側のキーを選んでください",

        # Settings file
        "settings file not found: {path}": "設定ファイルが見つかりません: {path}",
        "{path} is not valid JSON: {error}":
            "{path} は有効な JSON ではありません: {error}",
        "{path} must contain a JSON object":
            "{path} には JSON オブジェクトが必要です",
        "{path}: unknown setting(s): {names}":
            "{path}: 不明な設定: {names}",
        "{path}: {name} must be true or false":
            "{path}: {name} は true か false でなければなりません",
        "{path}: language must be one of {options}":
            "{path}: language は {options} のいずれかです",
        "side must be a string, got {kind}":
            "side は文字列でなければなりません（{kind}）",
        "side must be one of {options}, got {value}":
            "side は {options} のいずれかです（{value}）",
        "{name} must be true or false": "{name} は true か false です",
        "{name} must be a number": "{name} は数値でなければなりません",
        "{name} cannot be set from the settings file":
            "{name} は設定ファイルからは変更できません",
        "{name} must be a list of key names": "{name} はキー名のリストです",
        "remap must be an object of {from: to} key names":
            "remap は {from: to} 形式のキー名のオブジェクトです",
        "remap values must be key names": "remap の値はキー名でなければなりません",
    },

    "ko": {
        # Pages
    "Devices": "기기",
    "What this PC can see over Bluetooth LE": "이 PC 가 블루투스 LE 로 볼 수 있는 기기",
    "The target connects from its own Bluetooth settings, where this PC is listed under its Bluetooth name. The list below only shows what is nearby: this PC never appears in it.": "대상은 자체 블루투스 설정에서 연결하며, 거기에서 이 PC 는 블루투스 이름으로 표시됩니다. 아래 목록은 주변 기기만 보여 주며 이 PC 는 나타나지 않습니다.",
    "Scan": "스캔",
    "Stop scanning": "스캔 중지",
    "not advertising yet — the Log says why": "아직 광고하지 않습니다 — 이유는 로그에 있습니다",
    "the advertisement was cut short — see the Log": "광고가 중단되었습니다 — 로그를 보세요",
    "advertising as {name} — waiting for the target device to pair": "{name} 이름으로 광고 중 — 대상 기기의 페어링을 기다립니다",
    "advertising as a keyboard and mouse — waiting for the target device to pair": "키보드와 마우스로 광고 중 — 대상 기기의 페어링을 기다립니다",
    "connected since {time} — the target device is subscribed": "{time}부터 연결됨 — 대상 기기가 구독 중입니다",
    "last connected at {time}": "마지막 연결 {time}",
    "unnamed": "이름 없음",
    "No devices seen yet": "아직 발견된 기기가 없습니다",
    "cannot write {path}: {error}": "{path} 에 쓸 수 없습니다: {error}",
    "Everything Winborder reports": "Winborder 가 보고하는 모든 내용",
    "Reports the target accepted": "대상이 받아들인 보고 수",
        "Status": "상태",
        "What the bridge is doing right now": "브리지가 지금 하는 일",
        "Edge": "가장자리",
        "Where the target sits, and where the keyboard and mouse change hands": "대상이 있는 방향과 키보드·마우스가 넘어가는 지점",
        "Pointer": "포인터",
        "How mouse movement reaches the target":
            "마우스 움직임이 대상 기기로 전달되는 방식",
        "Keyboard": "키보드",
        "Keys the PC keeps for itself, and what the target receives":
            "PC가 직접 쓰는 키와 대상 기기로 가는 키",
        "Log": "로그",
        "Generic": "일반",
        "Startup, maintenance and what is running":
            "시작 프로그램, 유지 관리, 실행 환경",

        # Navigation
        "Settings file": "설정 파일",
        "Open settings": "설정 열기",
        "Reload settings": "설정 다시 불러오기",
        "Quit": "종료",

        # Groups
        "Connection": "연결",
        "Movement": "이동",
        "Returning": "복귀",
        "Scrolling": "스크롤",
        "Crossing": "넘김",
        "PC keys": "PC 키",
        "Target keyboard": "대상 키보드",
        "Startup": "시작",
        "Interface": "인터페이스",
        "About": "정보",
        "Developer": "개발자",
        "Author of Winborder": "Winborder 제작자",
        "Repository": "저장소",
        "Source code and releases": "소스 코드와 릴리스",
        "License": "라이선스",
        "Terms for use and redistribution": "사용 및 재배포 조건",

        # Values of the target side
        "Left": "왼쪽",
        "Right": "오른쪽",
        "Top": "위",
        "Bottom": "아래",

        # Settings
        "Target side": "대상 기기 위치",
        "Which side of the PC the target device sits on":
            "대상 기기가 PC의 어느 쪽에 있는지",
        "Pointer gain": "포인터 배율",
        "1.0 moves the target pointer as far as the PC cursor":
            "1.0이면 PC 커서와 같은 거리만큼 움직입니다",
        "Speed gain": "속도 배율",
        "Extra pointer gain proportional to how fast the mouse moves":
            "마우스 속도에 비례해 더해지는 배율",
        "Damping": "댐핑",
        "How far you have to pull back towards the PC before control returns. "
        "Raise it if a return arrives while the target pointer still looks "
        "inside its screen":
            "PC 쪽으로 얼마나 끌어야 제어권을 돌려줄지 정합니다. 대상 포인터가 "
            "화면 안에 있는데도 복귀한다면 이 값을 늘리세요",
        "Invert vertical scroll": "세로 스크롤 반전",
        "Vertical scrolling is reversed on the target":
            "대상 기기에서는 세로 스크롤 방향이 반대가 됩니다",
        "Horizontal scrolling is reversed on the target":
            "대상 기기에서는 가로 스크롤 방향이 반대가 됩니다",
        "Invert horizontal scroll": "가로 스크롤 반전",
        "Scroll step up": "위 스크롤 단계",
        "Scroll step down": "아래 스크롤 단계",
        "Lines per wheel detent": "휠 한 칸당 줄 수",
        "Cross at the screen edge": "화면 가장자리에서 넘기기",
        "The toggle key switches this while running":
            "실행 중에는 전환 키로 바꿀 수 있습니다",
        "Edge inset": "가장자리 여유",
        "How close to the PC screen edge the cursor has to get":
            "커서가 PC 화면 가장자리에 얼마나 가까워져야 하는지",
        "Exit clearance": "나갈 때 여유",
        "How far the cursor is placed back inside the PC screen on exit":
            "나갈 때 커서를 PC 화면 안쪽으로 얼마나 옮길지",
        "Enter cooldown": "진입 대기 시간",
        "Seconds before the same edge can be crossed again":
            "같은 가장자리를 다시 넘을 수 있을 때까지의 초",
        "Return by pulling back": "끌어서 복귀",
        "Pulling the pointer towards the PC returns control":
            "포인터를 PC 쪽으로 끌면 제어권을 돌려줍니다",
        "Release control": "제어권 해제",
        "Toggle edge crossing": "가장자리 넘김 전환",
        "Comma separated key names, for example F1":
            "쉼표로 구분한 키 이름, 예: F1",
        "Comma separated key names, for example F2":
            "쉼표로 구분한 키 이름, 예: F2",
        "Forward media keys": "미디어 키 전달",
        "Volume and transport keys go to the target":
            "볼륨과 재생 키를 대상 기기로 보냅니다",
        "Capture mouse buttons": "마우스 버튼 가로채기",
        "Clicks go to the target while it has control":
            "대상 기기가 제어권을 가진 동안 클릭을 보냅니다",
        "Start with Windows": "Windows 시작 시 실행",
        "One value under HKCU Software\\Microsoft\\Windows\\CurrentVersion\\Run, "
        "holding the command line; nothing else is written":
            "HKCU Software\\Microsoft\\Windows\\CurrentVersion\\Run 아래에 값 하나를 "
            "쓰고 내용은 명령줄입니다. 그 밖에는 아무것도 쓰지 않습니다",
        "Start hidden": "시작할 때 숨기기",
        "Open with the notification area icon only, without this window":
            "이 창을 열지 않고 알림 영역 아이콘만 표시합니다",
        "Remap keys": "키 재매핑",
        "Click a field and press the key, or right-click it to pick from the "
        "full list. The PC is unaffected":
            "필드를 클릭하고 키를 누르세요. 오른쪽 클릭하면 전체 목록에서 고를 수 있습니다. "
            "PC 에는 영향이 없습니다",
        "Search keys": "키 검색",
        "to": "→",
        "No keys remapped": "다시 매핑된 키가 없습니다",
        "Press a key": "키를 누르세요",
        "Language": "언어",
        "The language of this window. Changes apply immediately":
            "이 창의 언어입니다. 변경 사항은 즉시 적용됩니다",

        # Status page
        "Mode": "모드",
        "Which side has the keyboard and mouse":
            "키보드와 마우스가 어느 쪽에 있는지",
        "PC cursor": "PC 커서",
        "Fraction of the PC screen": "PC 화면 기준 비율",
        "Target pointer": "대상 포인터",
        "Fraction of the tracked surface": "추적 영역 기준 비율",
        "Travel": "이동량",
        "Motion since the target was entered, negative on the way back":
            "대상 기기 진입 후 이동량, 복귀 방향은 음수",
        "Device link": "기기 연결",
        "pc": "PC",
        "target": "대상 기기",
        "up": "연결됨",
        "down": "끊김",
        "written": "전송",
        "bad": "오류",

        # About
        "Version": "버전",
        "Shared by the window and the background service": "창과 백그라운드 서비스가 함께 사용",
        "Running from": "실행 환경",
        "An executable, or Python": "실행 파일 또는 Python",
        "executable": "실행 파일",
        "The file on disk that holds the current configuration": "현재 구성을 저장하는 디스크 파일",
        "Open settings file": "설정 파일 열기",
        "Reset to defaults": "기본값으로 재설정",

        # Holding the bridge still
        "Pause": "일시 정지",
        "Resume": "계속",
        "Paused": "브리지를 일시 정지했습니다",
        "Running": "브리지를 다시 시작했습니다",
        "Pause log": "로그 일시 정지",
        "Resume log": "로그 계속",

        # Log page
        "Auto-scroll": "자동 스크롤",
        "{count} new lines": "새 로그 {count}줄",
        "Clear": "지우기",

        # Messages
        "Saved": "저장했습니다",
        "Settings reset to defaults": "설정을 기본값으로 되돌렸습니다",
        "Reset every setting to its default value?":
            "모든 설정을 기본값으로 되돌릴까요?",
        "Reloaded {path}": "{path}을(를) 다시 불러왔습니다",
        "Cannot write {path}: {error}": "{path}에 쓸 수 없습니다: {error}",
        "Could not change the startup entry":
            "시작 프로그램 항목을 변경하지 못했습니다",

        # Rejected input
        "{label} must be a number": "{label}은(는) 숫자여야 합니다",
        "{label}: unknown key {name}": "{label}: 알 수 없는 키 {name}",
        "{label}: every row needs a key on both sides":
            "{label}: 각 줄에 양쪽 키를 모두 선택해야 합니다",

        # Settings file
        "settings file not found: {path}":
            "설정 파일을 찾을 수 없습니다: {path}",
        "{path} is not valid JSON: {error}":
            "{path}은(는) 올바른 JSON이 아닙니다: {error}",
        "{path} must contain a JSON object":
            "{path}에는 JSON 개체가 있어야 합니다",
        "{path}: unknown setting(s): {names}":
            "{path}: 알 수 없는 설정: {names}",
        "{path}: {name} must be true or false":
            "{path}: {name}은(는) true 또는 false여야 합니다",
        "{path}: language must be one of {options}":
            "{path}: language은(는) {options} 중 하나여야 합니다",
        "side must be a string, got {kind}":
            "side은(는) 문자열이어야 합니다 ({kind})",
        "side must be one of {options}, got {value}":
            "side은(는) {options} 중 하나여야 합니다 ({value})",
        "{name} must be true or false": "{name}은(는) true 또는 false여야 합니다",
        "{name} must be a number": "{name}은(는) 숫자여야 합니다",
        "{name} cannot be set from the settings file":
            "{name}은(는) 설정 파일에서 지정할 수 없습니다",
        "{name} must be a list of key names":
            "{name}은(는) 키 이름 목록이어야 합니다",
        "remap must be an object of {from: to} key names":
            "remap은(는) {from: to} 형식의 키 이름 개체여야 합니다",
        "remap values must be key names":
            "remap 값은 키 이름이어야 합니다",
    },
}
