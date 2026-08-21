# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Tests pour les scripts d'installation et configuration Docker.

pytest tests/test_installation.py -v
"""

import pytest
from pathlib import Path


# ============================================================================
# FIXTURES
# ============================================================================

@pytest.fixture
def project_root():
    """Retourne le répertoire racine du projet."""
    return Path(__file__).parent.parent


# ============================================================================
# TESTS SCRIPT SHELL (install.sh)
# ============================================================================

class TestInstallShell:
    """Tests pour le script install.sh."""

    def test_install_sh_exists(self, project_root):
        """Test que install.sh existe."""
        script_path = project_root / "install.sh"
        assert script_path.exists(), "install.sh n'existe pas"

    def test_install_sh_is_executable_content(self, project_root):
        """Test que install.sh a le bon shebang."""
        script_path = project_root / "install.sh"
        content = script_path.read_text(encoding="utf-8")
        assert content.startswith("#!/bin/bash"), "Mauvais shebang"

    def test_install_sh_has_required_sections(self, project_root):
        """Test que install.sh contient les sections requises."""
        script_path = project_root / "install.sh"
        content = script_path.read_text(encoding="utf-8")

        # Vérifier les sections clés
        assert "python" in content.lower(), "Section Python manquante"
        assert "venv" in content, "Section venv manquante"
        assert "pip install" in content, "Section pip install manquante"
        assert "requirements.txt" in content, "Référence à requirements.txt manquante"

    def test_install_sh_has_help(self, project_root):
        """Test que install.sh a une option d'aide."""
        script_path = project_root / "install.sh"
        content = script_path.read_text(encoding="utf-8")

        assert "--help" in content, "Option --help manquante"

    def test_install_sh_creates_directories(self, project_root):
        """Test que install.sh crée les répertoires nécessaires."""
        script_path = project_root / "install.sh"
        content = script_path.read_text(encoding="utf-8")

        assert "mkdir" in content, "Création de répertoires manquante"
        assert "data" in content, "Répertoire data manquant"
        assert "logs" in content, "Répertoire logs manquant"
        assert "knowledge" in content, "Répertoire knowledge manquant"


# ============================================================================
# TESTS SCRIPT WINDOWS (install.bat)
# ============================================================================

class TestInstallBat:
    """Tests pour le script install.bat."""

    def test_install_bat_exists(self, project_root):
        """Test que install.bat existe."""
        script_path = project_root / "install.bat"
        assert script_path.exists(), "install.bat n'existe pas"

    def test_install_bat_is_batch_file(self, project_root):
        """Test que install.bat est un fichier batch valide."""
        script_path = project_root / "install.bat"
        content = script_path.read_text(encoding="utf-8")
        assert "@echo off" in content.lower(), "Commande @echo off manquante"

    def test_install_bat_has_required_sections(self, project_root):
        """Test que install.bat contient les sections requises."""
        script_path = project_root / "install.bat"
        content = script_path.read_text(encoding="utf-8")

        assert "python" in content.lower(), "Section Python manquante"
        assert "venv" in content.lower(), "Section venv manquante"
        assert "pip install" in content.lower(), "Section pip install manquante"

    def test_install_bat_has_help(self, project_root):
        """Test que install.bat a une option d'aide."""
        script_path = project_root / "install.bat"
        content = script_path.read_text(encoding="utf-8")

        assert "--help" in content, "Option --help manquante"


# ============================================================================
# TESTS DOCKERFILE
# ============================================================================

class TestDockerfile:
    """Tests pour le Dockerfile."""

    def test_dockerfile_exists(self, project_root):
        """Test que le Dockerfile existe."""
        dockerfile = project_root / "Dockerfile"
        assert dockerfile.exists(), "Dockerfile n'existe pas"

    def test_dockerfile_has_from(self, project_root):
        """Test que le Dockerfile a une instruction FROM."""
        dockerfile = project_root / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")

        assert "FROM python:" in content, "Instruction FROM manquante"

    def test_dockerfile_has_workdir(self, project_root):
        """Test que le Dockerfile a un WORKDIR."""
        dockerfile = project_root / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")

        assert "WORKDIR /app" in content, "WORKDIR manquant"

    def test_dockerfile_copies_requirements(self, project_root):
        """Test que le Dockerfile copie requirements.txt."""
        dockerfile = project_root / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")

        assert "requirements.txt" in content, "Copie requirements.txt manquante"

    def test_dockerfile_copies_email_retention_audit(self, project_root):
        """Test que le script d'audit retention est disponible dans l'image."""
        dockerfile = project_root / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")

        assert "scripts/audit_email_content_retention.py" in content

    def test_dockerfile_installs_dependencies(self, project_root):
        """Test que le Dockerfile installe les dépendances."""
        dockerfile = project_root / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")

        assert "pip install" in content, "Installation pip manquante"

    def test_dockerfile_has_healthcheck(self, project_root):
        """Test que le Dockerfile a un healthcheck."""
        dockerfile = project_root / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")

        assert "HEALTHCHECK" in content, "HEALTHCHECK manquant"

    def test_dockerfile_has_cmd(self, project_root):
        """Test que le Dockerfile a une commande par défaut."""
        dockerfile = project_root / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")

        assert "CMD" in content, "CMD manquant"

    def test_dockerfile_uses_nonroot_user(self, project_root):
        """Test que le Dockerfile utilise un utilisateur non-root."""
        dockerfile = project_root / "Dockerfile"
        content = dockerfile.read_text(encoding="utf-8")

        assert "USER" in content, "Instruction USER manquante"
        assert "useradd" in content or "adduser" in content, "Création utilisateur manquante"


