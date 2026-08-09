import pytest
from backend.core.router import _fast_route_query


@pytest.mark.parametrize(
    "query",
    [
        "xin chào",
        "cảm ơn bạn nhiều lắm",
        "bạn là ai vậy?",
        "tạm biệt nhé",
        "hôm nay trời đẹp quá",
        "asdfjkl;qwerty",
    ],
)
def test_social_and_noise_queries_use_chitchat_fast_path(query: str) -> None:
    assert _fast_route_query(query) == "chitchat"


@pytest.mark.parametrize(
    "query",
    [
        "EPR là gì?",
        "Điều 77 quy định gì?",
        "ISO 14001 liên quan đến EPR như thế nào?",
    ],
)
def test_legal_signals_are_not_misclassified_as_chitchat(query: str) -> None:
    assert _fast_route_query(query) == "epr_query"
