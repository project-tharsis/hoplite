import pytest
from src.data.understat import parse_match_data

SAMPLE_HTML = '''
<script>
var matchesData = JSON.parse('{"12345":{"h":{"title":"Arsenal"},"a":{"title":"Chelsea"},"xG":{"h":"2.31","a":"0.87"},"goals":{"h":"3","a":"1"}}}');
</script>
'''

def test_parse_match_data():
    matches = parse_match_data(SAMPLE_HTML)
    assert len(matches) == 1
    match = matches[0]
    assert match["home_team"] == "Arsenal"
    assert match["away_team"] == "Chelsea"
    assert match["home_xg"] == 2.31
    assert match["away_xg"] == 0.87
    assert match["home_goals"] == 3
    assert match["away_goals"] == 1
    assert match["match_id"] == "12345"

def test_parse_empty_html():
    matches = parse_match_data("<html>no data here</html>")
    assert matches == []
