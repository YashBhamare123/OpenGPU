from tunnel import last_ngrok_error, ngrok_token, parse_tcp_endpoint, persist_token


def test_parse_json_tcp_url():
    line = '{"url":"tcp://6.tcp.ngrok.io:12345","msg":"started tunnel"}'
    assert parse_tcp_endpoint(line) == ("6.tcp.ngrok.io", 12345)


def test_parse_plain_tcp_url():
    assert parse_tcp_endpoint("forwarding tcp://0.tcp.ngrok.io:18000") == ("0.tcp.ngrok.io", 18000)


def test_last_ngrok_error_extracts_tcp_plan_message():
    chunk = (
        '{"err":"<nil>","lvl":"info","msg":"open config file"}\n'
        '{"err":"failed to start tunnel: ERR_NGROK_8013\\nAdd a card.","lvl":"eror"}\n'
    )
    assert "ERR_NGROK_8013" in last_ngrok_error(chunk)


def test_ngrok_token_accepts_ngrok_token_alias(monkeypatch):
    monkeypatch.delenv("NGROK_AUTHTOKEN", raising=False)
    monkeypatch.setenv("NGROK_TOKEN", "alias-secret")
    assert ngrok_token() == "alias-secret"


def test_persist_token_updates_existing_ngrok_token_key(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SERVER_IP=10.0.0.1\nNGROK_TOKEN=old\n", encoding="utf-8")
    persist_token(env_file, "new-token")
    text = env_file.read_text(encoding="utf-8")
    assert "NGROK_TOKEN=new-token" in text
    assert "NGROK_AUTHTOKEN=" not in text
    assert "old" not in text


def test_persist_token_replaces_and_sets_mode(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("SERVER_IP=10.0.0.1\nNGROK_AUTHTOKEN=old\n", encoding="utf-8")
    persist_token(env_file, "new-token")
    text = env_file.read_text(encoding="utf-8")
    assert "NGROK_AUTHTOKEN=new-token" in text
    assert "old" not in text
    assert env_file.stat().st_mode & 0o777 == 0o600
