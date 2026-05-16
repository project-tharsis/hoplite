import pytest
from unittest.mock import patch, Mock
from src.cli import load_config


def test_load_config_missing():
    """Test that missing config.yaml exits gracefully."""
    with patch("src.cli.Path.exists", return_value=False):
        with pytest.raises(SystemExit) as exc_info:
            load_config()
        assert exc_info.value.code == 1


@patch("builtins.open")
@patch("src.cli.Path.exists", return_value=True)
@patch("yaml.safe_load")
def test_load_config_valid(mock_yaml, mock_exists, mock_open):
    mock_yaml.return_value = {
        "data_sources": {
            "football_data": {"token": "test_fd_token"},
            "api_football": {"key": "test_af_key"}
        },
        "arsenal": {"team_id_football_data": 57},
        "feishu": {"hoplite_chat_id": "oc_test"}
    }
    config = load_config()
    assert config["arsenal"]["team_id_football_data"] == 57
    assert config["feishu"]["hoplite_chat_id"] == "oc_test"


def test_cmd_latest_stub(capsys):
    """Test that cmd_latest prints deprecation stub."""
    from src.cli import cmd_latest
    cmd_latest({})
    captured = capsys.readouterr()
    assert "removed in v4" in captured.out
    assert "fetch_match_data" in captured.out
    assert "analyze_match" in captured.out
