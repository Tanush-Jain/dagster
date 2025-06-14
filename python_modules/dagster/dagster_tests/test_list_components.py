import pytest
from dagster._core.test_utils import ensure_dagster_tests_import, new_cwd
from dagster.components.list import list_all_components_schema, list_plugins
from dagster_shared.serdes.objects import (
    ComponentFeatureData,
    PluginObjectKey,
    PluginObjectSnap,
    ScaffoldTargetTypeData,
)
from dagster_shared.serdes.objects.package_entry import PluginManifest
from jsonschema import Draft202012Validator, ValidationError

ensure_dagster_tests_import()

from dagster_tests.components_tests.utils import create_project_from_components


def test_list_plugins_from_entry_points():
    # First check the default behavior. We don't check the actual content because that may note be
    # stable (we are loading from all entry points).
    result = list_plugins(entry_points=True, extra_modules=[])

    assert isinstance(result, PluginManifest)
    assert len(result.objects) > 1


def test_list_plugins_from_module():
    # Now check what we get when we load directly from the test library. This has stable results.
    result = list_plugins(entry_points=False, extra_modules=["dagster_test.components"])
    assert isinstance(result, PluginManifest)

    objects = result.objects
    assert [obj.key.to_typename() for obj in objects] == [
        "dagster_test.components.AllMetadataEmptyComponent",
        "dagster_test.components.ComplexAssetComponent",
        "dagster_test.components.SimpleAssetComponent",
        "dagster_test.components.SimplePipesScriptComponent",
    ]

    assert objects[2] == PluginObjectSnap(
        key=PluginObjectKey(namespace="dagster_test.components", name="SimpleAssetComponent"),
        description="A simple asset that returns a constant string value.",
        summary="A simple asset that returns a constant string value.",
        owners=["john@dagster.io", "jane@dagster.io"],
        tags=["a", "b", "c"],
        feature_data=[
            ComponentFeatureData(
                schema={
                    "additionalProperties": False,
                    "properties": {
                        "asset_key": {
                            "description": "A unique identifier for the asset.",
                            "title": "Asset Key",
                            "type": "string",
                        },
                        "value": {"title": "Value", "type": "string"},
                    },
                    "required": ["asset_key", "value"],
                    "title": "SimpleAssetComponentModel",
                    "type": "object",
                }
            ),
            ScaffoldTargetTypeData(
                schema={"properties": {}, "title": "NoParams", "type": "object"}
            ),
        ],
    )

    pipes_script_component_model_schema = {
        "additionalProperties": False,
        "properties": {
            "asset_key": {"title": "Asset Key", "type": "string"},
            "filename": {"title": "Filename", "type": "string"},
        },
        "required": ["asset_key", "filename"],
        "title": "SimplePipesScriptComponentModel",
        "type": "object",
    }

    pipes_script_component_scaffold_params_schema = {
        "properties": {
            "asset_key": {"title": "Asset Key", "type": "string"},
            "filename": {"title": "Filename", "type": "string"},
        },
        "required": ["asset_key", "filename"],
        "title": "SimplePipesScriptScaffoldParams",
        "type": "object",
    }

    assert objects[3] == PluginObjectSnap(
        key=PluginObjectKey(namespace="dagster_test.components", name="SimplePipesScriptComponent"),
        description="A simple asset that runs a Python script with the Pipes subprocess client.\n\nBecause it is a pipes asset, no value is returned.",
        summary="A simple asset that runs a Python script with the Pipes subprocess client.",
        owners=[],
        tags=[],
        feature_data=[
            ComponentFeatureData(schema=pipes_script_component_model_schema),
            ScaffoldTargetTypeData(schema=pipes_script_component_scaffold_params_schema),
        ],
    )


def test_list_plugins_from_project() -> None:
    """Tests that the list CLI picks components we add."""
    # Now create a project and load the component types only from that project.
    with create_project_from_components(
        "definitions/local_component_sample",
        "definitions/other_local_component_sample",
        "definitions/single_file",
    ) as (tmpdir, location_name):
        with new_cwd(str(tmpdir)):
            result = list_plugins(
                entry_points=False, extra_modules=[f"{location_name}.defs.local_component_sample"]
            )
            assert isinstance(result, PluginManifest)

            objects = result.objects

            assert len(objects) == 1
            assert objects[0].key == PluginObjectKey(
                namespace=f"{location_name}.defs.local_component_sample",
                name="MyComponent",
            )

            # Add a second module
            result = list_plugins(
                entry_points=False,
                extra_modules=[
                    f"{location_name}.defs.local_component_sample",
                    f"{location_name}.defs.other_local_component_sample",
                ],
            )
            assert isinstance(result, PluginManifest)
            assert len(result.objects) == 2
            assert [obj.key.to_typename() for obj in result.objects] == [
                f"{location_name}.defs.local_component_sample.MyComponent",
                f"{location_name}.defs.other_local_component_sample.MyNewComponent",
            ]

            # Add another, non-local component directory, which no-ops
            result = list_plugins(
                entry_points=False,
                extra_modules=[
                    f"{location_name}.defs.local_component_sample",
                    f"{location_name}.defs.other_local_component_sample",
                    f"{location_name}.defs.single_file",
                ],
            )
            assert isinstance(result, PluginManifest)

            assert len(result.objects) == 2


def test_all_components_schema_command():
    result = list_all_components_schema(
        entry_points=False, extra_modules=("dagster_test.components",)
    )

    component_type_keys = [
        "ComplexAssetComponent",
        "SimpleAssetComponent",
        "SimplePipesScriptComponent",
    ]

    assert result["anyOf"] == [
        {"$ref": f"#/$defs/{component_type_key}"} for component_type_key in component_type_keys
    ]

    # Sanity check each of the component type schemas has a constant type property matching the
    # fully scoped component type key
    for component_type_key in component_type_keys:
        component_type_schema_def = result["$defs"][component_type_key]
        assert "type" in component_type_schema_def["properties"]
        assert (
            component_type_schema_def["properties"]["type"]["default"]
            == f"dagster_test.components.{component_type_key}"
        )
        assert (
            component_type_schema_def["properties"]["type"]["const"]
            == f"dagster_test.components.{component_type_key}"
        )
        assert "attributes" in component_type_schema_def["properties"]

    top_level_component_validator = Draft202012Validator(schema=result)
    top_level_component_validator.validate(
        {
            "type": "dagster_test.components.SimpleAssetComponent",
            "attributes": {"asset_key": "my_asset", "value": "my_value"},
        }
    )
    with pytest.raises(ValidationError):
        top_level_component_validator.validate(
            {
                "type": "dagster_test.components.SimpleAssetComponent",
                "attributes": {"asset_key": "my_asset", "value": "my_value"},
                "extra_key": "extra_value",
            }
        )
