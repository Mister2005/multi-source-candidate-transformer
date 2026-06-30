from abc import ABC, abstractmethod
from transformer.models import SourceItem, RawRecord


class BaseExtractor(ABC):
    @abstractmethod
    def extract(self, source: SourceItem) -> RawRecord:
        ...
