"""Translate the plain-language English summary into Mandarin, Spanish, Portuguese or Arabic (CLAUDE.md: Translation).

The English plain-language version is written and checked first; this translates that version, never the
clinician's original wording. Line by line:
    1. Protect what must not change: medicine names, test names, doses, numbers with units, doctor names and
       phone numbers are swapped for placeholders ("(ZX1)") so the translator can't rename or convert them.
    2. Translate. Offline by default: Argos Translate's OPUS models run locally with CTranslate2 (no API key,
       nothing leaves the computer). With ANTHROPIC_API_KEY, Claude translates instead.
       The offline model gives several candidate translations; the first that keeps every placeholder wins.
    3. Put the protected text back, exactly as written in English.
    4. Back-translate to English with the offline model and compare with the English line. A line whose
       meaning may have drifted (words dropped or changed, a number missing) is flagged for the clinician.
Every translated line is "translated on our own" (no official translation is used yet) and the output is
marked "translation not verified by a speaker of this language" until a qualified reviewer confirms it.

    python tools/translation/translate.py es "Take 1 pill (5 mg) each day."
    python scripts/setup/build_translation_models.py     # first time: downloads the models
"""

import os
import re
import sys
from functools import lru_cache
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODELS = HERE / "models"  # downloaded by scripts/setup/build_translation_models.py (git-ignored)

LANGUAGES = {"en": "English", "zh": "Mandarin (Simplified Chinese)", "es": "Spanish", "pt": "Portuguese", "ar": "Arabic"}
DIRECTION = {"ar": "rtl"}
SPEECH = {"en": "en-US", "zh": "zh-CN", "es": "es-US", "pt": "pt-BR", "ar": "ar-SA"}  # voices for the phone call
CANDIDATES = 6           # translations to try per line until one keeps every placeholder
DRIFT_SIMILARITY = 0.5   # back-translation must share at least half its content words with the English
CLAUDE_MODEL = "claude-opus-5-5"
OFFLINE_ENGINE = "Argos Translate (OPUS-MT models, run offline)"
NOT_VERIFIED = "translation not verified by a speaker of this language"

DOSE = re.compile(r"\b\d+(?:[.,/]\d+)*\s?(?:mg|mcg|g|ml|mL|IU|international units|units?|L|lb)\b")  # written doses
# (spoken ones, "5 milligrams" in the phone script, are translated so they're read in the listener's language)
PHONE = re.compile(r"\+?\d[\d ()-]{6,}\d")
DOCTOR = re.compile(r"\b(?:Dr|Doctor)\.? [A-Z][A-Za-z-]+")
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "at", "your", "you", "is", "are", "be", "it",
        "with", "this", "that", "if", "by", "as", "do", "will", "have", "has", "each", "from", "into", "get"}

