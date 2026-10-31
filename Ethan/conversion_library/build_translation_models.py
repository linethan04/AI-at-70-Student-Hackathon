"""Download the offline translation models translate.py uses (Argos Translate, OPUS-MT; MIT / CC BY).

English to and from Mandarin, Spanish, Portuguese and Arabic: 8 models, about 900 MB, saved in
data/translation_models/ (git-ignored). Only needed once.

    python Ethan/conversion_library/build_translation_models.py
"""

import io
import json
import shutil
import urllib.request
import zipfile

from translate import MODELS

INDEX = "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json"
PAIRS = [(a, b) for lang in ("zh", "es", "pt", "ar") for a, b in (("en", lang), (lang, "en"))]
# The newest es->en package uses a BPE tokenizer translate.py can't read; version 1.0 uses SentencePiece.
URLS = {("es", "en"): "https://argos-net.com/v1/translate-es_en-1_0.argosmodel"}


def main() -> None:
    index = json.load(urllib.request.urlopen(INDEX))
    MODELS.mkdir(parents=True, exist_ok=True)
    for src, dst in PAIRS:
        target = MODELS / f"{src}_{dst}"
        if (target / "model").is_dir():
            print(f"{src}_{dst}: already here")
            continue
        url = URLS.get((src, dst)) or next(p for p in index if p["from_code"] == src and p["to_code"] == dst)["links"][0]
        print(f"{src}_{dst}: downloading {url} ...")
        archive = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url).read()))
        root = archive.namelist()[0].split("/")[0]
        archive.extractall(MODELS)
        if (MODELS / root) != target:
            shutil.move(MODELS / root, target)


if __name__ == "__main__":
    main()
