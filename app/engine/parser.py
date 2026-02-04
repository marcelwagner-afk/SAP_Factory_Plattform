"""
SAP Implementation Factory - Configuration Parser

Parses and validates YAML configuration files.
Transforms raw YAML into validated domain models.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
import logging
import yaml
from pydantic import ValidationError

from app.models import (
    ImplementationModel,
    ProjectConfig,
    LandscapeConfig,
    ScopeConfig,
    CustomizingConfig,
    MigrationConfig,
    TestingConfig,
)

logger = logging.getLogger(__name__)


class ParserError(Exception):
    """Exception raised for parser errors."""

    def __init__(self, message: str, errors: Optional[List[str]] = None):
        self.message = message
        self.errors = errors or []
        super().__init__(self.message)


class ConfigParser:
    """
    Parser for SAP Implementation configuration files.

    Responsibilities:
    - Parse YAML content
    - Validate structure and required fields
    - Transform to domain model (ImplementationModel)
    - Report clear validation errors
    """

    # Required top-level sections
    REQUIRED_SECTIONS = ["project"]

    # Optional sections with defaults
    OPTIONAL_SECTIONS = ["landscape", "scope", "customizing", "migration", "testing"]

    def __init__(self):
        """Initialize parser."""
        self.logger = logging.getLogger(__name__)

    def parse(self, yaml_content: str) -> ImplementationModel:
        """
        Parse YAML content into ImplementationModel.

        Args:
            yaml_content: YAML configuration string

        Returns:
            Validated ImplementationModel

        Raises:
            ParserError: If parsing or validation fails
        """
        # Step 1: Parse YAML syntax
        raw_config = self._parse_yaml(yaml_content)

        # Step 2: Validate structure
        validation_errors = self._validate_structure(raw_config)
        if validation_errors:
            raise ParserError(
                "Configuration validation failed",
                errors=validation_errors,
            )

        # Step 3: Transform to domain model
        try:
            model = self._transform_to_model(raw_config)
        except ValidationError as e:
            errors = [f"{err['loc']}: {err['msg']}" for err in e.errors()]
            raise ParserError("Model validation failed", errors=errors)

        # Step 4: Semantic validation
        semantic_errors = self._validate_semantics(model)
        if semantic_errors:
            raise ParserError(
                "Semantic validation failed",
                errors=semantic_errors,
            )

        self.logger.info(
            f"Successfully parsed configuration for project: {model.project.name}"
        )
        return model

    def _parse_yaml(self, yaml_content: str) -> Dict[str, Any]:
        """
        Parse YAML string to dictionary.

        Args:
            yaml_content: Raw YAML string

        Returns:
            Parsed dictionary

        Raises:
            ParserError: If YAML syntax is invalid
        """
        try:
            config = yaml.safe_load(yaml_content)
            if config is None:
                raise ParserError("Empty configuration")
            if not isinstance(config, dict):
                raise ParserError("Configuration must be a YAML mapping/dictionary")
            return config
        except yaml.YAMLError as e:
            raise ParserError(f"YAML syntax error: {str(e)}")

    def _validate_structure(self, config: Dict[str, Any]) -> List[str]:
        """
        Validate configuration structure.

        Args:
            config: Parsed configuration dictionary

        Returns:
            List of validation errors
        """
        errors = []

        # Check required sections
        for section in self.REQUIRED_SECTIONS:
            if section not in config:
                errors.append(f"Missing required section: '{section}'")
            elif not isinstance(config[section], dict):
                errors.append(f"Section '{section}' must be a mapping")

        # Validate project section
        if "project" in config and isinstance(config["project"], dict):
            project = config["project"]
            if "name" not in project:
                errors.append("project.name is required")
            if "customer" not in project:
                errors.append("project.customer is required")

        # Validate landscape section
        if "landscape" in config:
            landscape = config["landscape"]
            if isinstance(landscape, dict):
                systems = landscape.get("systems", [])
                if not isinstance(systems, list):
                    errors.append("landscape.systems must be a list")
                else:
                    for i, system in enumerate(systems):
                        if not isinstance(system, dict):
                            errors.append(f"landscape.systems[{i}] must be a mapping")
                        elif "id" not in system:
                            errors.append(f"landscape.systems[{i}].id is required")

        # Validate customizing section
        if "customizing" in config:
            cust = config["customizing"]
            if isinstance(cust, dict):
                packages = cust.get("packages", [])
                if not isinstance(packages, list):
                    errors.append("customizing.packages must be a list")
                else:
                    for i, pkg in enumerate(packages):
                        if not isinstance(pkg, dict):
                            errors.append(f"customizing.packages[{i}] must be a mapping")
                        elif "id" not in pkg:
                            errors.append(f"customizing.packages[{i}].id is required")

        # Validate migration section
        if "migration" in config:
            migr = config["migration"]
            if isinstance(migr, dict):
                objects = migr.get("objects", [])
                if not isinstance(objects, list):
                    errors.append("migration.objects must be a list")

        # Validate testing section
        if "testing" in config:
            test = config["testing"]
            if isinstance(test, dict):
                suites = test.get("suites", [])
                if not isinstance(suites, list):
                    errors.append("testing.suites must be a list")

        return errors

    def _transform_to_model(self, config: Dict[str, Any]) -> ImplementationModel:
        """
        Transform dictionary to ImplementationModel.

        Args:
            config: Validated configuration dictionary

        Returns:
            ImplementationModel instance
        """
        # Create model with Pydantic validation
        model = ImplementationModel(
            project=ProjectConfig(**config["project"]),
            landscape=LandscapeConfig(**config.get("landscape", {})),
            scope=ScopeConfig(**config.get("scope", {})),
            customizing=CustomizingConfig(**config.get("customizing", {})),
            migration=MigrationConfig(**config.get("migration", {})),
            testing=TestingConfig(**config.get("testing", {})),
        )

        return model

    def _validate_semantics(self, model: ImplementationModel) -> List[str]:
        """
        Validate semantic correctness of the model.

        Args:
            model: Parsed ImplementationModel

        Returns:
            List of semantic validation errors
        """
        errors = []

        # Check system references in customizing
        system_ids = {s.id for s in model.landscape.systems}
        if system_ids:
            for pkg in model.customizing.packages:
                if pkg.target not in system_ids:
                    errors.append(
                        f"Customizing package '{pkg.id}' references unknown "
                        f"system '{pkg.target}'"
                    )

            for obj in model.migration.objects:
                if obj.target not in system_ids:
                    errors.append(
                        f"Migration object '{obj.id}' references unknown "
                        f"system '{obj.target}'"
                    )

            for suite in model.testing.suites:
                if suite.target not in system_ids:
                    errors.append(
                        f"Test suite '{suite.id}' references unknown "
                        f"system '{suite.target}'"
                    )

        # Check for duplicate IDs
        pkg_ids = [pkg.id for pkg in model.customizing.packages]
        if len(pkg_ids) != len(set(pkg_ids)):
            errors.append("Duplicate customizing package IDs found")

        obj_ids = [obj.id for obj in model.migration.objects]
        if len(obj_ids) != len(set(obj_ids)):
            errors.append("Duplicate migration object IDs found")

        suite_ids = [suite.id for suite in model.testing.suites]
        if len(suite_ids) != len(set(suite_ids)):
            errors.append("Duplicate test suite IDs found")

        return errors

    def parse_file(self, file_path: str) -> ImplementationModel:
        """
        Parse configuration from file.

        Args:
            file_path: Path to YAML file

        Returns:
            Validated ImplementationModel

        Raises:
            ParserError: If file cannot be read or parsed
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                yaml_content = f.read()
        except IOError as e:
            raise ParserError(f"Cannot read file: {str(e)}")

        return self.parse(yaml_content)

    def validate_only(self, yaml_content: str) -> Tuple[bool, List[str]]:
        """
        Validate configuration without returning model.

        Args:
            yaml_content: YAML configuration string

        Returns:
            Tuple of (is_valid, error_list)
        """
        try:
            self.parse(yaml_content)
            return True, []
        except ParserError as e:
            return False, e.errors


# Singleton instance
parser = ConfigParser()


def get_parser() -> ConfigParser:
    """Get parser instance."""
    return parser