# Fixed page words, translated on our own (model knowledge; flagged for review like every other line).
LABELS = {
    "en": {"title": "Your visit summary", "patient": "Patient", "date": "Visit date", "visit": "Your visit",
           "medicines": "Your medicines", "next": "What to do next", "how": "How to take",
           "New": "New", "Higher dose": "Higher dose", "Lower dose": "Lower dose", "New dose": "New dose",
           "Stopped": "Stopped", "questions": "Questions? Call your doctor's office", "reviewed": "Reviewed by",
           "not_verified": "", "hello": "Dear {name},"},
    "es": {"title": "Resumen de su visita", "patient": "Paciente", "date": "Fecha de la visita", "visit": "Su visita",
           "medicines": "Sus medicamentos", "next": "Qué hacer ahora", "how": "Cómo tomarlo",
           "New": "Nuevo", "Higher dose": "Dosis más alta", "Lower dose": "Dosis más baja", "New dose": "Dosis nueva",
           "Stopped": "Suspendido", "questions": "¿Preguntas? Llame al consultorio de su médico",
           "reviewed": "Revisado por", "not_verified": "Traducción no verificada por un hablante de este idioma.",
           "hello": "Hola, {name}:"},
    "pt": {"title": "Resumo da sua consulta", "patient": "Paciente", "date": "Data da consulta", "visit": "Sua consulta",
           "medicines": "Seus remédios", "next": "O que fazer agora", "how": "Como tomar",
           "New": "Novo", "Higher dose": "Dose maior", "Lower dose": "Dose menor", "New dose": "Dose nova",
           "Stopped": "Suspenso", "questions": "Dúvidas? Ligue para o consultório do seu médico",
           "reviewed": "Revisado por", "not_verified": "Tradução não verificada por um falante deste idioma.",
           "hello": "Olá, {name}:"},
    "zh": {"title": "您的就诊总结", "patient": "患者", "date": "就诊日期", "visit": "您的就诊", "medicines": "您的药物",
           "next": "接下来要做什么", "how": "服用方法", "New": "新药", "Higher dose": "剂量增加", "Lower dose": "剂量减少",
           "New dose": "新剂量", "Stopped": "已停用", "questions": "有问题？请致电您的医生诊所", "reviewed": "审核人",
           "not_verified": "此翻译尚未经过该语言使用者的核实。", "hello": "{name}，您好："},
    "ar": {"title": "ملخص زيارتك", "patient": "المريض", "date": "تاريخ الزيارة", "visit": "زيارتك", "medicines": "أدويتك",
           "next": "ماذا تفعل بعد ذلك", "how": "طريقة الاستخدام", "New": "جديد", "Higher dose": "جرعة أعلى",
           "Lower dose": "جرعة أقل", "New dose": "جرعة جديدة", "Stopped": "تم إيقافه",
           "questions": "هل لديك أسئلة؟ اتصل بعيادة طبيبك", "reviewed": "تمت المراجعة بواسطة",
           "not_verified": "لم يتم التحقق من هذه الترجمة من قبل متحدث بهذه اللغة.", "hello": "مرحبًا {name}،"},
}


def available(lang: str) -> bool:
    return lang == "en" or ((MODELS / f"en_{lang}" / "model").is_dir() and (MODELS / f"{lang}_en" / "model").is_dir())


@lru_cache(maxsize=8)
def model(pair: str):
    import ctranslate2
    import sentencepiece as spm
    folder = MODELS / pair
    if not (folder / "model").is_dir():
        raise RuntimeError(f"No offline model for {pair}: run build_translation_models.py")
    tokenizer = next(f for f in (folder / "sentencepiece.model", folder / "bpe.model") if f.exists())
    return ctranslate2.Translator(str(folder / "model"), inter_threads=2), spm.SentencePieceProcessor(model_file=str(tokenizer))


def run(pair: str, lines: list[str], candidates: int = 1) -> list[list[str]]:
    """Each line's translations, best first."""
    if not lines:
        return []
    translator, sp = model(pair)
    results = translator.translate_batch([sp.encode(l, out_type=str) for l in lines], beam_size=max(4, candidates),
                                         num_hypotheses=candidates)
    tidy = lambda t: re.sub(r"\s+", " ", sp.decode(t).replace("▁", " ")).strip()
    return [[tidy(h) for h in r.hypotheses] for r in results]


# Fixed everyday wording for words the summary uses again and again, so a page says them the same way every time
# (the model alone mixes "pastilla", "comprimido" and "píldora", or "usted" and "tú"). Our own wording (model
# knowledge), flagged like every other translated line. (English pattern, wording in the target language.)
GLOSSARY = {
    "es": [(r"\bBlood sugar medicine\b", "Medicina para el azúcar en la sangre"),
           (r"\bBlood pressure medicine\b", "Medicina para la presión arterial"),
           (r"\bCholesterol medicine\b", "Medicina para el colesterol"),
           (r"\bPain medicine\b", "Medicina para el dolor"),
           (r"\bTake 1 pill\b", "Tome 1 pastilla"),
           (r"\bthe swelling\b", "la hinchazón"), (r"\bswelling\b", "hinchazón")],
}
WHOLE_LINES = {"es": {"Raise your legs when you sit.": "Suba las piernas cuando se siente."}}

