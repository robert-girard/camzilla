from app.catalog import catalog_category_ids, catalog_for, semantic_id


def test_catalog_uses_stable_semantic_and_model_native_ids() -> None:
    catalog = catalog_for("ultralytics", "yolo11s")

    assert catalog.revision == "coco80-v1"
    assert len(catalog.categories) == 80
    assert catalog.categories[0].semantic_id == "coco:person"
    assert catalog.categories[0].native_class_id == 0
    assert catalog.categories[2].semantic_id == "coco:car"
    assert catalog.categories[2].native_class_id == 2
    assert semantic_id("traffic light") == "coco:traffic_light"
    assert len(catalog_category_ids(catalog)) == 80


def test_deterministic_models_expose_different_verified_catalogs() -> None:
    person = catalog_for("fake", "fake-person-v1")
    multi = catalog_for("fake", "fake-multi-v1")

    assert catalog_category_ids(person) == {"coco:person"}
    assert catalog_category_ids(multi) == {"coco:person", "coco:car", "coco:dog"}
    assert person.revision != multi.revision
