from lecturelog.api.app import create_app


def _schema():
    # Схема строится без lifespan: app.openapi() не подключается к БД/MinIO.
    return create_app().openapi()


def test_openapi_info_has_version_and_description():
    info = _schema()["info"]
    assert info["title"] == "LectureLog"
    assert info["version"] == "1.0.0"
    assert info["description"]  # непустое описание продукта


def test_openapi_usage_is_structured():
    schemas = _schema()["components"]["schemas"]
    assert "Usage" in schemas
    usage = schemas["Usage"]
    # Не бесформенный object: есть свойства стадий.
    assert set(usage["properties"]) >= {"transcribe", "structurize", "video_slides", "total"}
    assert "TotalUsage" in schemas
    assert "StageUsage" in schemas
