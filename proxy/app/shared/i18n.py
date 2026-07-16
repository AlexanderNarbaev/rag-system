# proxy/app/i18n.py
"""
Multi-language support: language detection, prompt templates, fallback messages.
Language detection uses character-set analysis — no external API required (air-gapped).
Supports: English (EN), Russian (RU), German (DE), French (FR), Chinese (ZH).
"""

import logging

from proxy.app.shared.config import DEFAULT_LANGUAGE, I18N_ENABLED
from proxy.app.shared.config import SUPPORTED_LANGUAGES as CONFIG_SUPPORTED_LANGUAGES

logger = logging.getLogger(__name__)

SUPPORTED_LANGUAGES: set[str] = (
    set(CONFIG_SUPPORTED_LANGUAGES) if isinstance(CONFIG_SUPPORTED_LANGUAGES, list) else {"en", "ru", "de", "fr", "zh"}
)  # noqa: E501

_CJK_RANGES = [
    (0x4E00, 0x9FFF),
    (0x3400, 0x4DBF),
    (0x20000, 0x2A6DF),
    (0x2A700, 0x2B73F),
    (0x2B740, 0x2B81F),
    (0x2B820, 0x2CEAF),
    (0xF900, 0xFAFF),
    (0x2F800, 0x2FA1F),
]

_DE_SPECIAL = "äöüßÄÖÜ"
_FR_SPECIAL = "àâäæçèéêëîïôœùûüÿÀÂÄÆÇÈÉÊËÎÏÔŒÙÛÜŸ"

_DE_COMMON_WORDS = {
    "und",
    "ein",
    "eine",
    "der",
    "die",
    "das",
    "ist",
    "nicht",
    "mit",
    "von",
    "für",
    "auf",
    "ich",
    "wir",
    "sie",
    "was",
    "wie",
    "wo",
    "sind",
    "aus",
    "wird",
    "werden",
    "wurde",
    "wenn",
    "auch",
    "noch",
    "schon",
    "diese",
    "durch",
    "über",
    "nach",
    "vor",
    "bei",
    "ab",
    "seit",
    "dass",
    "oder",
    "aber",
    "sich",
    "einen",
    "dem",
    "den",
    "des",
    "im",
    "am",
    "um",
    "zum",
    "zur",
    "kein",
    "keine",
    "mehr",
    "als",
    "nur",
}

_FR_COMMON_WORDS = {
    "est",
    "vous",
    "dans",
    "avec",
    "pour",
    "sur",
    "comment",
    "quelle",
    "sont",
    "nous",
    "ils",
    "elles",
    "leur",
    "leurs",
    "comme",
    "cette",
    "aussi",
    "tout",
    "tous",
    "toute",
    "toutes",
    "faire",
    "peut",
    "être",
    "avoir",
    "entre",
    "deux",
    "même",
    "autre",
    "autres",
    "sans",
    "mais",
    "donc",
    "encore",
    "toujours",
    "ainsi",
    "alors",
    "peuvent",
    "doit",
    "doivent",
    "depuis",
    "rendre",
    "pendant",
    "avant",
    "après",
    "celui",
    "celle",
    "ceux",
    "celles",
    "certains",
    "certaines",  # noqa: E501
    "votre",
    "notre",
    "sera",
    "seront",
    "étaient",
    "était",
    "moins",
    "plus",
    "très",
    "bien",
    "dire",
    "mettre",
    "nouveau",
    "nouvelle",
    "nouveaux",
    "premier",
    "première",
}


def _count_cjk(text: str) -> int:
    return sum(1 for c in text if any(lo <= ord(c) <= hi for lo, hi in _CJK_RANGES))


def _count_cyrillic(text: str) -> int:
    return sum(1 for c in text if "А" <= c <= "я" or c in "Ёё")


def _count_german_special(text: str) -> int:
    return sum(1 for c in text if c in _DE_SPECIAL)


def _count_french_special(text: str) -> int:
    return sum(1 for c in text if c in _FR_SPECIAL)


def _count_german_words(text: str) -> int:
    words = set(text.lower().split())
    return sum(1 for w in words if w in _DE_COMMON_WORDS)


def _count_french_words(text: str) -> int:
    words = set(text.lower().split())
    return sum(1 for w in words if w in _FR_COMMON_WORDS)


def _count_alpha(text: str) -> int:
    return sum(1 for c in text if c.isalpha())


