from lecturelog.infrastructure.persistence.orm import YoutubeCookieRow


def test_youtube_cookie_row_tablename_and_columns():
    assert YoutubeCookieRow.__tablename__ == "youtube_cookies"
    cols = YoutubeCookieRow.__table__.columns
    assert "id" in cols
    assert "content" in cols
    assert "updated_at" in cols