# ============================================================================
# TESTS DOCKER COMPOSE
# ============================================================================

class TestDockerCompose:
    """Tests pour docker-compose.yml."""

    def test_docker_compose_exists(self, project_root):
        """Test que docker-compose.yml existe."""
        compose = project_root / "docker-compose.yml"
        assert compose.exists(), "docker-compose.yml n'existe pas"

    def test_docker_compose_is_valid_yaml(self, project_root):
        """Test que docker-compose.yml est un YAML valide.

        Note: Le champ 'version:' est déprécié depuis Docker Compose V2
        et n'est plus requis. On vérifie simplement que le fichier est
        un YAML valide avec une section 'services:'.
        """
        import yaml
        compose = project_root / "docker-compose.yml"
        content = compose.read_text(encoding="utf-8")

        # Vérifier que c'est du YAML valide
        try:
            data = yaml.safe_load(content)
            assert data is not None, "Fichier YAML vide"
            assert "services" in data, "Section 'services' manquante"
        except yaml.YAMLError as e:
            pytest.fail(f"YAML invalide: {e}")

    def test_docker_compose_has_services(self, project_root):
        """Test que docker-compose.yml a des services."""
        compose = project_root / "docker-compose.yml"
        content = compose.read_text(encoding="utf-8")

        assert "services:" in content, "Section services manquante"
        assert "agentys:" in content, "Service agentys manquant"

    def test_docker_compose_has_volumes(self, project_root):
        """Test que docker-compose.yml a des volumes."""
        compose = project_root / "docker-compose.yml"
        content = compose.read_text(encoding="utf-8")

        assert "volumes:" in content, "Section volumes manquante"
        assert "./data:/app/data" in content, "Volume data manquant"

    def test_docker_compose_has_environment(self, project_root):
        """Test que docker-compose.yml a des variables d'environnement."""
        compose = project_root / "docker-compose.yml"
        content = compose.read_text(encoding="utf-8")

        assert "environment:" in content, "Section environment manquante"
        assert "ANTHROPIC_API_KEY" in content, "Variable ANTHROPIC_API_KEY manquante"

    def test_docker_compose_has_healthcheck(self, project_root):
        """Test que docker-compose.yml a un healthcheck."""
        compose = project_root / "docker-compose.yml"
        content = compose.read_text(encoding="utf-8")

        assert "healthcheck:" in content, "Healthcheck manquant"

    def test_docker_compose_has_logging(self, project_root):
        """Test que docker-compose.yml configure le logging."""
        compose = project_root / "docker-compose.yml"
        content = compose.read_text(encoding="utf-8")

        assert "logging:" in content, "Configuration logging manquante"

    def test_docker_compose_has_optional_services(self, project_root):
        """Test que docker-compose.yml a des services optionnels."""
        compose = project_root / "docker-compose.yml"
        content = compose.read_text(encoding="utf-8")

        assert "profiles:" in content, "Profiles manquants pour services optionnels"


# ============================================================================
# TESTS REQUIREMENTS
# ============================================================================

class TestRequirements:
    """Tests pour requirements.txt."""

    def test_requirements_exists(self, project_root):
        """Test que requirements.txt existe."""
        requirements = project_root / "requirements.txt"
        assert requirements.exists(), "requirements.txt n'existe pas"

    def test_requirements_has_core_deps(self, project_root):
        """Test que requirements.txt a les dépendances principales."""
        requirements = project_root / "requirements.txt"
        content = requirements.read_text(encoding="utf-8").lower()

        core_deps = ["anthropic", "flask", "python-dotenv"]
        for dep in core_deps:
            assert dep in content, f"Dépendance {dep} manquante"


# ============================================================================
# TESTS INTEGRATION
# ============================================================================

class TestInstallationIntegration:
    """Tests d'intégration pour l'installation."""

    def test_all_installation_files_exist(self, project_root):
        """Test que tous les fichiers d'installation existent."""
        required_files = [
            "install.sh",
            "install.bat",
            "Dockerfile",
            "docker-compose.yml",
            "requirements.txt",
        ]

        for filename in required_files:
            filepath = project_root / filename
            assert filepath.exists(), f"{filename} n'existe pas"

    def test_installation_scripts_are_consistent(self, project_root):
        """Test que les scripts d'installation sont cohérents."""
        shell_script = (project_root / "install.sh").read_text(encoding="utf-8")
        bat_script = (project_root / "install.bat").read_text(encoding="utf-8")

        # Les deux devraient créer les mêmes répertoires
        for dir_name in ["data", "logs", "knowledge"]:
            assert dir_name in shell_script, f"{dir_name} manquant dans install.sh"
            assert dir_name in bat_script, f"{dir_name} manquant dans install.bat"

    def test_dockerfile_matches_requirements(self, project_root):
        """Test que le Dockerfile utilise requirements.txt."""
        dockerfile = (project_root / "Dockerfile").read_text(encoding="utf-8")
        requirements = project_root / "requirements.txt"

        assert requirements.exists(), "requirements.txt n'existe pas"
        assert "requirements.txt" in dockerfile, "Dockerfile n'utilise pas requirements.txt"