def detect_language(text: str | None) -> str:
    """Detect language using character set analysis.

    Priority: CJK > Cyrillic > German > French > English.
    Uses special character + common stopword heuristics.
    Falls back to DEFAULT_LANGUAGE on empty/None input.

    Args:
        text: Input query or message text.

    Returns:
        ISO 639-1 language code: en, ru, de, fr, zh.
    """
    if not text:
        return DEFAULT_LANGUAGE

    if not isinstance(text, str):
        return DEFAULT_LANGUAGE

    cjk = _count_cjk(text)
    cyrillic = _count_cyrillic(text)
    de_special = _count_german_special(text)
    fr_special = _count_french_special(text)
    de_words = _count_german_words(text)
    fr_words = _count_french_words(text)
    alpha = _count_alpha(text)

    if cjk > 0 and cjk >= alpha * 0.1:
        return "zh"

    if cyrillic > 0 and cyrillic >= alpha * 0.1:
        return "ru"

    de_score = de_special + de_words * 3
    fr_score = fr_special + fr_words * 3

    if de_score >= 2 and de_score > fr_score:
        return "de"

    if fr_score >= 2 and fr_score > de_score:
        return "fr"

    if de_special > 0 and de_special >= alpha * 0.03:
        return "de"

    if fr_special > 0 and fr_special >= alpha * 0.03:
        return "fr"

    return DEFAULT_LANGUAGE


SYSTEM_PROMPTS: dict[str, str] = {
    "en": (
        "You are a helpful corporate knowledge assistant. "
        "Answer the user's question using only the provided context. "
        "If the context does not contain enough information, say so clearly. "
        "Always cite your sources."
    ),
    "ru": (
        "Вы — корпоративный ассистент по базе знаний. "
        "Отвечайте на вопросы пользователя, используя только предоставленный "
        "контекст. "
        "Если контекст не содержит достаточно информации, чётко скажите об "
        "этом. "
        "Всегда указывайте источники."
    ),
    "de": (
        "Sie sind ein hilfreicher Assistent für die Wissensdatenbank des Unternehmens. "
        "Beantworten Sie die Fragen des Benutzers ausschließlich anhand des bereitgestellten Kontexts. "
        "Wenn der Kontext nicht genügend Informationen enthält, sagen Sie dies deutlich. "
        "Geben Sie immer Ihre Quellen an."
    ),
    "fr": (
        "Vous êtes un assistant de base de connaissances d'entreprise. "
        "Répondez aux questions de l'utilisateur en utilisant "
        "uniquement le contexte fourni. "
        "Si le contexte ne contient pas suffisamment d'informations, "
        "dites-le clairement. "
        "Citez toujours vos sources."
    ),
    "zh": (
        "您是企业知识库助手。"
        "仅使用提供的上下文回答用户的问题。"
        "如果上下文包含的信息不足，请明确说明。"
        "请始终注明信息来源。"
    ),
}

FALLBACK_MESSAGES: dict[str, str] = {
    "en": "I don't have enough information to answer this question. Please try rephrasing or check the source "
    "documents.",
    # noqa: E501
    "ru": "У меня недостаточно информации, чтобы ответить на этот вопрос. Пожалуйста, переформулируйте запрос или "
    "проверьте исходные документы.",
    # noqa: E501
    "de": "Ich habe nicht genügend Informationen, um diese Frage zu beantworten. Bitte versuchen Sie, "
    "die Frage umzuformulieren, oder überprüfen Sie die Quelldokumente.",
    # noqa: E501
    "fr": "Je ne dispose pas d'assez d'informations pour répondre à cette question. Veuillez reformuler ou vérifier "
    "les documents sources.",
    # noqa: E501
    "zh": "我没有足够的信息来回答这个问题。请尝试重新表述您的问题，或查阅源文档。",
}


def get_system_prompt(lang: str | None = None) -> str:
    """Return the system prompt for the given language.

    Falls back to English for unsupported languages or if i18n is disabled.

    Args:
        lang: ISO 639-1 language code or None.

    Returns:
        System prompt string.
    """
    if not I18N_ENABLED:
        return SYSTEM_PROMPTS["en"]
    if lang is None:
        return SYSTEM_PROMPTS["en"]
    return SYSTEM_PROMPTS.get(lang, SYSTEM_PROMPTS["en"])


def get_fallback_message(lang: str | None = None) -> str:
    """Return the language-specific 'I don't know' fallback message.

    Falls back to English for unsupported languages or if i18n is disabled.

    Args:
        lang: ISO 639-1 language code or None.

    Returns:
        Fallback message string.
    """
    if not I18N_ENABLED:
        return FALLBACK_MESSAGES["en"]
    if lang is None:
        return FALLBACK_MESSAGES["en"]
    return FALLBACK_MESSAGES.get(lang, FALLBACK_MESSAGES["en"])
