[Documentation](index.md) · [简体中文](../zh/images.md)

# Image input

Set `ENABLE_VISION=True` (default) when the main model supports image input. Images are saved under `FEISHU_RECEIVED_DIR` and referenced from conversation checkpoints; their original bytes are encoded as Base64 Data URLs when making model requests. JPEG, PNG, GIF and WebP are validated by actual content. The application accepts up to 8 images and 20 MiB of image data per request, with a 10 MiB per-image limit. Plain text requests keep the existing behavior.

```text
/image "/path/first image.png" /path/second.jpg -- Compare these images
/image img-<id> img-<id> -- Explain the difference
/image all -- Describe the pending images
/upload "/path/image.png"
```

`/image` selects images for the current turn; use `--` before the question. `/upload` stores files and returns their paths/IDs. On Feishu, sending an image saves it and returns an ID. Quote the image message and reply with a question, use `/image` with IDs, or send text and images together in a rich-text message. An ordinary follow-up text keeps the existing attachment-path behavior; pending images are selected explicitly for vision. `/upload` marks all pending images as storage-only; `/upload <id...>` marks just those images. Pending selections expire according to `FEISHU_PENDING_FILE_TTL_SECONDS`; saved history references remain usable. Image commands accept local paths only from the terminal.

Set `LLM_FALLBACK_ENABLE_VISION=True` only if the backup model also supports images. Image requests require a vision-capable fallback. Turning vision off sends textual image references in place of image data. Keep referenced files available; changed, missing or over-budget images produce an explicit error. Context summarization uses the same image adapter. For Workflow `llm`/`subagent` nodes, set `config.image_ids` or `config.image_ids_field` (a list state field) to explicitly pass image IDs from the originating conversation. Image generation is a separate future capability; existing file-sending tools remain available.

The existing shared main conversation is retained: terminal and Feishu requests can continue the same image conversation. Historical images use their stored attachment scope; selecting new attachments still checks the current origin. Use distinct `session_key` values when separate conversations are needed.
