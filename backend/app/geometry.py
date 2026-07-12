from dataclasses import dataclass

from .contracts import NormalizedBox


@dataclass(frozen=True)
class LetterboxTransform:
    source_width: int
    source_height: int
    model_width: int
    model_height: int

    @property
    def scale(self) -> float:
        return min(self.model_width / self.source_width, self.model_height / self.source_height)

    @property
    def padding_x(self) -> float:
        return (self.model_width - self.source_width * self.scale) / 2

    @property
    def padding_y(self) -> float:
        return (self.model_height - self.source_height * self.scale) / 2

    def model_to_normalized(self, x1: float, y1: float, x2: float, y2: float) -> NormalizedBox:
        """Undo aspect-preserving letterboxing and clamp to the source image."""
        source_x1 = max(0.0, min(self.source_width, (x1 - self.padding_x) / self.scale))
        source_y1 = max(0.0, min(self.source_height, (y1 - self.padding_y) / self.scale))
        source_x2 = max(0.0, min(self.source_width, (x2 - self.padding_x) / self.scale))
        source_y2 = max(0.0, min(self.source_height, (y2 - self.padding_y) / self.scale))
        return NormalizedBox(
            x=source_x1 / self.source_width,
            y=source_y1 / self.source_height,
            width=(source_x2 - source_x1) / self.source_width,
            height=(source_y2 - source_y1) / self.source_height,
        )
