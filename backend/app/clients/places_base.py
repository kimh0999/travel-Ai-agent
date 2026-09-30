from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class PlaceResult:
    provider_id: str
    name: str
    category: str
    address: str
    place_url: Optional[str]
    x: Optional[str]
    y: Optional[str]


class PlaceSearchError(Exception):
    pass


class PlaceProvider(Protocol):
    name: str
    is_mock: bool

    def search(self, query: str, size: int = 5) -> list[PlaceResult]:
        """키워드로 장소를 검색한다. 실패하면 PlaceSearchError."""
        ...
