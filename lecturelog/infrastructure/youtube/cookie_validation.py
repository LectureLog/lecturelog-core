from __future__ import annotations


class InvalidCookieFormat(ValueError):
    """cookies.txt не похож на формат Netscape."""


def validate_netscape_cookies(content: bytes) -> None:
    """Лёгкая проверка Netscape cookies.txt.

    Принимаем, если есть заголовок `# Netscape HTTP Cookie File` ИЛИ хотя бы
    одна значимая строка с 7 TAB-полями. Полный парсинг не делаем — задача лишь
    отсечь явный мусор (HTML/пустоту), из-за которого yt-dlp молча не сработает.
    """
    text = content.decode("utf-8", errors="ignore")
    if not text.strip():
        raise InvalidCookieFormat("Пустой файл cookies")
    if "# Netscape HTTP Cookie File" in text:
        return
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        if len(line.split("\t")) == 7:
            return
    raise InvalidCookieFormat(
        "Не похоже на cookies.txt (Netscape format). Экспортируй cookies расширением браузера."
    )