TOKENS = ("ZX{}", "VAR{}", "#{}")  # placeholder styles, tried in turn (the Arabic model garbles some)
SCRIPT = {"zh": r"[\u4e00-\u9fff]", "ar": r"[\u0600-\u06ff]", "es": r"[a-záéíóúñ]", "pt": r"[a-záéíóúãõç]"}
ONE = {"zh": "一", "ar": "واحد", "es": r"\bun[oa]?\b", "pt": r"\bu(?:m|ma)\b"}  # "1 pill" may become "one pill"


def protect(line: str, keep: set[str], style: str = TOKENS[0], lang: str = "") -> tuple[str, dict[str, str]]:
    """'Take 1 pill (5 mg) of Amlodipine' -> 'Take 1 pill (ZX1) of ZX2', {'ZX1': '5 mg', 'ZX2': 'Amlodipine'}.
    Glossary words for `lang` are swapped too, and come back in the target language."""
    spans, fixed = [], {}
    for pattern, target in GLOSSARY.get(lang, []):
        for m in re.finditer(pattern, line):
            spans.append(m.span())
            fixed[m.span()] = target
    for name in sorted(keep, key=len, reverse=True):
        spans += [m.span() for m in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", line)]
    for pattern in (DOSE, PHONE, DOCTOR):
        spans += [m.span() for m in pattern.finditer(line)]
    chosen = []
    for start, end in sorted(spans, key=lambda s: (s[0], -(s[1] - s[0]))):
        if not chosen or start >= chosen[-1][1]:
            chosen.append((start, end))
    out, slots, pos = [], {}, 0
    for i, (start, end) in enumerate(chosen, 1):
        token = style.format(i)
        slots[token] = fixed.get((start, end), line[start:end])
        out.append(line[pos:start] + token)
        pos = end
    return "".join(out) + line[pos:], slots


def restore(text: str, slots: dict[str, str]) -> str:
    for token in sorted(slots, key=len, reverse=True):
        text = text.replace(token, slots[token])
    return text


def usable(candidate: str, slots: dict[str, str], lang: str, english: str) -> bool:
    """Keeps every placeholder and is really in the target language (not the English copied back)."""
    words = re.sub(r"ZX\d+|VAR\d+|#\d+", "", candidate)
    return all(t in candidate for t in slots) and bool(re.search(SCRIPT[lang], words.lower())) and candidate != english


NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7", "eight": "8",
                "nine": "9", "ten": "10", "tablet": "pill", "tablets": "pills", "daily": "day", "every": "each"}


def content(text: str) -> set[str]:
    words = [NUMBER_WORDS.get(w, w) for w in re.findall(r"[a-z]+|\d+", text.lower())]
    return {w for w in words if w not in STOP and (len(w) > 2 or w.isdigit())}


def similarity(a: str, b: str) -> float:
    x, y = content(a), content(b)
    return len(x & y) / max(1, len(x | y)) if x or y else 1.0


