import re

def clean_text(text):
    """Remove <think>...</think> blocks and whitespace."""
    if not text:
        return ""
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    return cleaned.strip()
