# tools/voice/

[`voices.py`](voices.py) makes the **phone-call voice**: natural neural text-to-speech that runs on this computer, with no API key and nothing sent out. It reads each line a little slower than everyday speech, for older listeners.

| Language | Voice |
|---|---|
| English | Kokoro v1.0, `af_heart` (kokoro-onnx) |
| Spanish | Kokoro v1.0, `ef_dora` |
| Portuguese | Kokoro v1.0, `pf_dora` |
| Mandarin | Kokoro v1.0 through sherpa-onnx with its Chinese lexicon, `zf_xiaoxiao` |
| Arabic | Piper, `ar_JO-kareem-medium` |

## Run

```bash
python scripts/setup/build_voices.py                                          # once: ~770 MB into models/ (git-ignored)
python tools/voice/voices.py en "Take 1 pill, 5 milligrams, each day." out.wav   # one line to a WAV file
```

In the app, the **Phone call** tab plays the script line by line, preparing the next line while one plays. The demo video uses the same voices: `af_bella` for the narrator and `af_heart` for the call.
