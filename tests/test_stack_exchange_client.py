import io

import py7zr
import pytest
import requests

from saas_words_two import stack_exchange_client as sec

SITE = "softwarerecs.stackexchange.com"

POSTS_XML = """<?xml version="1.0" encoding="utf-8"?>
<posts>
  <row Id="1" PostTypeId="1" CreationDate="2026-08-01T10:00:00.000" Score="5" AnswerCount="1" OwnerUserId="42" Title="Is there a tool for X" Body="&lt;p&gt;manual process takes hours&lt;/p&gt;" />
  <row Id="2" PostTypeId="2" ParentId="1" CreationDate="2026-08-01T11:00:00.000" Score="2" OwnerUserId="43" Body="&lt;p&gt;we still use spreadsheets&lt;/p&gt;" />
  <row Id="3" PostTypeId="4" CreationDate="2026-08-01T12:00:00.000" OwnerUserId="1" Body="tag wiki excerpt, not a real post" />
</posts>
"""


def build_fixture_archive(path):
    with py7zr.SevenZipFile(path, mode="w") as archive:
        archive.writef(io.BytesIO(POSTS_XML.encode("utf-8")), "Posts.xml")


def no_sleep(_seconds):
    return None


def test_make_item_id_is_deterministic_and_namespaced():
    item_id = sec.make_item_id(SITE, 1)
    assert item_id == 900100000001
    assert sec.make_item_id(SITE, 1) == item_id


def test_normalize_row_question_maps_to_story():
    row = {
        "Id": "1", "PostTypeId": "1", "CreationDate": "2026-08-01T10:00:00.000",
        "Score": "5", "AnswerCount": "1", "OwnerUserId": "42",
        "Title": "Is there a tool for X", "Body": "<p>manual process takes hours</p>",
    }
    normalized = sec.normalize_row(SITE, row)
    assert normalized["id"] == sec.make_item_id(SITE, 1)
    assert normalized["type"] == "story"
    assert normalized["title"] == "Is there a tool for X"
    assert normalized["parent"] is None
    assert normalized["by"] == "42"


def test_normalize_row_answer_maps_to_comment_with_parent():
    row = {
        "Id": "2", "PostTypeId": "2", "ParentId": "1", "CreationDate": "2026-08-01T11:00:00.000",
        "Score": "2", "OwnerUserId": "43", "Body": "<p>we still use spreadsheets</p>",
    }
    normalized = sec.normalize_row(SITE, row)
    assert normalized["type"] == "comment"
    assert normalized["parent"] == sec.make_item_id(SITE, 1)


def test_normalize_row_ignores_non_question_answer_post_types():
    row = {"Id": "3", "PostTypeId": "4", "OwnerUserId": "1", "Body": "tag wiki excerpt"}
    assert sec.normalize_row(SITE, row) is None


def test_normalize_row_skips_question_with_no_owner_user_id():
    """Regression: real Stack Exchange dumps omit OwnerUserId for posts by
    deleted/migrated accounts - found via parse_sources.py's real schema
    validation (hn_items.by required) against an actual dump, not a
    synthetic fixture. Such a post can't contribute a real independent
    user, so it must be dropped, not inserted with a missing 'by'."""
    row = {
        "Id": "4", "PostTypeId": "1", "CreationDate": "2026-08-01T10:00:00.000",
        "Title": "Is there a tool for Y", "Body": "<p>manual process takes hours</p>",
    }
    assert sec.normalize_row(SITE, row) is None


def test_normalize_row_skips_answer_with_no_owner_user_id():
    row = {
        "Id": "5", "PostTypeId": "2", "ParentId": "1", "CreationDate": "2026-08-01T11:00:00.000",
        "Body": "<p>we still use spreadsheets</p>",
    }
    assert sec.normalize_row(SITE, row) is None


def test_iter_posts_with_se_id_parses_fixture(tmp_path):
    archive_path = tmp_path / "sample.7z"
    build_fixture_archive(archive_path)
    posts_xml_path = sec.extract_posts_xml(archive_path, tmp_path)

    rows = list(sec.iter_posts_with_se_id(SITE, posts_xml_path))
    assert [se_id for se_id, _ in rows] == [1, 2, 3]
    normalized = [n for _se_id, n in rows if n is not None]
    assert len(normalized) == 2  # the PostTypeId=4 row normalizes to None


def test_iter_normalized_posts_skips_none(tmp_path):
    archive_path = tmp_path / "sample.7z"
    build_fixture_archive(archive_path)
    posts_xml_path = sec.extract_posts_xml(archive_path, tmp_path)
    normalized = list(sec.iter_normalized_posts(SITE, posts_xml_path))
    assert len(normalized) == 2
    assert normalized[0]["type"] == "story"
    assert normalized[1]["type"] == "comment"


class FakeStreamResponse:
    def __init__(self, content: bytes, status_ok: bool = True):
        self._content = content
        self._status_ok = status_ok

    def raise_for_status(self):
        if not self._status_ok:
            raise requests.HTTPError("bad status")

    def iter_content(self, chunk_size):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


class FakeSession:
    def __init__(self, content: bytes, status_ok: bool = True):
        self.content = content
        self.status_ok = status_ok
        self.calls: list[str] = []

    def get(self, url, timeout, stream):
        self.calls.append(url)
        return FakeStreamResponse(self.content, self.status_ok)


def test_download_dump_writes_file_and_is_idempotent(tmp_path):
    archive_bytes = b"fake-7z-bytes"
    dest = tmp_path / "site.7z"
    session = FakeSession(archive_bytes)

    result = sec.download_dump(session, SITE, dest, sleep_fn=no_sleep)
    assert result.ok
    assert result.data["cached"] is False
    assert dest.read_bytes() == archive_bytes
    assert len(session.calls) == 1

    # second call should hit the cache, not the network
    result2 = sec.download_dump(session, SITE, dest, sleep_fn=no_sleep)
    assert result2.ok
    assert result2.data["cached"] is True
    assert len(session.calls) == 1  # no new network call


def test_download_dump_fails_after_retries():
    dest_dir_session = FakeSession(b"", status_ok=False)

    def get_that_fails(url, timeout, stream):
        raise requests.ConnectionError("boom")

    dest_dir_session.get = get_that_fails
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmpdir:
        dest = Path(tmpdir) / "site.7z"
        result = sec.download_dump(dest_dir_session, SITE, dest, retry_attempts=2, sleep_fn=no_sleep)
    assert not result.ok
    assert result.attempts == 2


def test_access_test_pass_with_real_fixture_archive(tmp_path):
    dest = tmp_path / "site.7z"
    build_fixture_archive(dest)
    # pre-populate the "download" target so download_dump treats it as cached
    session = FakeSession(b"unused")
    result = sec.access_test(session, site=SITE, dest_path=dest, sleep_fn=no_sleep)
    assert result.ok
    assert result.data["questions"] == 1
    assert result.data["answers"] == 1
    assert result.data["cached_download"] is True


def test_access_test_fails_on_bad_7z_file(tmp_path):
    dest = tmp_path / "site.7z"
    dest.write_bytes(b"not a real 7z archive")
    session = FakeSession(b"unused")
    result = sec.access_test(session, site=SITE, dest_path=dest, sleep_fn=no_sleep)
    assert not result.ok


def test_access_test_fails_when_download_fails():
    def get_that_fails(url, timeout, stream):
        raise requests.ConnectionError("boom")

    session = FakeSession(b"")
    session.get = get_that_fails
    result = sec.access_test(session, site=SITE, sleep_fn=no_sleep)
    assert not result.ok