def translate_lines(lines: list[str], lang: str, keep: set[str] = frozenset(), spoken: bool = False) -> list[dict]:
    """[{"en", "text", "back", "flags"}] for each English line. spoken: a script read aloud, where "five
    milligrams" in the listener's own number words is fine (only written numbers are checked)."""
    if lang == "en":
        return [{"en": l, "text": l, "back": "", "flags": []} for l in lines]
    chosen: list[tuple[str, dict] | None] = [None] * len(lines)
    for i, line in enumerate(lines):
        if line in WHOLE_LINES.get(lang, {}):
            chosen[i] = (WHOLE_LINES[lang][line], {})
        else:
            p, slots = protect(line, set(keep), lang=lang)
            if slots and not re.sub(r"ZX\d+|[\W\d]", "", p):  # nothing left to translate ("Pain medicine")
                chosen[i] = (p, slots)
    if os.environ.get("ANTHROPIC_API_KEY"):
        protected = [protect(l, set(keep), lang=lang) for l in lines]
        forward = claude_translate([p for p, _ in protected], lang) or []
        for i, (f, (p, slots)) in enumerate(zip(forward, protected)):
            if chosen[i] is None and usable(f, slots, lang, p):
                chosen[i] = (f, slots)
    for style in TOKENS:  # offline: each placeholder style in turn, for the lines still without a translation
        todo = [i for i, c in enumerate(chosen) if c is None]
        if not todo:
            break
        protected = {i: protect(lines[i], set(keep), style, lang) for i in todo}
        for i, options in zip(todo, run(f"en_{lang}", [protected[i][0] for i in todo], CANDIDATES)):
            slots = protected[i][1]
            chosen[i] = next(((o, slots) for o in options if usable(o, slots, lang, protected[i][0])), None)
    out = []
    for english, choice in zip(lines, chosen):
        flags = ["translated on our own (no official translation used)"]
        if choice is None:  # every style lost a placeholder: translate the real words and ask the clinician to check
            best = run(f"en_{lang}", [english])[0][0]
            flags.append("a medicine name, dose or number may have changed in translation: check it")
            text, kept, slots = best, best, {}
        else:
            text = restore(choice[0], choice[1])
        out.append({"en": english, "text": text, "flags": flags})
    backs = run(f"{lang}_en", [o["text"] for o in out])  # the text as the patient will read it
    for o, back in zip(out, backs):
        o["back"] = back[0]
        if similarity(o["en"], o["back"]) < DRIFT_SIMILARITY:
            o["flags"].append("back-translation differs from the English: the meaning may have changed")
        missing = set() if spoken else set(re.findall(r"\d+", o["en"])) - set(re.findall(r"\d+", o["text"]))
        if "1" in missing and re.search(ONE[lang], o["text"].lower()):
            missing.discard("1")  # "1 pill" -> "una pastilla"
        if missing:
            o["flags"].append("number missing in the translation: " + ", ".join(sorted(missing)))
    return out


CLAUDE_PROMPT = """Translate each line from English into {language} for an older adult patient and their family. \
Plain, warm, respectful words at about a 5th-grade reading level; short sentences; no idioms or slang; formal \
"you". Keep every token like ZX1, ZX2 exactly as written (they stand for medicine names, doses and numbers). \
Do not add, drop or soften anything. Return the same number of lines in the same order."""


def claude_translate(lines: list[str], lang: str) -> list[str] | None:
    """Claude's translation (with ANTHROPIC_API_KEY); None if it fails, so the offline model is used."""
    try:
        import anthropic
        from pydantic import BaseModel

        class Lines(BaseModel):
            lines: list[str]

        response = anthropic.Anthropic().beta.messages.parse(
            model=CLAUDE_MODEL, max_tokens=4000, output_config={"effort": "high"}, system=CLAUDE_PROMPT.format(language=LANGUAGES[lang]),
            messages=[{"role": "user", "content": "\n".join(f"{i + 1}. {l}" for i, l in enumerate(lines))}],
            output_format=Lines)
        got = [re.sub(r"^\d+\.\s*", "", l) for l in response.parsed_output.lines]
        return got if len(got) == len(lines) else None
    except Exception:
        return None


def engine() -> str:
    return f"Claude ({CLAUDE_MODEL}); back-translation check: {OFFLINE_ENGINE}" if os.environ.get("ANTHROPIC_API_KEY") \
        else OFFLINE_ENGINE


if __name__ == "__main__":
    for row in translate_lines(sys.argv[2:] or [sys.stdin.read()], sys.argv[1]):
        print(row["text"], "\n  back:", row["back"], *(f"\n  ! {f}" for f in row["flags"][1:]))
