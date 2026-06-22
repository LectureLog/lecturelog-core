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


def _paths():
    return _schema()["paths"]


def test_openapi_declares_all_status_codes():
    paths = _paths()
    expected = {
        ("/api/v1/tasks", "post"): {"200", "400"},
        ("/api/v1/uploads", "post"): {"200", "400", "409"},
        ("/api/v1/tasks/{task_id}", "get"): {"200", "404"},
        ("/api/v1/tasks/{task_id}/transcript", "get"): {"200", "202", "400", "404", "409"},
        ("/api/v1/tasks/{task_id}/result", "get"): {"200", "404"},
        ("/api/v1/tasks/{task_id}/result-url", "get"): {"200", "404", "409"},
        ("/api/v1/health", "get"): {"200"},
    }
    for (path, method), codes in expected.items():
        responses = set(paths[path][method]["responses"])
        assert codes <= responses, (path, method, codes - responses)


def test_openapi_routes_have_summary_and_tags():
    paths = _paths()
    for path, methods in paths.items():
        for method, op in methods.items():
            assert op.get("summary"), (path, method)
            assert op.get("tags"), (path, method)


def _resolve_ref(schema, node):
    # Разворачивает $ref в фактическую модель из components.schemas.
    if "$ref" in node:
        name = node["$ref"].split("/")[-1]
        return schema["components"]["schemas"][name]
    return node


def test_openapi_transcript_errors_match_actual_bodies():
    # OpenAPI — источник правды для генерации клиента: схемы ошибок /transcript
    # обязаны соответствовать ФАКТИЧЕСКИМ телам ({"error": ...}), а не ErrorResponse
    # ({"detail": ...}). Сверяем форму для 400/404/409.
    schema = _schema()
    op = schema["paths"]["/api/v1/tasks/{task_id}/transcript"]["get"]
    responses = op["responses"]

    def props(code):
        media = responses[code]["content"]["application/json"]["schema"]
        return _resolve_ref(schema, media)["properties"]

    # 400: error + allowed (список форматов), без detail-only формы ErrorResponse.
    p400 = props("400")
    assert "error" in p400
    assert "allowed" in p400
    assert "detail" not in p400 or "error" in p400  # не чистый ErrorResponse

    # 404: error (task_not_found).
    p404 = props("404")
    assert "error" in p404

    # 409: error + detail (task.error).
    p409 = props("409")
    assert "error" in p409
    assert "detail" in p409

    # Ни одна из схем не должна быть голым ErrorResponse {detail: str}.
    for code in ("400", "404", "409"):
        assert set(props(code)) != {"detail"}, code
