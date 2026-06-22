from lecturelog.application.factories import webhook_notifier_factory
from lecturelog.infrastructure.webhook.http_notifier import HttpWebhookNotifier


def test_factory_returns_none_without_url():
    # Без callback_url — автономный режим (None), даже если секрет задан.
    assert webhook_notifier_factory(None, "s") is None
    assert webhook_notifier_factory("", "s") is None


def test_factory_returns_none_without_secret():
    # URL задан, секрет нет — без подписи вебхук не включаем.
    assert webhook_notifier_factory("https://p", None) is None
    assert webhook_notifier_factory("https://p", "") is None


def test_factory_builds_notifier_when_both_set():
    notifier = webhook_notifier_factory("https://p", "s")
    assert isinstance(notifier, HttpWebhookNotifier)
