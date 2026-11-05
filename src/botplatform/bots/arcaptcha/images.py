"""Telling image types apart from their first bytes."""

IMAGE_TYPES = [
    (b"\x89PNG\r\n\x1a\n", "image/png", "png"),
    (b"\xff\xd8\xff", "image/jpeg", "jpg"),
    (b"GIF8", "image/gif", "gif"),
]


def sniff_image(data: bytes, header: str | None) -> tuple[str, str]:
    """The content type and file extension of image bytes, from their first bytes."""
    for magic, content_type, extension in IMAGE_TYPES:
        if data.startswith(magic):
            return content_type, extension
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    if header and header.startswith("image/"):
        content_type = header.split(";")[0].strip()
        return content_type, content_type.split("/")[1].split("+")[0]
    return "application/octet-stream", "bin"
