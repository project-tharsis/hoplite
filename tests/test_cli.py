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


@patch("src.cli.load_config")
@patch("src.data.football_data.FootballDataClient")
@patch("src.output.feishu_card.FeishuCardBuilder")
@patch("src.report.ReportOrchestrator")
@patch("src.normalizer.normalize_football_data_match")
def test_cmd_latest_no_matches(mock_normalize, mock_orch, mock_card, mock_fd, mock_config):
    """Test cmd_latest when no matches are returned."""
    mock_config.return_value = {
        "data_sources": {"football_data": {"token": "x"}},
        "arsenal": {"team_id_football_data": 57},
        "feishu": {"hoplite_chat_id": "oc_test"}
    }
    mock_fd_instance = Mock()
    mock_fd_instance.get_team_matches.return_value = []
    mock_fd.return_value = mock_fd_instance
    
    with pytest.raises(SystemExit) as exc_info:
        from src.cli import cmd_latest
        cmd_latest(mock_config())
    assert exc_info.value.code == 1
