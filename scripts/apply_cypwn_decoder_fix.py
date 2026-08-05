#!/usr/bin/env python3
from pathlib import Path

script_path = Path("scripts/sync_deb_library.py")
text = script_path.read_text(encoding="utf-8")
text = text.replace(
    "import os\nimport re\nimport sys\n",
    "import os\nimport re\nimport shutil\nimport subprocess\nimport sys\n",
    1,
)
old = '''def decompress_index(url: str, data: bytes) -> bytes:
    lowered = url.lower()
    if data.startswith(b"\\x1f\\x8b") or lowered.endswith(".gz"):
        output = gzip.decompress(data)
    elif data.startswith(b"BZh") or lowered.endswith(".bz2"):
        output = bz2.decompress(data)
    elif data.startswith(b"\\xfd7zXZ\\x00") or lowered.endswith(".xz"):
        output = lzma.decompress(data)
    else:
        output = data
    if len(output) > MAX_DECOMPRESSED:
        raise ValueError("index exceeded decompressed size limit")
    return output
'''
new = '''ZSTD_MAGIC = b"\\x28\\xb5\\x2f\\xfd"


def decompress_zstd(data: bytes) -> bytes:
    tool = shutil.which("zstd") or shutil.which("unzstd")
    if not tool:
        raise ValueError("Zstandard package index found, but no zstd decoder is installed")
    try:
        completed = subprocess.run(
            [tool, "-d", "-q", "-c"],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Zstandard package index decoding timed out") from exc
    if completed.returncode != 0:
        detail = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(f"Zstandard package index decoding failed: {detail[:240]}")
    return completed.stdout


def decompress_index(url: str, data: bytes) -> bytes:
    # Compression is determined by magic bytes, never by the URL suffix. Some
    # repositories (notably CyPwn) serve Zstandard or HTML through .xz paths.
    if data.startswith(b"\\x1f\\x8b"):
        output = gzip.decompress(data)
    elif data.startswith(b"BZh"):
        output = bz2.decompress(data)
    elif data.startswith(b"\\xfd7zXZ\\x00"):
        output = lzma.decompress(data)
    elif data.startswith(ZSTD_MAGIC):
        output = decompress_zstd(data)
    else:
        output = data
    if len(output) > MAX_DECOMPRESSED:
        raise ValueError("index exceeded decompressed size limit")
    return output
'''
if old not in text:
    raise SystemExit("decompress_index block did not match")
text = text.replace(old, new, 1)
text = text.replace(
    '("Packages.xz", "Packages.bz2", "Packages.gz", "Packages")',
    '("Packages.zst", "Packages.xz", "Packages.bz2", "Packages.gz", "Packages")',
)
script_path.write_text(text, encoding="utf-8")

test_path = Path("tests/test_deb_library.py")
tests = test_path.read_text(encoding="utf-8")
marker = '\n\nif __name__ == "__main__":\n'
additions = '''
    def test_compression_detection_uses_magic_not_suffix(self) -> None:
        html = b"<html><body>not an xz stream</body></html>"
        self.assertEqual(
            library.decompress_index("https://repo.example/Packages.xz", html),
            html,
        )

    def test_candidate_urls_include_zstandard_indexes(self) -> None:
        urls, explicit = library.candidate_urls(self.direct_source)
        self.assertFalse(explicit)
        self.assertEqual(urls[0], "https://repo.example/Packages.zst")
        self.assertIn(
            "https://repo.example/dists/stable/main/binary-iphoneos-arm64/Packages.zst",
            urls,
        )
'''
if marker not in tests:
    raise SystemExit("test insertion marker missing")
tests = tests.replace(marker, "\n" + additions + marker, 1)
test_path.write_text(tests, encoding="utf-8")
