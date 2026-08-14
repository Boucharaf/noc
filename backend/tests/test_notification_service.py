import json
from types import SimpleNamespace

from twilio.base.exceptions import TwilioRestException

from app.services import notification_service as ns


def test_sms_skipped_when_unconfigured():
    assert ns.send_sms("test") == 0


def test_email_skipped_when_unconfigured():
    assert ns.send_email("subject", "body") == 0


def test_notify_disabled_sends_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(ns, "NOTIFICATIONS_ENABLED", False)
    monkeypatch.setattr(ns, "send_sms", lambda body: called.append(("sms", body)))
    monkeypatch.setattr(
        ns, "send_email", lambda subject, body, html=None: called.append(("email", body))
    )
    ns.notify_critical_incident(1, "DED-001", "DREP Dédougou", "critical", "2026-05-17", "panne", None)
    assert called == []


def test_notify_sends_sms_and_email(monkeypatch):
    called = []
    monkeypatch.setattr(ns, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(ns, "send_sms", lambda body: called.append(("sms", body)) or 1)
    monkeypatch.setattr(
        ns,
        "send_email",
        lambda subject, body, html=None: called.append(("email", subject + body, html)) or 1,
    )
    ns.notify_critical_incident(
        4821, "DED-001", "DREP Dédougou", "critical", "2026-05-17T03:22:00",
        "Perte de connectivité", "TKT-2026-04821",
    )
    kinds = [k for k, *_ in called]
    assert kinds == ["sms", "email"]
    sms_body = called[0][1]
    assert "DED-001" in sms_body and "CRITICAL" in sms_body and "TKT-2026-04821" in sms_body
    email_content = called[1][1]
    assert "DED-001" in email_content and "#4821" in email_content
    # The text part must stand on its own; the HTML is the alternative.
    email_html = called[1][2]
    assert email_html and "DED-001" in email_html and "TKT-2026-04821" in email_html


def test_notify_never_raises(monkeypatch):
    def boom(body):
        raise RuntimeError("provider down")

    monkeypatch.setattr(ns, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(ns, "send_sms", boom)
    # Must swallow the exception — ingestion depends on it.
    ns.notify_critical_incident(1, "OUA-003", "Nœud Ouaga", "critical", "2026-06-01", None, None)


def _render(**overrides):
    kwargs = {
        "incident_id": 4821,
        "node_code": "DED-001",
        "node_name": "DREP Dédougou",
        "severity": "critical",
        "detected_at": "2026-05-17T03:22:00",
        "description": "Perte de connectivité",
        "itop_ticket_id": "I-023404",
    }
    kwargs.update(overrides)
    return ns._incident_email_html(**kwargs)


def test_email_html_carries_the_incident_facts():
    html = _render()
    for expected in ("DED-001", "DREP Dédougou", "I-023404", "#4821", "ALERTE CRITIQUE"):
        assert expected in html
    assert "17/05/2026 à 03h22" in html  # ISO reformatted for humans


def test_email_html_escapes_supervision_text():
    # Descriptions arrive from Zabbix/iTop and are not trusted markup.
    html = _render(description="<script>alert(1)</script>", node_name="A & B")
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "A &amp; B" in html


def test_email_html_severity_colour_follows_the_incident():
    assert ns.SEVERITY_COLOR["high"] in _render(severity="high")
    assert ns.SEVERITY_COLOR["critical"] in _render(severity="critical")


def test_email_html_drops_optional_blocks_when_absent(monkeypatch):
    monkeypatch.setattr(ns, "DASHBOARD_URL", "")
    html = _render(description=None, itop_ticket_id=None)
    assert "Description" not in html
    assert "Ouvrir le dashboard" not in html
    assert "—" in html  # ticket row still rendered, with a dash


def test_email_html_links_the_dashboard_when_configured(monkeypatch):
    monkeypatch.setattr(ns, "DASHBOARD_URL", "https://noc.anptic.bf")
    assert 'href="https://noc.anptic.bf/global"' in _render()


def test_email_sends_multipart_alternative(monkeypatch):
    sent = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, user, password):
            pass

        def sendmail(self, sender, recipients, message):
            sent["message"] = message

    monkeypatch.setattr(ns, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(ns, "SMTP_USER", "")
    monkeypatch.setattr(ns, "NOC_EMAIL_RECIPIENTS", ["noc@anptic.bf"])
    monkeypatch.setattr(ns.smtplib, "SMTP", FakeSMTP)

    assert ns.send_email("sujet", "texte brut", html="<b>riche</b>") == 1
    message = sent["message"]
    assert "multipart/alternative" in message
    assert "text/plain" in message and "text/html" in message
    # Plain text first: multipart/alternative shows the *last* part it can render.
    assert message.index("text/plain") < message.index("text/html")


def test_email_stays_plain_text_without_html(monkeypatch):
    sent = {}
    monkeypatch.setattr(ns, "SMTP_HOST", "smtp.test")
    monkeypatch.setattr(ns, "NOC_EMAIL_RECIPIENTS", ["noc@anptic.bf"])
    monkeypatch.setattr(
        ns.smtplib,
        "SMTP",
        lambda *a, **k: type(
            "S",
            (),
            {
                "__enter__": lambda s: s,
                "__exit__": lambda s, *e: False,
                "starttls": lambda s: None,
                "login": lambda s, u, p: None,
                "sendmail": lambda s, f, r, m: sent.update(message=m),
            },
        )(),
    )
    assert ns.send_email("sujet", "texte brut") == 1
    assert "multipart" not in sent["message"]


def _configure_sms(monkeypatch, recipients=("+22670000001", "+22670000002")):
    monkeypatch.setattr(ns, "TWILIO_ACCOUNT_SID", "AC123")
    monkeypatch.setattr(ns, "TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setattr(ns, "TWILIO_API_KEY_SID", "")
    monkeypatch.setattr(ns, "TWILIO_API_KEY_SECRET", "")
    monkeypatch.setattr(ns, "TWILIO_CONTENT_SID", "HX999")
    monkeypatch.setattr(ns, "TWILIO_FROM_NUMBER", "+15550000000")
    monkeypatch.setattr(ns, "NOC_SMS_RECIPIENTS", list(recipients))


def test_sms_rejects_an_api_key_in_the_account_slot(monkeypatch, caplog):
    _configure_sms(monkeypatch)
    # The 401 / error 20003 case: an SK… value where the AC… account SID belongs.
    monkeypatch.setattr(ns, "TWILIO_ACCOUNT_SID", "SK7b808d1d52")

    assert ns.send_sms("alerte") == 0
    assert "must be the AC" in caplog.text


def test_sms_api_key_authenticates_but_account_addresses(monkeypatch):
    _configure_sms(monkeypatch)
    monkeypatch.setattr(ns, "TWILIO_API_KEY_SID", "SK456")
    monkeypatch.setattr(ns, "TWILIO_API_KEY_SECRET", "secret")

    client = ns._twilio_client()
    assert (client.username, client.password) == ("SK456", "secret")
    # The URL still has to name the account, not the key.
    assert client.account_sid == "AC123"


def test_sms_falls_back_to_the_account_auth_token(monkeypatch):
    _configure_sms(monkeypatch)
    client = ns._twilio_client()
    assert (client.username, client.password) == ("AC123", "tok")
    assert client.account_sid == "AC123"


def test_sms_needs_some_credential(monkeypatch):
    _configure_sms(monkeypatch)
    monkeypatch.setattr(ns, "TWILIO_AUTH_TOKEN", "")
    assert ns.send_sms("alerte") == 0


class FakeMessages:
    def __init__(self, created, fail_for=()):
        self.created = created
        self.fail_for = fail_for

    def create(self, from_=None, to=None, body=None, content_sid=None, content_variables=None):
        if to in self.fail_for:
            raise TwilioRestException(status=400, uri="/Messages.json", msg="invalid number")
        self.created.append(
            {
                "from_": from_,
                "to": to,
                "body": body,
                "content_sid": content_sid,
                "content_variables": content_variables,
            }
        )
        return object()


def test_sms_sends_through_the_twilio_client(monkeypatch):
    created = []
    _configure_sms(monkeypatch)
    monkeypatch.setattr(ns, "_twilio_client", lambda: SimpleNamespace(messages=FakeMessages(created)))

    assert ns.send_sms("alerte") == 2
    assert [m["to"] for m in created] == ["+22670000001", "+22670000002"]
    assert all(m["from_"] == "+15550000000" for m in created)


def test_sms_sends_the_content_template_not_a_body(monkeypatch):
    created = []
    _configure_sms(monkeypatch)
    monkeypatch.setattr(ns, "_twilio_client", lambda: SimpleNamespace(messages=FakeMessages(created)))

    ns.send_sms("alerte")
    # A trial account rejects `body`, so nothing may go out that way.
    assert all(m["body"] is None for m in created)
    assert all(m["content_sid"] == "HX999" for m in created)
    assert json.loads(created[0]["content_variables"])["1"] == "alerte"


def test_sms_without_a_content_template_is_skipped(monkeypatch, caplog):
    _configure_sms(monkeypatch)
    monkeypatch.setattr(ns, "TWILIO_CONTENT_SID", "")
    assert ns.send_sms("alerte") == 0
    assert "TWILIO_CONTENT_SID is not set" in caplog.text


def test_content_variables_fill_every_slot_and_truncate():
    variables = json.loads(ns._content_variables("x" * 500))
    assert len(variables["1"]) == ns.SMS_VARIABLE_MAX_CHARS
    # Unused slots are sent empty rather than left as literal "{{2}}".
    assert [variables[str(i)] for i in range(2, ns.TWILIO_CONTENT_VARIABLE_SLOTS + 1)] == [""] * (
        ns.TWILIO_CONTENT_VARIABLE_SLOTS - 1
    )


def test_sms_client_gets_the_configured_credentials(monkeypatch):
    _configure_sms(monkeypatch)
    client = ns._twilio_client()
    assert client.username == "AC123"
    assert client.password == "tok"


def test_sms_counts_only_what_twilio_accepted(monkeypatch):
    created = []
    _configure_sms(monkeypatch)
    monkeypatch.setattr(
        ns,
        "_twilio_client",
        lambda: SimpleNamespace(messages=FakeMessages(created, fail_for=("+22670000001",))),
    )

    # One rejected number must not stop the others, nor raise.
    assert ns.send_sms("alerte") == 1
    assert [m["to"] for m in created] == ["+22670000002"]
