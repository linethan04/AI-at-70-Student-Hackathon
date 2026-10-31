# scripts/video/

These files build the demo video, [`outputs/video/ai_at_70_demo.mp4`](../../outputs/video/ai_at_70_demo.mp4), from the **real app**. The app clips in it are screen recordings of the actual page going through Maria's visit.

## The made-up visit (one story throughout)

All three files describe the same made-up visit: Maria Rodriguez, 78, her daughter Sofia, and Dr. Lee.

| File | What it is |
|---|---|
| [`maria_checkin.json`](maria_checkin.json) | Maria's check-in, as exported by the questionnaire. Sofia has consent to receive the summary. |
| [`maria_conversation.txt`](maria_conversation.txt) | the visit conversation |
| [`maria_note.txt`](maria_note.txt) | Dr. Lee's typed note |

These files are also the quickest way to try the app by hand (see the main [README](../../README.md#quick-start)).

## Build the video

You need macOS for the `say` voices, Google Chrome, the translation models and the voices (see [`../setup/`](../setup/)).

```bash
python scripts/video/make_visit_audio.py   # voices the conversation -> maria_visit.wav (git-ignored)
python scripts/run_ai_at_70.py &           # the app must be running
python scripts/video/capture_app.py        # records the app going through the visit -> build/ (git-ignored)
python scripts/video/make_video.py         # renders the scenes, adds narration -> outputs/video/ai_at_70_demo.mp4
```

| File | What it does |
|---|---|
| [`make_visit_audio.py`](make_visit_audio.py) | reads `maria_conversation.txt` aloud in two voices; the recording step plays it into the app through Chrome's fake microphone |
| [`capture_app.py`](capture_app.py) | drives the app in Chrome, saving a screen recording plus timing marks, the English and Spanish printouts, the family email, the phone script and the logo |
| [`cartoon.html`](cartoon.html) | the animated scenes (modern flat style, ordinary human proportions); open `cartoon.html?scene=turn` to preview one |
| [`make_video.py`](make_video.py) | the story and narration (`STORY`): renders each scene frame by frame, cuts the app clips into a browser window, adds the Kokoro voiceover and the phone voice, crossfades the scenes, and writes the MP4 |

The shot list, the narration word for word and the pacing rules are in [`outputs/video/VIDEO_PROMPT.md`](../../outputs/video/VIDEO_PROMPT.md).
