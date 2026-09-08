import re


def clean_text(text: str) -> str:
    """只规范空白，不改动报警代码、数字或单位等有业务含义的内容。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
