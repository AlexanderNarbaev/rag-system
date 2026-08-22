# Model cache staging directory

`etl/Dockerfile.etl` copies this directory into the image at `/root/.cache/`
(see the `MODEL_CACHE_DIR` build arg). Populate it before building for
air-gapped environments:

```bash
# sentence-transformers / Hugging Face models
cp -r ~/.cache/huggingface etl/model_cache/huggingface

# spaCy models (or install them into site-packages instead)
cp -r ~/.local/share/spacy etl/model_cache/spacy
```

Keep real model files out of git — this directory is gitignored except for
this README.
