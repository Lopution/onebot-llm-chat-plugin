def test_config_audit_detects_media_supports_images_conflict(valid_api_key: str):
    from mika_chat_core.config import Config
    from mika_chat_core.utils.config_audit import audit_config

    cfg = Config(
        llm_api_key=valid_api_key,
        mika_master_id=123456789,
        mika_media_policy_default="images",
        mika_llm_supports_images=False,
    )

    codes = {item.code for item in audit_config(cfg)}
    assert "supports_images_conflict" in codes


def test_effective_snapshot_masks_secrets(valid_api_key: str):
    from mika_chat_core.config import Config
    from mika_chat_core.utils.config_snapshot import build_effective_config_snapshot

    cfg = Config(
        llm_api_key=valid_api_key,
        mika_master_id=123456789,
        search_api_key="B" * 32,
        mika_webui_token="super-secret-token",
        llm_extra_headers_json='{"X-Test":"value","Authorization":"Bearer secret"}',
    )

    snapshot = build_effective_config_snapshot(cfg)
    assert snapshot["config"]["llm_api_key"] != valid_api_key
    assert snapshot["config"]["search_api_key"] != "B" * 32
    assert snapshot["config"]["mika_webui_token"] != "super-secret-token"
    assert snapshot["config"]["llm_extra_headers_json"] != '{"X-Test":"value","Authorization":"Bearer secret"}'

    derived_llm = snapshot.get("derived", {}).get("llm", {})
    assert isinstance(derived_llm.get("api_keys"), list)
    assert derived_llm["api_keys"]  # should keep count

