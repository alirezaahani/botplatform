import pytest

from botplatform.bots.arcaptcha.images import sniff_image

PNG = b"\x89PNG\r\n\x1a\n" + b"rest"
JPEG = b"\xff\xd8\xff\xe0" + b"rest"
GIF = b"GIF89a" + b"rest"
WEBP = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"rest"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (PNG, ("image/png", "png")),
        (JPEG, ("image/jpeg", "jpg")),
        (GIF, ("image/gif", "gif")),
        (WEBP, ("image/webp", "webp")),
    ],
)
def test_known_magic_bytes_decide_the_type(data, expected):
    assert sniff_image(data, None) == expected


def test_magic_bytes_win_over_a_conflicting_header():
    assert sniff_image(PNG, "image/jpeg") == ("image/png", "png")


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("image/avif", ("image/avif", "avif")),
        ("image/svg+xml", ("image/svg+xml", "svg")),
        ("image/png; charset=binary", ("image/png", "png")),
    ],
)
def test_unknown_bytes_fall_back_to_an_image_header(header, expected):
    assert sniff_image(b"<svg/>", header) == expected


@pytest.mark.parametrize("header", [None, "", "text/html", "application/json"])
def test_unknown_bytes_without_an_image_header_are_octet_stream(header):
    assert sniff_image(b"nothing known", header) == ("application/octet-stream", "bin")


def test_empty_data_is_octet_stream():
    assert sniff_image(b"", None) == ("application/octet-stream", "bin")


def test_riff_without_webp_marker_is_not_webp():
    data = b"RIFF" + b"\x00\x00\x00\x00" + b"WAVE"
    assert sniff_image(data, None) == ("application/octet-stream", "bin")
