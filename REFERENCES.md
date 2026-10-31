# References

This page lists every source, dataset, model and library AI at 70 uses. It also says what each one is used for.

Wording that comes from model knowledge rather than a standard source is labeled in the app as "no standard source" (or "translated on our own"). Examples are the phrase table in `tools/plain_language/data/simple_words.json` and the Spanish glossary in `tools/translation/translate.py`. That wording is flagged for the clinician, as [CLAUDE.md](CLAUDE.md) requires.

## Plain-language word choices (in priority order)

1. **CDC. *Everyday Words for Public Health Communication*.** Centers for Disease Control and Prevention, 2016. https://www.cdc.gov/other/pdf/EverydayWordsForPublicHealthCommunication.pdf
   Plain replacements for clinical words. Built into `tools/plain_language/data/lay_dictionary.json` by `scripts/setup/build_dictionaries.py`.
2. **MedlinePlus health topics.** U.S. National Library of Medicine (NLM). https://medlineplus.gov/ (XML: https://medlineplus.gov/xml.html)
   Consumer names for conditions ("hypertension" → "high blood pressure").
3. **MedlinePlus lab tests.** NLM. https://medlineplus.gov/lab-tests/
   Plain descriptions of tests (BMP, HbA1c, microalbumin).
4. **MedlinePlus drug information,** via **MedlinePlus Connect.** NLM. https://connect.medlineplus.gov/
   What each medicine is for ("This medicine treats high blood pressure"). Cached in `tools/plain_language/data/drug_info.json` by `tools/plain_language/drug_info.py`.
5. **Federal Plain Language Guidelines** and word list. plainlanguage.gov (General Services Administration). https://www.plainlanguage.gov/guidelines/ (archived copy of December 2024 via the Internet Archive, https://web.archive.org/)
   Everyday words for non-medical terms.
6. **Wikipedia, *List of medical abbreviations*** (CC BY-SA 4.0). https://en.wikipedia.org/wiki/List_of_medical_abbreviations
   Used only to expand abbreviations (BID, qhs, PRN), never as plain wording.

## Medical vocabularies (term checks)

- **RxNorm** and **RxNav REST API.** NLM. https://rxnav.nlm.nih.gov/REST
  Drug names (generic and brand) and RxNorm IDs. Used to keep every medicine name exactly as written, and to spot misheard drug names in transcripts.
- **RxClass.** NLM, via RxNav. Drug classes ("diuretics" → water pill).
- **NLM Clinical Table Search Service.** https://clinicaltables.nlm.nih.gov/api
  ICD-10-CM diagnoses, consumer Conditions, LOINC lab names and HCPCS procedures.
- **Medical spelling word list** (OpenMedSpel-based, about 98,000 words). https://github.com/glutanimate/wordlist-medicalterms-en
  Detects medical jargon and corrects misheard terms offline.

## Reading level (who knows which words)

- **Brysbaert, M., & Biemiller, A. (2017).** Test-based age-of-acquisition norms for 44 thousand English word meanings. *Behavior Research Methods*, 49, 1520–1523. Data: https://osf.io/kz2px
  Built on Dale & O'Rourke's *Living Word Vocabulary* (1981). Tells the reader check (`tools/plain_language/reader.py`) the school grade by which most students know each word.
- **Brysbaert, M., Mandera, P., McCormick, S. F., & Keuleers, E. (2019).** Word prevalence norms for 62,000 English lemmas. *Behavior Research Methods*, 51, 467–479. Data: https://osf.io/nbu9e
  Tells the check which words 99% of adults know.
- **Kuperman, V., Stadthagen-Gonzalez, H., & Brysbaert, M. (2012).** Age-of-acquisition ratings for 30,000 English words. *Behavior Research Methods*, 44, 978–990. Included in the OSF data above.
- **McLaughlin, G. H. (1969).** SMOG grading: a new readability formula. *Journal of Reading*, 12(8), 639–646. Reported for reference (via `textstat`).
- **Fernández Huerta, J. (1959)** readability formula and **INFLESZ** (Barrio-Cantalejo et al., 2008). The recommended readability scales for Spanish, named in CLAUDE.md.
- **wordfreq** (Speer, R.). Word frequency data. https://github.com/rspeer/wordfreq

## Medication instructions

- **USP General Chapter <17> Prescription Container Labeling.** United States Pharmacopeia. The style for medicine action lines ("Take 1 pill (5 mg) each day").
- **Universal Medication Schedule** (morning, noon, evening, bedtime). Wolf, M. S., et al. (2011). *Archives of Internal Medicine* 171(4). Used only when the note supports it.
- **National Institute on Aging (NIA),** health information for older adults. https://www.nia.nih.gov/health. A tone and format guide for older readers.

