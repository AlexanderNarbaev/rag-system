# ruff: noqa: E501, SIM117, E402, N817, SIM105
"""Tests for proxy/app/i18n.py — language detection and prompt templates."""

from proxy.app.shared.i18n import (
    FALLBACK_MESSAGES,
    SUPPORTED_LANGUAGES,
    SYSTEM_PROMPTS,
    detect_language,
    get_fallback_message,
    get_system_prompt,
)


class TestDetectLanguage:
    """Character-set based language detection."""

    def test_detects_english_default(self):
        assert detect_language("How do I set up CI/CD in GitLab?") == "en"

    def test_detects_russian_cyrillic(self):
        assert detect_language("Как настроить CI/CD пайплайн в GitLab?") == "ru"

    def test_detects_german_umlaut(self):
        assert detect_language("Wie richte ich eine CI/CD-Pipeline in GitLab ein?") == "de"

    def test_detects_german_eszett(self):
        assert detect_language("Die Straße ist lang.") == "de"

    def test_detects_french_accents(self):
        assert detect_language("Comment configurer un pipeline CI/CD dans GitLab?") == "fr"

    def test_detects_chinese_cjk(self):
        assert detect_language("如何在GitLab中设置CI/CD管道？") == "zh"

    def test_detects_chinese_traditional(self):
        assert detect_language("如何在GitLab中設置CI/CD管道？") == "zh"

    def test_empty_text_returns_en(self):
        assert detect_language("") == "en"

    def test_none_text_returns_en(self):
        assert detect_language(None) == "en"

    def test_mixed_cyrillic_and_latin_prefers_cyrillic(self):
        assert detect_language("Как настроить GitLab CI/CD pipeline?") == "ru"

    def test_mixed_cjk_and_latin_prefers_cjk(self):
        assert detect_language("GitLab CI/CD 配置 pipeline") == "zh"

    def test_mixed_german_and_english_prefers_german(self):
        assert detect_language("Wie configure ich das CI/CD pipeline?") == "de"

    def test_mixed_french_and_english_prefers_french(self):
        assert detect_language("Comment configurer le CI/CD pipeline?") == "fr"

    def test_long_multilingual_text_returns_majority(self):
        long_de = (
            "Dies ist ein sehr langer deutscher Text mit vielen Wörtern über CI/CD-Pipelines und deren "
            "Konfiguration in verschiedenen Umgebungen."
        )
        assert detect_language(long_de) == "de"

    def test_long_french_text(self):
        long_fr = (
            "Ceci est un très long texte français avec de nombreux mots sur les pipelines CI/CD et leur "
            "configuration dans différents environnements."
        )
        assert detect_language(long_fr) == "fr"


class TestSupportedLanguages:
    """Tests for SUPPORTED_LANGUAGES set."""

    def test_five_languages_supported(self):
        assert len(SUPPORTED_LANGUAGES) == 5

    def test_contains_expected_languages(self):
        assert {"en", "ru", "de", "fr", "zh"} == SUPPORTED_LANGUAGES


class TestGetSystemPrompt:
    """Tests for system prompt retrieval."""

    def test_returns_prompt_for_valid_lang(self):
        prompt = get_system_prompt("de")
        assert isinstance(prompt, str)
        assert len(prompt) > 10

    def test_returns_en_for_unknown_lang(self):
        prompt = get_system_prompt("jp")
        assert prompt == SYSTEM_PROMPTS["en"]

    def test_returns_en_for_none(self):
        prompt = get_system_prompt(None)
        assert prompt == SYSTEM_PROMPTS["en"]

    def test_all_supported_langs_have_prompt(self):
        for lang in SUPPORTED_LANGUAGES:
            prompt = get_system_prompt(lang)
            assert isinstance(prompt, str)
            assert len(prompt) > 10

    def test_german_prompt_contains_german_text(self):
        prompt = SYSTEM_PROMPTS["de"]
        assert "Wissensdatenbank" in prompt or "Assistent" in prompt or "Sie" in prompt

    def test_french_prompt_contains_french_text(self):
        prompt = SYSTEM_PROMPTS["fr"]
        assert "base" in prompt.lower() or "assistant" in prompt.lower()

    def test_chinese_prompt_contains_chinese_text(self):
        prompt = SYSTEM_PROMPTS["zh"]
        assert any(ord(c) > 0x4E00 for c in prompt)


class TestGetFallbackMessage:
    """Tests for language-specific fallback messages."""

    def test_returns_message_for_valid_lang(self):
        msg = get_fallback_message("de")
        assert isinstance(msg, str)
        assert len(msg) > 5

    def test_returns_en_for_unknown_lang(self):
        msg = get_fallback_message("jp")
        assert msg == FALLBACK_MESSAGES["en"]

    def test_returns_en_for_none(self):
        msg = get_fallback_message(None)
        assert msg == FALLBACK_MESSAGES["en"]

    def test_all_supported_langs_have_fallback(self):
        for lang in SUPPORTED_LANGUAGES:
            msg = get_fallback_message(lang)
            assert isinstance(msg, str)
            assert len(msg) > 5

    def test_german_fallback_contains_german(self):
        assert "nicht" in FALLBACK_MESSAGES["de"].lower()

    def test_french_fallback_contains_french(self):
        assert "pas" in FALLBACK_MESSAGES["fr"].lower() or "répondre" in FALLBACK_MESSAGES["fr"].lower()

    def test_chinese_fallback_contains_chinese(self):
        assert any(ord(c) > 0x4E00 for c in FALLBACK_MESSAGES["zh"])
