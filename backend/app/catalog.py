"""Versioned model class catalogs with stable semantic identifiers."""

from __future__ import annotations

from .contracts import CatalogCategory, ModelClassCatalog

COCO_LABELS = (
    "person",
    "bicycle",
    "car",
    "motorcycle",
    "airplane",
    "bus",
    "train",
    "truck",
    "boat",
    "traffic light",
    "fire hydrant",
    "stop sign",
    "parking meter",
    "bench",
    "bird",
    "cat",
    "dog",
    "horse",
    "sheep",
    "cow",
    "elephant",
    "bear",
    "zebra",
    "giraffe",
    "backpack",
    "umbrella",
    "handbag",
    "tie",
    "suitcase",
    "frisbee",
    "skis",
    "snowboard",
    "sports ball",
    "kite",
    "baseball bat",
    "baseball glove",
    "skateboard",
    "surfboard",
    "tennis racket",
    "bottle",
    "wine glass",
    "cup",
    "fork",
    "knife",
    "spoon",
    "bowl",
    "banana",
    "apple",
    "sandwich",
    "orange",
    "broccoli",
    "carrot",
    "hot dog",
    "pizza",
    "donut",
    "cake",
    "chair",
    "couch",
    "potted plant",
    "bed",
    "dining table",
    "toilet",
    "tv",
    "laptop",
    "mouse",
    "remote",
    "keyboard",
    "cell phone",
    "microwave",
    "oven",
    "toaster",
    "sink",
    "refrigerator",
    "book",
    "clock",
    "vase",
    "scissors",
    "teddy bear",
    "hair drier",
    "toothbrush",
)

DESCRIPTIONS = {
    "person": "People visible in the camera frame.",
    "car": "Passenger cars recognized by the active COCO model.",
    "truck": "Trucks recognized by the active COCO model.",
    "bus": "Buses recognized by the active COCO model.",
    "bicycle": "Bicycles recognized by the active COCO model.",
    "motorcycle": "Motorcycles recognized by the active COCO model.",
    "cat": "Domestic cats recognized by the active COCO model.",
    "dog": "Dogs recognized by the active COCO model.",
    "bird": "Birds recognized by the active COCO model.",
}


def semantic_id(label: str) -> str:
    return f"coco:{label.replace(' ', '_')}"


def coco_catalog(backend_id: str, model_id: str) -> ModelClassCatalog:
    return ModelClassCatalog(
        revision="coco80-v1",
        backend_id=backend_id,
        model_id=model_id,
        categories=[
            CatalogCategory(
                semantic_id=semantic_id(label),
                native_class_id=index,
                display_label=label,
                description=DESCRIPTIONS.get(label),
            )
            for index, label in enumerate(COCO_LABELS)
        ],
    )


def catalog_for(backend_id: str, model_id: str) -> ModelClassCatalog:
    if backend_id == "fake":
        labels = ("person", "car", "dog") if model_id == "fake-multi-v1" else ("person",)
        return ModelClassCatalog(
            revision="coco-person-car-dog-v1" if len(labels) > 1 else "coco-person-v1",
            backend_id=backend_id,
            model_id=model_id,
            categories=[
                CatalogCategory(
                    semantic_id=semantic_id(label),
                    native_class_id=index,
                    display_label=label,
                    description=DESCRIPTIONS[label],
                )
                for index, label in enumerate(labels)
            ],
        )
    if backend_id == "ultralytics":
        return coco_catalog(backend_id, model_id)
    return ModelClassCatalog(
        revision=f"{backend_id}-unavailable-v1",
        backend_id=backend_id,
        model_id=model_id,
        categories=[],
    )


def normalize_semantic_id(value: str) -> str:
    return value if ":" in value else semantic_id(value)


def catalog_category_ids(catalog: ModelClassCatalog) -> frozenset[str]:
    return frozenset(category.semantic_id for category in catalog.categories)


def catalog_labels(catalog: ModelClassCatalog) -> dict[str, str]:
    """Map known IDs while leaving callers free to display unknown IDs verbatim."""
    return {category.semantic_id: category.display_label for category in catalog.categories}