## Translation

- **Argos Translate** (MIT) and its **OPUS-MT** models (Tiedemann & Thottingal, 2020, *OPUS-MT: Building open translation services for the World*, EAMT; CC BY 4.0). Package index: https://github.com/argosopentech/argospm-index
  Offline English ↔ Spanish, Mandarin, Portuguese and Arabic, plus every back-translation check.
- **CTranslate2** (OpenNMT, MIT) and **SentencePiece** (Google, Apache-2.0). Run the translation models on this computer.
- **Claude** (Anthropic). When `ANTHROPIC_API_KEY` is set, translates and writes the plain-language summary under the same rules.

## Speech: transcription, speakers and voices

- **Whisper** (Radford et al., 2022, *Robust Speech Recognition via Large-Scale Weak Supervision*, OpenAI, MIT), run with **faster-whisper** (SYSTRAN, MIT). Offline transcription.
- **ElevenLabs Scribe** (`scribe_v2`). Optional cloud transcription with speaker labels, when `ELEVENLABS_API_KEY` is set.
- **NVIDIA TitaNet** speaker-embedding model (NeMo, CC BY 4.0), run with **sherpa-onnx** (k2-fsa, Apache-2.0). Tells speakers apart offline.
- **Kokoro-82M v1.0** (hexgrad, Apache-2.0), run with **kokoro-onnx** (https://github.com/thewh1teagle/kokoro-onnx). Phone-call voices for English (af_heart), Spanish (ef_dora) and Portuguese (pf_dora), and the video narrator (af_bella). Mandarin (zf_xiaoxiao) runs through **sherpa-onnx** (https://github.com/k2-fsa/sherpa-onnx).
- **Piper** (Rhasspy / Open Home Foundation, MIT), voice **ar_JO-kareem-medium**. The Arabic phone-call voice.
- **Apple Vision** text recognition, via **ocrmac**. Reads a photo of a written note (macOS).

## Software

- **Flask** (web servers), **Jinja2** (summary templates), **httpx**, **pydantic**, **python-dotenv**, **pypdf** (PDF notes), **textstat**, **rapidfuzz** (fuzzy term matching), **numpy**, **soundfile**, **sounddevice**, **openpyxl**.
- **Anthropic Python SDK.** Claude steps (`claude-opus-5-5`).
- **Playwright** (Microsoft, Apache-2.0) and **Google Chrome.** Record the real app for the demo video, and render the animated scenes.
- **FFmpeg** (via **imageio-ffmpeg**). Video and audio encoding.
- **Fonts:** Nunito and Nunito Sans (the app); Plus Jakarta Sans (the video). Both from Google Fonts, under the SIL Open Font License.

## Demo video structure

These were used to shape the 60–90-second ad: hook, problem, turn, how it works, payoff and closing line. They also set the pacing of about 140–160 spoken words per minute.

- Typecast, *Explainer Video Script Template With Voiceover Timing.* https://typecast.ai/learn/?p=14931
- Typecast, *Product Demo Script: 60-Second Template and Example.* https://typecast.ai/learn/?p=14846
- Biteable, *Explainer video script template.* https://biteable.com/blog/explainer-video-script-template/
- Levitate Media, *How to write an explainer video script.* https://levitatemedia.com/learn/how-to-write-an-explainer-video-script
- ContentBeta, *Healthcare testimonial videos.* https://www.contentbeta.com/blog/healthcare-testimonial-videos/
- B2W, *10 Best Healthcare Ad Examples That Built Patient Trust and Loyalty.* https://www.b2w.tv/blog/non-salesy-animated-healthcare-commercials
- Beast of Traal, *Whatever it takes… in a heartbeat* (Macmillan Cancer Support ad review). https://beastoftraal.com/2021/02/10/whatever-it-takes-in-a-heartbeat/

## Test data used during development (not in the repository)

These public datasets were used to test the transcription and the plain-language rewriting while building. The test scripts and downloaded copies were removed when the repository was cleaned up.

- **PriMock57:** mock primary-care consultations with human transcripts and notes (Papadopoulos Korfiatis et al., 2022, *PriMock57: A Dataset Of Primary Care Mock Consultations*, ACL; CC BY 4.0). https://github.com/babylonhealth/primock57
- **MTSamples:** sample medical transcription reports (general medicine and discharge summaries). https://mtsamples.com/
