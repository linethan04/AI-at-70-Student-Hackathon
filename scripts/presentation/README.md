# scripts/presentation/

These scripts build [`outputs/presentation/AI_at_70.pptx`](../../outputs/presentation/AI_at_70.pptx).

```bash
python scripts/presentation/render_images.py       # logo + cartoon stills from the video's scenes -> build/ (git-ignored)
python scripts/presentation/make_presentation.py   # the 4 slides -> outputs/presentation/AI_at_70.pptx
```

| File | What it does |
|---|---|
| [`render_images.py`](render_images.py) | Saves the app's logo from `outputs/interface/index.html`, and renders stills of the video's scenes ([`scripts/video/cartoon.html`](../video/cartoon.html)) without captions, so the slides match the video. It needs `scripts/video/build/` from `scripts/video/capture_app.py`. |
| [`make_presentation.py`](make_presentation.py) | Builds the slides with python-pptx, in the app's colors: blue `1C5D84`, teal `38B6A9`, green `1D7A55`, amber `F2B33D`. `AUTHORS` and `STATEMENT` are at the top. Slide 3 uses `outputs/interface/screenshots/5_review.png`. |
