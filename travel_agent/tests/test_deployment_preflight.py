from scripts.preflight_public_deploy import validate


def _valid_values():
    return {
        "WECHAT_APP_ID": "wx-app-id",
        "WECHAT_APP_SECRET": "wechat-app-secret",
        "OWNER_OPENID": "owner-openid",
        "AUTH_TOKEN_SECRET": "a" * 40,
        "CLOUDFLARE_TUNNEL_TOKEN": "tunnel-token",
        "PUBLIC_API_BASE_URL": "https://travel.example.com",
        "HEALTH_ALERT_WEBHOOK_URL": "https://alerts.example.com/hook",
    }


def test_public_deployment_preflight_accepts_consistent_secure_configuration():
    values = _valid_values()
    private_config = f'const config = {{ apiBaseUrl: "{values["PUBLIC_API_BASE_URL"]}" }}'

    assert validate(values, private_config) == []


def test_public_deployment_preflight_rejects_missing_secrets_temporary_urls_and_mismatch():
    values = _valid_values()
    values["CLOUDFLARE_TUNNEL_TOKEN"] = ""
    values["AUTH_TOKEN_SECRET"] = "short"
    values["PUBLIC_API_BASE_URL"] = "https://temporary.trycloudflare.com"
    private_config = 'const config = { apiBaseUrl: "https://another.example.com" }'

    errors = validate(values, private_config)

    assert any("CLOUDFLARE_TUNNEL_TOKEN" in error for error in errors)
    assert any("32 characters" in error for error in errors)
    assert any("stable hostname" in error for error in errors)
    assert any("does not match" in error for error in errors)


def test_public_deployment_preflight_rejects_http_webhook_and_does_not_expose_values():
    values = _valid_values()
    values["HEALTH_ALERT_WEBHOOK_URL"] = "http://alerts.example.com/hook"

    errors = validate(values, 'const config = { apiBaseUrl: "https://travel.example.com" }')

    assert any("must be an HTTPS URL" in error for error in errors)
    assert not any("wechat-app-secret" in error or "tunnel-token" in error for error in errors)


def test_public_deployment_preflight_rejects_legacy_shared_trial_credential():
    values = _valid_values()
    private_config = (
        f'const config = {{ apiBaseUrl: "{values["PUBLIC_API_BASE_URL"]}", '
        'trialAccessKey: "must-not-be-included" }'
    )

    errors = validate(values, private_config)

    assert any("legacy trialAccessKey" in error for error in errors)


def test_legacy_trial_preview_requires_explicit_opt_in_and_matching_https_origin():
    values = {
        "LEGACY_TRIAL_AUTH_ENABLED": "true",
        "TRIAL_ACCESS_KEY": "preview-key",
        "PUBLIC_API_BASE_URL": "https://preview.trycloudflare.com",
    }
    private_config = (
        'const config = { authMode: "trial", trialAccessKey: "preview-key", '
        'apiBaseUrl: "https://preview.trycloudflare.com" }'
    )

    assert validate(values, private_config, legacy_trial_preview=True) == []

    values["LEGACY_TRIAL_AUTH_ENABLED"] = "false"
    errors = validate(values, private_config, legacy_trial_preview=True)
    assert any("must be explicitly true" in error for error in errors)

    values["LEGACY_TRIAL_AUTH_ENABLED"] = "true"
    values["TRIAL_ACCESS_KEY"] = "different-key"
    errors = validate(values, private_config, legacy_trial_preview=True)
    assert any("do not match" in error for error in errors)
