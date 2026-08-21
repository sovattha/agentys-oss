# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2024-2026 Agentys contributors
"""
Dashboard web pour visualiser les statistiques Agentys.

Lance un serveur Flask local pour afficher :
- Statistiques globales
- Historique des traitements
- Usage des tokens et coûts
- Mises à jour temps réel via WebSocket

Usage avec WebSocket:
    from app.dashboard import socketio, notify_email_processed, run_dashboard

    # Notifier le dashboard d'un nouvel email traité
    notify_email_processed(email_data)

    # Lancer le serveur
    run_dashboard(host="127.0.0.1", port=5000)
"""

from datetime import datetime
from flask import Flask, render_template_string, jsonify

# flask_socketio est optionnel
try:
    from flask_socketio import SocketIO, emit
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    SocketIO = None  # type: ignore
    emit = None  # type: ignore

import os
import re
import secrets

from app.config import OUTPUTS_DIR, INPUTS_DIR, KNOWLEDGE_DIR
from app.agents import MODEL_COSTS
from app.infrastructure.container import get_container
from app.infrastructure.cost_manager import get_cost_manager
from app.infrastructure.security import get_data_retention_manager
from app.analytics import get_analytics_manager

app = Flask(__name__)
# SECURITY: Use environment variable or generate a secure random key
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)

# SocketIO pour les mises à jour temps réel (optionnel)
# SECURITY: Restrict CORS to localhost by default, configurable via env var.
# The dashboard is a single-user visualization tool (port 5000). Events emitted
# via `socketio.emit()` broadcast to all connected clients — acceptable for a
# local admin view but DANGEROUS if exposed externally. The guard below refuses
# to start the SocketIO instance if any non-localhost origin is allowed without
# an explicit opt-in (`DASHBOARD_ALLOW_REMOTE=1`).
ALLOWED_ORIGINS = os.environ.get("DASHBOARD_CORS_ORIGINS", "http://127.0.0.1:5050,http://localhost:5050").split(",")


def _is_localhost_origin(origin: str) -> bool:
    o = (origin or "").strip().lower()
    return (
        o.startswith("http://127.0.0.1")
        or o.startswith("http://localhost")
        or o.startswith("https://127.0.0.1")
        or o.startswith("https://localhost")
    )


_REMOTE_OPT_IN = os.environ.get("DASHBOARD_ALLOW_REMOTE", "").strip() in ("1", "true", "yes")
_ALL_LOCAL = all(_is_localhost_origin(o) for o in ALLOWED_ORIGINS if o)

if SOCKETIO_AVAILABLE:
    if not _ALL_LOCAL and not _REMOTE_OPT_IN:
        # Non-localhost origin detected without explicit opt-in → refuse to
        # broadcast private email events globally. Fall back to HTTP-only
        # dashboard (stats visible, but no realtime broadcasts).
        import logging as _dash_log
        _dash_log.getLogger(__name__).warning(
            "[DASHBOARD] Refusing to start SocketIO: non-localhost CORS origin "
            "detected without DASHBOARD_ALLOW_REMOTE=1 opt-in. "
            "Origins=%s", ALLOWED_ORIGINS,
        )
        socketio = None  # type: ignore
    else:
        socketio = SocketIO(app, cors_allowed_origins=ALLOWED_ORIGINS, async_mode="threading")
else:
    socketio = None  # type: ignore

# ============================================================================
# SECURITY: Input validation constants
# ============================================================================
DRAFT_ID_MAX_LENGTH = 256
DRAFT_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_\-]+$")
FEEDBACK_MAX_LENGTH = 10000  # 10KB max for feedback text


def _validate_draft_id(draft_id: str) -> bool:
    """
    Validate draft ID format.

    Security: Prevents injection attacks and limits size.

    Args:
        draft_id: The draft ID to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not draft_id or not isinstance(draft_id, str):
        return False
    if len(draft_id) > DRAFT_ID_MAX_LENGTH:
        return False
    return bool(DRAFT_ID_PATTERN.match(draft_id))


def _validate_feedback(feedback: str) -> bool:
    """
    Validate feedback text.

    Security: Prevents DoS via oversized payloads.

    Args:
        feedback: The feedback text to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not isinstance(feedback, str):
        return False
    if len(feedback) > FEEDBACK_MAX_LENGTH:
        return False
    return True


# ============================================================================
# TEMPLATES HTML
# ============================================================================

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Agentys - Dashboard</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.2/socket.io.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #e4e4e4;
            min-height: 100vh;
            padding: 2rem;
        }
        .container { max-width: 1400px; margin: 0 auto; }
        h1 {
            text-align: center;
            margin-bottom: 2rem;
            font-size: 2.5rem;
            background: linear-gradient(90deg, #00d9ff, #00ff88);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .stats-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1.5rem;
            margin-bottom: 2rem;
        }
        .stat-card {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 1.5rem;
            border: 1px solid rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
        }
        .stat-card h3 {
            color: #888;
            font-size: 0.9rem;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
            letter-spacing: 1px;
        }
        .stat-card .value {
            font-size: 2.5rem;
            font-weight: bold;
            color: #00d9ff;
        }
        .stat-card .unit {
            font-size: 1rem;
            color: #666;
            margin-left: 0.5rem;
        }
        .stat-card.success .value { color: #00ff88; }
        .stat-card.warning .value { color: #ffcc00; }
        .stat-card.cost .value { color: #ff6b6b; }
        .stat-card.time .value { color: #a855f7; }
        .stat-card.automation .value { color: #06b6d4; }

        .section {
            background: rgba(255,255,255,0.05);
            border-radius: 16px;
            padding: 1.5rem;
            margin-bottom: 2rem;
            border: 1px solid rgba(255,255,255,0.1);
        }
        .section h2 {
            margin-bottom: 1rem;
            color: #00d9ff;
            font-size: 1.3rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        .section h2 .export-btn {
            font-size: 0.8rem;
            background: rgba(255,255,255,0.1);
            border: none;
            padding: 0.5rem 1rem;
            border-radius: 8px;
            color: #00d9ff;
            cursor: pointer;
        }
        .section h2 .export-btn:hover { background: rgba(255,255,255,0.2); }

        table {
            width: 100%;
            border-collapse: collapse;
        }
        th, td {
            padding: 0.75rem;
            text-align: left;
            border-bottom: 1px solid rgba(255,255,255,0.1);
        }
        th { color: #888; font-weight: normal; text-transform: uppercase; font-size: 0.8rem; }
        tr:hover { background: rgba(255,255,255,0.05); }

        .status-badge {
            padding: 0.25rem 0.75rem;
            border-radius: 20px;
            font-size: 0.8rem;
            font-weight: bold;
        }
        .status-v1 { background: #00ff8833; color: #00ff88; }
        .status-v2 { background: #ffcc0033; color: #ffcc00; }
        .status-ignored { background: #ff6b6b33; color: #ff6b6b; }

        .refresh-btn {
            position: fixed;
            bottom: 2rem;
            right: 2rem;
            background: #00d9ff;
            color: #1a1a2e;
            border: none;
            padding: 1rem 2rem;
            border-radius: 50px;
            font-weight: bold;
            cursor: pointer;
            transition: transform 0.2s;
        }
        .refresh-btn:hover { transform: scale(1.05); }

        .model-costs {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 1rem;
        }
        .model-card {
            background: rgba(0,0,0,0.3);
            padding: 1rem;
            border-radius: 8px;
        }
        .model-card h4 { color: #00d9ff; margin-bottom: 0.5rem; }
        .model-card .prices { font-size: 0.9rem; color: #888; }

        .empty-state {
            text-align: center;
            padding: 3rem;
            color: #666;
        }
        .empty-state .icon { font-size: 4rem; margin-bottom: 1rem; }

        /* Live indicator */
        .live-indicator {
            font-size: 0.9rem;
            padding: 0.3rem 0.8rem;
            border-radius: 20px;
            background: rgba(0, 255, 136, 0.2);
            color: #00ff88;
            animation: pulse 2s infinite;
            vertical-align: middle;
            margin-left: 1rem;
        }
        .live-indicator.disconnected {
            background: rgba(255, 107, 107, 0.2);
            color: #ff6b6b;
            animation: none;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }

        /* Toast notifications */
        .toast-container {
            position: fixed;
            top: 1rem;
            right: 1rem;
            z-index: 9999;
        }
        .toast {
            background: rgba(0, 217, 255, 0.95);
            color: #1a1a2e;
            padding: 1rem 1.5rem;
            border-radius: 8px;
            margin-bottom: 0.5rem;
            animation: slideIn 0.3s ease;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
        }
        .toast.success { background: rgba(0, 255, 136, 0.95); }
        .toast.error { background: rgba(255, 107, 107, 0.95); color: #fff; }
        @keyframes slideIn {
            from { transform: translateX(100%); opacity: 0; }
            to { transform: translateX(0); opacity: 1; }
        }

        .charts-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
            gap: 1.5rem;
        }
        .chart-container {
            background: rgba(0,0,0,0.2);
            border-radius: 12px;
            padding: 1rem;
            height: 300px;
        }
        .chart-container h4 {
            color: #888;
            font-size: 0.9rem;
            margin-bottom: 0.5rem;
            text-transform: uppercase;
        }
    </style>
</head>
<body>
    <!-- Toast container for notifications -->
    <div id="toast-container" class="toast-container"></div>

    <div class="container">
        <h1>🤖 Agentys Dashboard <span id="live-indicator" class="live-indicator" title="Connexion temps réel">⚡ Live</span></h1>

        <!-- Stats avancées -->
        <div class="stats-grid">
            <div class="stat-card" id="stat-total">
                <h3>Emails traités</h3>
                <span class="value" id="value-total">{{ draft_stats.total }}</span>
            </div>
            <div class="stat-card success" id="stat-v1">
                <h3>Validés V1</h3>
                <span class="value" id="value-v1">{{ draft_stats.validated_v1 }}</span>
                <span class="unit" id="unit-v1">({{ draft_stats.v1_percent }}%)</span>
            </div>
            <div class="stat-card warning" id="stat-v2">
                <h3>Corrigés V2</h3>
                <span class="value" id="value-v2">{{ draft_stats.corrected_v2 }}</span>
                <span class="unit" id="unit-v2">({{ draft_stats.v2_percent }}%)</span>
            </div>
            <div class="stat-card time" id="stat-time-saved">
                <h3>Temps économisé</h3>
                <span class="value" id="value-time-saved">{{ draft_stats.time_saved_hours }}</span>
                <span class="unit">heures</span>
            </div>
            <div class="stat-card automation" id="stat-automation">
                <h3>Taux automatisation</h3>
                <span class="value" id="value-automation">{{ draft_stats.automation_rate }}</span>
                <span class="unit">%</span>
            </div>
            <div class="stat-card" id="stat-avg-time">
                <h3>Temps moyen</h3>
                <span class="value" id="value-avg-time">{{ draft_stats.avg_processing_time_sec }}</span>
                <span class="unit">sec/email</span>
            </div>
            <div class="stat-card" id="stat-tokens">
                <h3>Tokens utilisés</h3>
                <span class="value" id="value-tokens">{{ "{:,}".format(draft_stats.total_tokens) }}</span>
            </div>
            <div class="stat-card cost" id="stat-cost">
                <h3>Coût estimé</h3>
                <span class="value" id="value-cost">${{ stats.total_cost }}</span>
            </div>
        </div>

        <!-- Graphiques -->
        <div class="section">
            <h2>📈 Évolution</h2>
            <div class="charts-grid">
                <div class="chart-container">
                    <h4>Emails par jour</h4>
                    <canvas id="dailyChart"></canvas>
                </div>
                <div class="chart-container">
                    <h4>Répartition V1/V2</h4>
                    <canvas id="pieChart"></canvas>
                </div>
            </div>
        </div>

        <div class="section">
            <h2>📊 Historique des traitements</h2>
            {% if history %}
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Fichier</th>
                        <th>Emails</th>
                        <th>V1</th>
                        <th>V2</th>
                        <th>Ignorés</th>
                    </tr>
                </thead>
                <tbody>
                    {% for item in history %}
                    <tr>
                        <td>{{ item.date }}</td>
                        <td>{{ item.filename }}</td>
                        <td>{{ item.total }}</td>
                        <td><span class="status-badge status-v1">{{ item.v1 }}</span></td>
                        <td><span class="status-badge status-v2">{{ item.v2 }}</span></td>
                        <td><span class="status-badge status-ignored">{{ item.ignored }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="empty-state">
                <div class="icon">📭</div>
                <p>Aucun traitement effectué pour le moment.</p>
                <p>Lancez <code>python -m app.main</code> pour traiter des emails.</p>
            </div>
            {% endif %}
        </div>

        <div class="section">
            <h2>💰 Coûts des modèles (par million de tokens)</h2>
            <div class="model-costs">
                {% for model, costs in model_costs.items() %}
                <div class="model-card">
                    <h4>{{ model.split('-')[1] | title }}</h4>
                    <div class="prices">
                        Input: ${{ costs.input }}<br>
                        Output: ${{ costs.output }}
                    </div>
                </div>
                {% endfor %}
            </div>
        </div>

        <div class="section">
            <h2>
                📝 Brouillons récents (Mode Apprentissage)
                <button class="export-btn" onclick="exportCSV()">📥 Export CSV</button>
            </h2>
            {% if drafts %}
            <table>
                <thead>
                    <tr>
                        <th>Date</th>
                        <th>Expéditeur</th>
                        <th>Sujet</th>
                        <th>Status</th>
                        <th>Note</th>
                        <th>Actions</th>
                    </tr>
                </thead>
                <tbody>
                    {% for draft in drafts %}
                    <tr>
                        <td>{{ draft.timestamp[:16] }}</td>
                        <td>{{ draft.email_sender[:30] }}</td>
                        <td>{{ draft.email_subject[:40] }}{% if draft.email_subject|length > 40 %}...{% endif %}</td>
                        <td>
                            {% if 'V1' in draft.status %}
                            <span class="status-badge status-v1">V1</span>
                            {% else %}
                            <span class="status-badge status-v2">V2</span>
                            {% endif %}
                        </td>
                        <td>
                            <div class="rating" data-id="{{ draft.id }}">
                                {% for i in range(1, 6) %}
                                <span class="star {% if draft.feedback_rating and i <= draft.feedback_rating %}active{% endif %}"
                                      data-value="{{ i }}" onclick="rate('{{ draft.id }}', {{ i }})">★</span>
                                {% endfor %}
                            </div>
                        </td>
                        <td>
                            <button class="view-btn" onclick="viewDraft('{{ draft.id }}')">👁️</button>
                        </td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% else %}
            <div class="empty-state">
                <div class="icon">📝</div>
                <p>Aucun brouillon généré par le daemon.</p>
                <p>Lancez <code>python run_daemon.py</code> pour commencer.</p>
            </div>
            {% endif %}
        </div>


        <!-- Section Learning -->
        <div class="section">
            <h2>🧠 Apprentissage</h2>
            <div class="stats-grid" style="margin-bottom: 1rem;">
                <div class="stat-card automation">
                    <h3>Patterns actifs</h3>
                    <span class="value">{{ learning_stats.patterns_count }}</span>
                </div>
                <div class="stat-card success">
                    <h3>Ajustements appliqués</h3>
                    <span class="value">{{ learning_stats.active_adjustments }}</span>
                </div>
                <div class="stat-card">
                    <h3>Emails analysés</h3>
                    <span class="value">{{ learning_stats.analyzed_emails }}</span>
                </div>
            </div>
            {% if learning_stats.top_patterns %}
            <h4 style="color: #888; margin: 1rem 0 0.5rem;">Top Patterns</h4>
            <table>
                <thead><tr><th>Type</th><th>Pattern</th><th>Occurrences</th></tr></thead>
                <tbody>
                    {% for p in learning_stats.top_patterns %}
                    <tr>
                        <td>{{ p.type }}</td>
                        <td>{{ p.value[:50] }}{% if p.value|length > 50 %}...{% endif %}</td>
                        <td>{{ p.occurrences }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% endif %}
        </div>

        <!-- Section Coûts détaillés -->
        <div class="section">
            <h2>💰 Gestion des Coûts</h2>
            <div class="stats-grid" style="margin-bottom: 1rem;">
                <div class="stat-card cost">
                    <h3>Coût ce mois</h3>
                    <span class="value">${{ cost_stats.current_month_cost }}</span>
                </div>
                {% if cost_stats.monthly_budget %}
                <div class="stat-card {% if cost_stats.usage_percentage > 80 %}warning{% endif %}">
                    <h3>Budget utilisé</h3>
                    <span class="value">{{ cost_stats.usage_percentage }}</span>
                    <span class="unit">%</span>
                </div>
                <div class="stat-card">
                    <h3>Budget restant</h3>
                    <span class="value">${{ cost_stats.remaining_budget }}</span>
                </div>
                {% endif %}
                <div class="stat-card">
                    <h3>Requêtes API</h3>
                    <span class="value">{{ cost_stats.total_requests }}</span>
                </div>
            </div>
            {% if cost_stats.by_agent %}
            <h4 style="color: #888; margin: 1rem 0 0.5rem;">Coûts par Agent</h4>
            <table>
                <thead><tr><th>Agent</th><th>Coût</th><th>Requêtes</th><th>% du total</th></tr></thead>
                <tbody>
                    {% for agent, data in cost_stats.by_agent.items() %}
                    <tr>
                        <td>{{ agent }}</td>
                        <td>${{ "%.4f"|format(data.cost_usd) }}</td>
                        <td>{{ data.request_count }}</td>
                        <td>{{ "%.1f"|format(data.percentage) }}%</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
            {% endif %}
        </div>

        <!-- Section Catégories -->
        <div class="section">
            <h2>📊 Breakdown par Catégorie</h2>
            <div class="charts-grid">
                <div class="chart-container">
                    <h4>Répartition des emails</h4>
                    <canvas id="categoryChart"></canvas>
                </div>
                <div style="padding: 1rem;">
                    <table>
                        <thead><tr><th>Catégorie</th><th>Nombre</th><th>%</th></tr></thead>
                        <tbody>
                            {% for cat, count in category_breakdown.items() %}
                            <tr>
                                <td>
                                    <span class="status-badge" style="background: {% if cat == 'URGENT' %}#ff6b6b33; color: #ff6b6b{% elif cat == 'IMPORTANT' %}#ffcc0033; color: #ffcc00{% elif cat == 'NORMAL' %}#00d9ff33; color: #00d9ff{% else %}#88888833; color: #888{% endif %}">
                                        {{ cat }}
                                    </span>
                                </td>
                                <td>{{ count }}</td>
                                <td>{{ "%.1f"|format(count / (category_total or 1) * 100) }}%</td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>

        <!-- ROI Calculator -->
        <div class="section">
            <h2>📈 ROI - Retour sur Investissement</h2>
            <div class="stats-grid">
                <div class="stat-card time">
                    <h3>Temps économisé</h3>
                    <span class="value">{{ roi.time_saved_hours }}</span>
                    <span class="unit">heures</span>
                </div>
                <div class="stat-card success">
                    <h3>Valeur générée</h3>
                    <span class="value">${{ roi.value_generated }}</span>
                    <span class="unit">(@${{ roi.hourly_rate }}/h)</span>
                </div>
                <div class="stat-card cost">
                    <h3>Coût total</h3>
                    <span class="value">${{ roi.total_cost }}</span>
                </div>
                <div class="stat-card automation">
                    <h3>ROI</h3>
                    <span class="value">{{ roi.roi_percent }}</span>
                    <span class="unit">%</span>
                </div>
            </div>
            <p style="color: #666; margin-top: 1rem; font-size: 0.9rem;">
                * Estimation basée sur {{ roi.avg_time_per_email }} min/email manuellement vs {{ roi.ai_time_per_email }} sec avec l'IA
            </p>
        </div>

        <!-- Section Analytics - Comparaison IA vs Humain -->
        <div class="section">
            <h2>🔬 Analytics - Comparaison IA vs Humain</h2>
            <div class="stats-grid" style="margin-bottom: 1rem;">
                <div class="stat-card">
                    <h3>Total éditions</h3>
                    <span class="value">{{ analytics.comparison.total_edits }}</span>
                </div>
                <div class="stat-card automation">
                    <h3>Similarité moyenne</h3>
                    <span class="value">{{ analytics.comparison.avg_similarity }}</span>
                    <span class="unit">%</span>
                </div>
                <div class="stat-card {% if analytics.comparison.avg_edit_ratio > 30 %}warning{% else %}success{% endif %}">
                    <h3>Taux modification</h3>
                    <span class="value">{{ analytics.comparison.avg_edit_ratio }}</span>
                    <span class="unit">%</span>
                </div>
            </div>
            {% if analytics.comparison.distribution %}
            <div class="charts-grid">
                <div class="chart-container">
                    <h4>Distribution des modifications</h4>
                    <canvas id="editDistributionChart"></canvas>
                </div>
                <div style="padding: 1rem;">
                    <h4 style="color: #888; margin-bottom: 0.5rem;">Répartition</h4>
                    <table>
                        <tr>
                            <td><span class="status-badge status-v1">Sans modification</span></td>
                            <td>{{ analytics.comparison.distribution.no_change }}</td>
                        </tr>
                        <tr>
                            <td><span class="status-badge" style="background: #00d9ff33; color: #00d9ff;">Mineure (&lt;20%)</span></td>
                            <td>{{ analytics.comparison.distribution.minor }}</td>
                        </tr>
                        <tr>
                            <td><span class="status-badge status-v2">Modérée (20-50%)</span></td>
                            <td>{{ analytics.comparison.distribution.moderate }}</td>
                        </tr>
                        <tr>
                            <td><span class="status-badge status-ignored">Majeure (&gt;50%)</span></td>
                            <td>{{ analytics.comparison.distribution.major }}</td>
                        </tr>
                    </table>
                </div>
            </div>
            {% endif %}
        </div>

        <!-- Section Analytics - Qualité des réponses -->
        <div class="section">
            <h2>📊 Analytics - Qualité des Réponses</h2>
            <div class="stats-grid" style="margin-bottom: 1rem;">
                <div class="stat-card">
                    <h3>Brouillons notés</h3>
                    <span class="value">{{ analytics.quality.total_scored }}</span>
                </div>
                <div class="stat-card {% if analytics.quality.avg_overall_score >= 75 %}success{% elif analytics.quality.avg_overall_score >= 50 %}warning{% else %}cost{% endif %}">
                    <h3>Score moyen</h3>
                    <span class="value">{{ analytics.quality.avg_overall_score }}</span>
                    <span class="unit">/100</span>
                </div>
                <div class="stat-card automation">
                    <h3>Note utilisateur</h3>
                    <span class="value">{{ analytics.quality.avg_user_rating }}</span>
                    <span class="unit">/5</span>
                </div>
                <div class="stat-card {% if analytics.performance.improvement_trend >= 0 %}success{% else %}cost{% endif %}">
                    <h3>Tendance</h3>
                    <span class="value">{% if analytics.performance.improvement_trend >= 0 %}↗{% else %}↘{% endif %} {{ analytics.performance.improvement_trend|abs }}</span>
                </div>
            </div>
            {% if analytics.quality.score_distribution %}
            <div class="charts-grid">
                <div class="chart-container">
                    <h4>Distribution des scores de qualité</h4>
                    <canvas id="qualityDistributionChart"></canvas>
                </div>
                <div style="padding: 1rem;">
                    <h4 style="color: #888; margin-bottom: 0.5rem;">Répartition</h4>
                    <table>
                        <tr>
                            <td><span class="status-badge" style="background: #00ff8833; color: #00ff88;">Excellent (≥90)</span></td>
                            <td>{{ analytics.quality.score_distribution.excellent }}</td>
                        </tr>
                        <tr>
                            <td><span class="status-badge" style="background: #00d9ff33; color: #00d9ff;">Bon (75-90)</span></td>
                            <td>{{ analytics.quality.score_distribution.good }}</td>
                        </tr>
                        <tr>
                            <td><span class="status-badge status-v2">Acceptable (50-75)</span></td>
                            <td>{{ analytics.quality.score_distribution.acceptable }}</td>
                        </tr>
                        <tr>
                            <td><span class="status-badge status-ignored">À améliorer (&lt;50)</span></td>
                            <td>{{ analytics.quality.score_distribution.needs_improvement }}</td>
                        </tr>
                    </table>
                    {% if analytics.recommendations %}
                    <h4 style="color: #888; margin: 1rem 0 0.5rem;">Recommandations</h4>
                    <ul style="color: #888; font-size: 0.9rem; padding-left: 1.5rem;">
                        {% for rec in analytics.recommendations %}
                        <li style="margin-bottom: 0.5rem;">{{ rec }}</li>
                        {% endfor %}
                    </ul>
                    {% endif %}
                </div>
            </div>
            {% endif %}
        </div>

        <!-- Section Rétention données (RGPD) -->
        <div class="section">
            <h2>🔒 Rétention des Données (RGPD)</h2>
            <table>
                {% for table, info in retention_stats.items() %}
                <tr>
                    <td>{{ table }}</td>
                    <td>{{ info.total_records }} enregistrements</td>
                    <td>Rétention: {{ info.retention_days }} jours</td>
                    <td>
                        {% if info.expiring_soon > 0 %}
                        <span class="status-badge status-v2">{{ info.expiring_soon }} expirent bientôt</span>
                        {% else %}
                        <span style="color: #00ff88;">OK</span>
                        {% endif %}
                    </td>
                </tr>
                {% endfor %}
            </table>
        </div>

        <div class="section">
            <h2>📁 Configuration</h2>
            <table>
                <tr><td>Dossier inputs</td><td><code>{{ config.inputs_dir }}</code></td></tr>
                <tr><td>Dossier outputs</td><td><code>{{ config.outputs_dir }}</code></td></tr>
                <tr><td>Knowledge base</td><td><code>{{ config.knowledge_file }}</code> ({{ config.knowledge_size }} chars)</td></tr>
                <tr><td>Corpus emails</td><td>{{ config.corpus_count }} emails</td></tr>
            </table>
        </div>
    </div>

    <!-- Modal pour voir le brouillon -->
    <div id="draftModal" class="modal" style="display:none;">
        <div class="modal-content">
            <span class="close" onclick="closeModal()">&times;</span>
            <h3 id="modalTitle">Brouillon</h3>
            <div class="modal-section">
                <h4>Email reçu</h4>
                <pre id="modalEmail"></pre>
            </div>
            <div class="modal-section">
                <h4>Réponse générée</h4>
                <pre id="modalDraft"></pre>
            </div>
            <div class="modal-section">
                <h4>Critique</h4>
                <pre id="modalCritique"></pre>
            </div>
            <div class="feedback-section">
                <h4>Feedback</h4>
                <textarea id="modalFeedback" placeholder="Votre feedback pour améliorer les réponses..."></textarea>
                <button onclick="saveFeedback()">💾 Sauvegarder</button>
            </div>
        </div>
    </div>

    <button class="refresh-btn" onclick="location.reload()">🔄 Actualiser</button>

    <style>
        .star { cursor: pointer; color: #444; font-size: 1.2rem; }
        .star:hover, .star.active { color: #ffcc00; }
        .view-btn { background: #00d9ff33; border: none; padding: 0.3rem 0.5rem; border-radius: 4px; cursor: pointer; }

        .modal { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.8); z-index: 1000; display: flex; align-items: center; justify-content: center; }
        .modal-content { background: #1a1a2e; padding: 2rem; border-radius: 16px; max-width: 800px; max-height: 80vh; overflow-y: auto; width: 90%; }
        .modal-content h3 { color: #00d9ff; margin-bottom: 1rem; }
        .modal-section { margin-bottom: 1.5rem; }
        .modal-section h4 { color: #888; margin-bottom: 0.5rem; }
        .modal-section pre { background: rgba(0,0,0,0.3); padding: 1rem; border-radius: 8px; white-space: pre-wrap; max-height: 200px; overflow-y: auto; }
        .close { float: right; font-size: 2rem; cursor: pointer; color: #888; }
        .close:hover { color: #fff; }
        .feedback-section textarea { width: 100%; height: 80px; background: rgba(0,0,0,0.3); border: 1px solid #333; border-radius: 8px; padding: 0.5rem; color: #fff; margin-bottom: 0.5rem; }
        .feedback-section button { background: #00ff88; color: #1a1a2e; border: none; padding: 0.5rem 1rem; border-radius: 4px; cursor: pointer; font-weight: bold; }
    </style>

    <script>
        let currentDraftId = null;

        // Données pour les graphiques
        const dailyStats = {{ daily_stats | tojson }};

        // Initialiser les graphiques au chargement
        document.addEventListener('DOMContentLoaded', function() {
            initCharts();
        });

        function initCharts() {
            // Graphique des emails par jour
            if (dailyStats.length > 0) {
                new Chart(document.getElementById('dailyChart'), {
                    type: 'line',
                    data: {
                        labels: dailyStats.map(d => d.date.slice(5)),  // MM-DD
                        datasets: [
                            {
                                label: 'Total',
                                data: dailyStats.map(d => d.total),
                                borderColor: '#00d9ff',
                                backgroundColor: 'rgba(0, 217, 255, 0.1)',
                                fill: true,
                                tension: 0.4
                            },
                            {
                                label: 'V1',
                                data: dailyStats.map(d => d.v1),
                                borderColor: '#00ff88',
                                backgroundColor: 'transparent',
                                tension: 0.4
                            },
                            {
                                label: 'V2',
                                data: dailyStats.map(d => d.v2),
                                borderColor: '#ffcc00',
                                backgroundColor: 'transparent',
                                tension: 0.4
                            }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { labels: { color: '#888' } } },
                        scales: {
                            x: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.1)' } },
                            y: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.1)' } }
                        }
                    }
                });
            }

            // Graphique circulaire V1/V2
            const v1 = {{ draft_stats.validated_v1 }};
            const v2 = {{ draft_stats.corrected_v2 }};
            if (v1 > 0 || v2 > 0) {
                new Chart(document.getElementById('pieChart'), {
                    type: 'doughnut',
                    data: {
                        labels: ['Validés V1', 'Corrigés V2'],
                        datasets: [{
                            data: [v1, v2],
                            backgroundColor: ['#00ff88', '#ffcc00'],
                            borderWidth: 0
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'bottom',
                                labels: { color: '#888' }
                            }
                        }
                    }
                });
            }

            // Graphique des catégories
            const categoryData = {{ category_breakdown | tojson }};
            const categoryLabels = Object.keys(categoryData);
            const categoryValues = Object.values(categoryData);
            const categoryColors = {
                'URGENT': '#ff6b6b',
                'IMPORTANT': '#ffcc00',
                'NORMAL': '#00d9ff',
                'NEWSLETTER': '#888888',
                'PROMO': '#a855f7',
                'SPAM': '#333333',
                'CC_ONLY': '#666666'
            };
            if (categoryLabels.length > 0) {
                new Chart(document.getElementById('categoryChart'), {
                    type: 'doughnut',
                    data: {
                        labels: categoryLabels,
                        datasets: [{
                            data: categoryValues,
                            backgroundColor: categoryLabels.map(l => categoryColors[l] || '#888'),
                            borderWidth: 0
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'right',
                                labels: { color: '#888' }
                            }
                        }
                    }
                });
            }

            // Graphique distribution des modifications (Analytics)
            const editDistribution = {{ analytics.comparison.distribution | tojson }};
            const editCanvas = document.getElementById('editDistributionChart');
            if (editCanvas && Object.keys(editDistribution).length > 0) {
                new Chart(editCanvas, {
                    type: 'bar',
                    data: {
                        labels: ['Sans modif', 'Mineure', 'Modérée', 'Majeure'],
                        datasets: [{
                            label: 'Nombre de brouillons',
                            data: [
                                editDistribution.no_change || 0,
                                editDistribution.minor || 0,
                                editDistribution.moderate || 0,
                                editDistribution.major || 0
                            ],
                            backgroundColor: ['#00ff88', '#00d9ff', '#ffcc00', '#ff6b6b'],
                            borderWidth: 0
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: { legend: { display: false } },
                        scales: {
                            x: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.1)' } },
                            y: { ticks: { color: '#888' }, grid: { color: 'rgba(255,255,255,0.1)' } }
                        }
                    }
                });
            }

            // Graphique distribution qualité
            const qualityDistribution = {{ analytics.quality.score_distribution | tojson }};
            const qualityCanvas = document.getElementById('qualityDistributionChart');
            if (qualityCanvas && Object.keys(qualityDistribution).length > 0) {
                new Chart(qualityCanvas, {
                    type: 'doughnut',
                    data: {
                        labels: ['Excellent', 'Bon', 'Acceptable', 'À améliorer'],
                        datasets: [{
                            data: [
                                qualityDistribution.excellent || 0,
                                qualityDistribution.good || 0,
                                qualityDistribution.acceptable || 0,
                                qualityDistribution.needs_improvement || 0
                            ],
                            backgroundColor: ['#00ff88', '#00d9ff', '#ffcc00', '#ff6b6b'],
                            borderWidth: 0
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: {
                                position: 'bottom',
                                labels: { color: '#888' }
                            }
                        }
                    }
                });
            }
        }

        function rate(id, value) {
            fetch('/api/feedback', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: id, rating: value, feedback: ''})
            }).then(() => {
                document.querySelectorAll(`.rating[data-id="${id}"] .star`).forEach((star, i) => {
                    star.classList.toggle('active', i < value);
                });
            });
        }

        function viewDraft(id) {
            currentDraftId = id;
            fetch('/api/draft/' + id)
                .then(r => r.json())
                .then(data => {
                    document.getElementById('modalTitle').textContent = data.email_subject;
                    document.getElementById('modalEmail').textContent = data.email_preview;
                    document.getElementById('modalDraft').textContent = data.draft_final;
                    document.getElementById('modalCritique').textContent = data.critique;
                    document.getElementById('modalFeedback').value = data.feedback || '';
                    document.getElementById('draftModal').style.display = 'flex';
                });
        }

        function closeModal() {
            document.getElementById('draftModal').style.display = 'none';
        }

        function saveFeedback() {
            const feedback = document.getElementById('modalFeedback').value;
            fetch('/api/feedback', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({id: currentDraftId, feedback: feedback})
            }).then(() => closeModal());
        }

        function exportCSV() {
            window.location.href = '/api/export-csv';
        }

        // ========================================
        // WebSocket Real-time Updates
        // ========================================

        const socket = io();
        const liveIndicator = document.getElementById('live-indicator');
        const toastContainer = document.getElementById('toast-container');

        // Connection events
        socket.on('connect', function() {
            console.log('WebSocket connected');
            liveIndicator.classList.remove('disconnected');
            liveIndicator.innerHTML = '⚡ Live';
            showToast('Connexion temps réel établie', 'success');
        });

        socket.on('disconnect', function() {
            console.log('WebSocket disconnected');
            liveIndicator.classList.add('disconnected');
            liveIndicator.innerHTML = '⚠️ Déconnecté';
        });

        socket.on('connect_error', function() {
            liveIndicator.classList.add('disconnected');
            liveIndicator.innerHTML = '⚠️ Erreur';
        });

        // Real-time stats update
        socket.on('stats_update', function(data) {
            console.log('Stats update received:', data);

            // Update stat values with animation
            updateStatWithAnimation('value-total', data.total);
            updateStatWithAnimation('value-v1', data.validated_v1);
            updateStatWithAnimation('value-v2', data.corrected_v2);
            updateStatWithAnimation('value-automation', data.automation_rate);

            // Update percentages
            const unitV1 = document.getElementById('unit-v1');
            const unitV2 = document.getElementById('unit-v2');
            if (unitV1) unitV1.textContent = '(' + data.v1_percent + '%)';
            if (unitV2) unitV2.textContent = '(' + data.v2_percent + '%)';
        });

        // New email processed notification
        socket.on('email_processed', function(data) {
            console.log('Email processed:', data);
            showToast('📧 ' + data.subject + ' - ' + data.status, 'success');

            // Refresh stats
            socket.emit('request_stats');
        });

        // New draft created
        socket.on('draft_created', function(data) {
            console.log('Draft created:', data);
            showToast('✉️ Brouillon créé: ' + data.subject, 'success');
        });

        // Error notification
        socket.on('error_notification', function(data) {
            console.log('Error:', data);
            showToast('❌ ' + data.message, 'error');
        });

        // Budget alert
        socket.on('budget_alert', function(data) {
            console.log('Budget alert:', data);
            showToast('⚠️ Budget: ' + data.usage_percent + '% utilisé', 'error');
        });

        // Helpers
        function updateStatWithAnimation(elementId, newValue) {
            const element = document.getElementById(elementId);
            if (element) {
                element.style.transition = 'transform 0.3s, color 0.3s';
                element.style.transform = 'scale(1.2)';
                element.style.color = '#00ff88';

                setTimeout(() => {
                    element.textContent = typeof newValue === 'number' ?
                        newValue.toLocaleString() : newValue;
                    element.style.transform = 'scale(1)';
                    element.style.color = '';
                }, 150);
            }
        }

        function showToast(message, type = 'info') {
            const toast = document.createElement('div');
            toast.className = 'toast ' + type;
            toast.textContent = message;
            toastContainer.appendChild(toast);

            // Auto-remove after 5 seconds
            setTimeout(() => {
                toast.style.animation = 'slideIn 0.3s ease reverse';
                setTimeout(() => toast.remove(), 300);
            }, 5000);
        }

        // Request initial stats on page load
        socket.on('connect', function() {
            socket.emit('request_stats');
        });
    </script>
</body>
</html>
"""

# ============================================================================
# FONCTIONS UTILITAIRES
# ============================================================================

def get_stats() -> dict:
    """Calcule les statistiques globales."""
    stats = {
        "total_emails": 0,
        "validated_v1": 0,
        "corrected_v2": 0,
        "ignored": 0,
        "v1_percent": 0,
        "v2_percent": 0,
        "total_tokens": 0,
        "total_tokens_formatted": "0",
        "total_cost": "0.00",
        "current_model": "opus",
    }

    # Lire les fichiers de sortie
    output_files = list(OUTPUTS_DIR.glob("*.xlsx")) if OUTPUTS_DIR.exists() else []

    for file in output_files:
        try:
            import pandas as pd
        except ImportError:
            break  # pandas non disponible, skip Excel parsing
        try:
            df = pd.read_excel(file)
            if "Status" in df.columns:
                stats["total_emails"] += len(df)
                stats["validated_v1"] += len(df[df["Status"].str.contains("V1", na=False)])
                stats["corrected_v2"] += len(df[df["Status"].str.contains("V2", na=False)])
                stats["ignored"] += len(df[df["Status"].str.contains("IGNORÉ", na=False)])
        except Exception:
            continue

    # Calculer les pourcentages
    if stats["total_emails"] > 0:
        stats["v1_percent"] = round(stats["validated_v1"] / stats["total_emails"] * 100)
        stats["v2_percent"] = round(stats["corrected_v2"] / stats["total_emails"] * 100)

    # Estimer les tokens (approximation)
    stats["total_tokens"] = stats["total_emails"] * 3000  # ~3000 tokens par email
    stats["total_tokens_formatted"] = f"{stats['total_tokens']:,}"

    # Calculer le coût (avec Opus par défaut)
    opus_costs = MODEL_COSTS.get("claude-opus-4-7", {"input": 15, "output": 75})
    input_tokens = stats["total_tokens"] * 0.8
    output_tokens = stats["total_tokens"] * 0.2
    cost = (input_tokens * opus_costs["input"] + output_tokens * opus_costs["output"]) / 1_000_000
    stats["total_cost"] = f"{cost:.2f}"

    return stats


def get_history() -> list:
    """Récupère l'historique des traitements."""
    history = []
    output_files = sorted(OUTPUTS_DIR.glob("*.xlsx"), reverse=True) if OUTPUTS_DIR.exists() else []

    for file in output_files[:10]:  # 10 derniers
        try:
            import pandas as pd
        except ImportError:
            break  # pandas non disponible, skip Excel parsing
        try:
            df = pd.read_excel(file)
            if "Status" in df.columns:
                history.append({
                    "date": file.stem.replace("rapport_", "").replace("test_agents_results", "test"),
                    "filename": file.name,
                    "total": len(df),
                    "v1": len(df[df["Status"].str.contains("V1", na=False)]),
                    "v2": len(df[df["Status"].str.contains("V2", na=False)]),
                    "ignored": len(df[df["Status"].str.contains("IGNORÉ", na=False)]) if "IGNORÉ" in str(df["Status"].values) else 0,
                })
        except Exception:
            continue

    return history


def get_config() -> dict:
    """Récupère la configuration actuelle."""
    knowledge_file = KNOWLEDGE_DIR / "memoire.md"
    knowledge_size = 0
    if knowledge_file.exists():
        knowledge_size = len(knowledge_file.read_text(encoding="utf-8"))

    corpus_file = INPUTS_DIR / "emails_corpus.xlsx"
    corpus_count = 0
    if corpus_file.exists():
        try:
            import pandas as pd
            df = pd.read_excel(corpus_file)
            corpus_count = len(df)
        except ImportError:
            pass  # pandas non disponible, skip corpus count
        except Exception:
            pass

    return {
        "inputs_dir": str(INPUTS_DIR),
        "outputs_dir": str(OUTPUTS_DIR),
        "knowledge_file": str(knowledge_file),
        "knowledge_size": knowledge_size,
        "corpus_count": corpus_count,
    }


# ============================================================================
# ROUTES
# ============================================================================

def get_learning_stats() -> dict:
    """Récupère les statistiques du learning via LearningService (Clean Architecture)."""
    try:
        container = get_container()
        service = container.get_learning_service()
        stats = service.get_stats()
        return {
            "patterns_count": stats.get("patterns_count", 0),
            "active_adjustments": stats.get("active_adjustments", 0),
            "analyzed_emails": stats.get("total_with_feedback", 0),
            "top_patterns": stats.get("top_patterns", [])[:5],
        }
    except Exception:
        return {"patterns_count": 0, "active_adjustments": 0, "analyzed_emails": 0, "top_patterns": []}


def get_cost_stats() -> dict:
    """Récupère les statistiques des coûts."""
    try:
        manager = get_cost_manager()
        stats = manager.get_stats()
        return {
            "current_month_cost": f"{stats.get('current_month_cost', 0):.2f}",
            "monthly_budget": stats.get('monthly_budget'),
            "remaining_budget": f"{stats.get('remaining_budget', 0):.2f}" if stats.get('remaining_budget') else None,
            "usage_percentage": f"{stats.get('usage_percentage', 0):.1f}",
            "total_requests": stats.get('total_requests', 0),
            "by_agent": stats.get('by_agent', {}),
            "by_model": stats.get('by_model', {}),
        }
    except Exception:
        return {"current_month_cost": "0.00", "total_requests": 0, "by_agent": {}, "by_model": {}}


def get_category_breakdown() -> dict:
    """Récupère le breakdown par catégorie via le container (Clean Architecture)."""
    try:
        container = get_container()
        history = container.get_draft_history()
        stats = history.get_stats()
        return stats.get("by_category", {})
    except Exception:
        return {}


def get_retention_stats() -> dict:
    """Récupère les statistiques de rétention."""
    try:
        manager = get_data_retention_manager()
        return manager.get_retention_stats()
    except Exception:
        return {}


def get_analytics_stats() -> dict:
    """Récupère les statistiques d'analytics (comparaison IA/humain, qualité)."""
    try:
        manager = get_analytics_manager()
        summary = manager.get_analytics_summary()
        return {
            "quality": summary.get("quality", {
                "total_scored": 0,
                "avg_overall_score": 0,
                "avg_user_rating": 0,
                "score_distribution": {},
            }),
            "comparison": summary.get("comparison", {
                "total_edits": 0,
                "avg_edit_ratio": 0,
                "avg_similarity": 100,
                "distribution": {},
            }),
            "performance": summary.get("performance", {
                "improvement_trend": 0,
            }),
            "recommendations": summary.get("recommendations", []),
        }
    except Exception:
        return {
            "quality": {"total_scored": 0, "avg_overall_score": 0, "avg_user_rating": 0, "score_distribution": {}},
            "comparison": {"total_edits": 0, "avg_edit_ratio": 0, "avg_similarity": 100, "distribution": {}},
            "performance": {"improvement_trend": 0},
            "recommendations": [],
        }


def calculate_roi(draft_stats: dict, cost_stats: dict) -> dict:
    """Calcule le retour sur investissement."""
    total_emails = draft_stats.get("total", 0)

    # Paramètres ROI
    avg_time_per_email_manual = 3  # minutes
    avg_time_per_email_ai = 10  # secondes
    hourly_rate = 50  # $/heure

    # Calculs
    time_saved_minutes = total_emails * (avg_time_per_email_manual - avg_time_per_email_ai / 60)
    time_saved_hours = round(time_saved_minutes / 60, 1)
    value_generated = round(time_saved_hours * hourly_rate, 2)

    try:
        total_cost = float(cost_stats.get("current_month_cost", "0").replace("$", ""))
    except (ValueError, AttributeError):
        total_cost = 0

    roi_percent = round((value_generated / total_cost - 1) * 100) if total_cost > 0 else 0

    return {
        "time_saved_hours": time_saved_hours,
        "value_generated": value_generated,
        "total_cost": f"{total_cost:.2f}",
        "roi_percent": roi_percent,
        "hourly_rate": hourly_rate,
        "avg_time_per_email": avg_time_per_email_manual,
        "ai_time_per_email": avg_time_per_email_ai,
    }


def _dashboard_current_account_id() -> int:
    """Résout l'account_id du dashboard legacy (mode Tauri mono-compte).

    Renvoie -1 si aucun compte courant — les listes scoped retournent alors
    des résultats vides au lieu de fuir entre comptes.

    M-3 audit (2026-04-25): this dashboard is the legacy Tauri-only HTML
    surface (single-user install). The singleton call is acceptable here
    because the desktop process binds to a single account, but if this
    surface is ever re-used in a multi-tenant deployment it MUST move
    to a JWT-resolved account_id like the REST routes do.
    """
    try:
        from app.multi_accounts import get_current_account
        _acct = get_current_account()
        if _acct and hasattr(_acct, "id") and isinstance(_acct.id, int):
            return _acct.id
    except Exception:
        pass
    return -1


@app.route("/")
def dashboard():
    """Page principale du dashboard."""
    container = get_container()
    history = container.get_draft_history()

    _acct_id = _dashboard_current_account_id()
    drafts = history.get_all_for_account(_acct_id, limit=20) if _acct_id > 0 else []
    # M-3: scope draft_stats by account_id to avoid cross-account leakage in
    # multi-account Tauri installs. Empty stats if no current account resolved.
    if hasattr(history, "get_stats_for_account"):
        draft_stats = history.get_stats_for_account(_acct_id) if _acct_id > 0 else {}
    else:
        draft_stats = history.get_stats() if _acct_id > 0 else {}
    cost_stats = get_cost_stats()
    category_breakdown = draft_stats.get("by_category", {}) if draft_stats else {}
    analytics = get_analytics_stats()

    return render_template_string(
        DASHBOARD_HTML,
        stats=get_stats(),
        history=get_history(),
        config=get_config(),
        model_costs=MODEL_COSTS,
        drafts=drafts,
        draft_stats=draft_stats,
        daily_stats=draft_stats.get("daily_stats", []),
        learning_stats=get_learning_stats(),
        cost_stats=cost_stats,
        category_breakdown=category_breakdown,
        category_total=sum(category_breakdown.values()) if category_breakdown else 0,
        retention_stats=get_retention_stats(),
        roi=calculate_roi(draft_stats, cost_stats),
        analytics=analytics,
    )


@app.route("/api/stats")
def api_stats():
    """API JSON pour les statistiques."""
    container = get_container()
    history = container.get_draft_history()
    return jsonify({
        "stats": get_stats(),
        "history": get_history(),
        "config": get_config(),
        "draft_stats": history.get_stats(),
    })


@app.route("/api/draft/<draft_id>")
def api_draft(draft_id):
    """API pour récupérer un brouillon."""
    # SECURITY: Validate draft_id format (prevent injection attacks)
    if not _validate_draft_id(draft_id):
        return jsonify({"error": "Invalid id format"}), 400

    container = get_container()
    history = container.get_draft_history()
    _acct_id = _dashboard_current_account_id()
    record = history.get_by_id_for_account(draft_id, _acct_id) if _acct_id > 0 else None
    if record:
        return jsonify({
            "id": record.id,
            "email_subject": record.email_subject,
            "email_preview": record.email_preview,
            "draft_final": record.draft_final,
            "critique": record.critique,
            "feedback": record.feedback,
            "feedback_rating": record.feedback_rating,
        })
    return jsonify({"error": "Not found"}), 404


@app.route("/api/feedback", methods=["POST"])
def api_feedback():
    """API pour sauvegarder le feedback."""
    from flask import request
    data = request.get_json()
    draft_id = data.get("id")
    feedback = data.get("feedback", "")
    rating = data.get("rating")

    # SECURITY: Validate draft_id format (prevent injection attacks)
    if not draft_id:
        return jsonify({"error": "Missing id"}), 400

    if not _validate_draft_id(draft_id):
        return jsonify({"error": "Invalid id format"}), 400

    # SECURITY: Validate feedback size (prevent DoS)
    if not _validate_feedback(feedback):
        return jsonify({"error": "Invalid feedback format or size"}), 400

    if rating is not None:
        if not isinstance(rating, int) or isinstance(rating, bool):
            return jsonify({"error": "Rating must be an integer between 1 and 5"}), 400
        if rating < 1 or rating > 5:
            return jsonify({"error": "Rating must be between 1 and 5"}), 400

    container = get_container()
    history = container.get_draft_history()
    _acct_id = _dashboard_current_account_id()
    if _acct_id <= 0:
        return jsonify({"error": "Draft not found"}), 404
    success = history.update_feedback_for_account(draft_id, _acct_id, feedback, rating)

    if not success:
        return jsonify({"error": "Draft not found"}), 404

    return jsonify({"success": True})


@app.route("/api/export-training")
def api_export_training():
    """Exporte les données pour entraînement."""
    container = get_container()
    history = container.get_draft_history()
    data = history.export_for_training()
    return jsonify(data)


@app.route("/api/export-csv")
def api_export_csv():
    """Exporte l'historique en CSV."""
    from flask import Response
    container = get_container()
    history = container.get_draft_history()
    csv_data = history.export_csv()
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=agentys_export.csv"}
    )


# ============================================================================
# API MEMORY (Base de connaissances IA)
# ============================================================================

@app.route("/api/memory")
def api_memory_get():
    """Récupère le contenu de la mémoire IA."""
    from app.memory_manager import get_memory_manager
    manager = get_memory_manager()
    return jsonify({
        "content": manager.get_memory(),
        "stats": {
            "total_size": manager.get_stats().total_size,
            "word_count": manager.get_stats().word_count,
            "section_count": manager.get_stats().section_count,
            "last_modified": manager.get_stats().last_modified,
            "version_count": manager.get_stats().version_count
        }
    })


@app.route("/api/memory", methods=["POST"])
def api_memory_update():
    """Met à jour la mémoire IA."""
    from flask import request
    from app.memory_manager import get_memory_manager

    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Content required"}), 400

    manager = get_memory_manager()
    version = manager.update_memory(
        content=data["content"],
        change_summary=data.get("change_summary", ""),
        created_by=data.get("created_by", "dashboard")
    )

    return jsonify({
        "success": True,
        "version": {
            "id": version.id,
            "content_hash": version.content_hash,
            "created_at": version.created_at
        }
    })


@app.route("/api/memory/sections")
def api_memory_sections():
    """Récupère les sections de la mémoire."""
    from app.memory_manager import get_memory_manager
    from dataclasses import asdict
    manager = get_memory_manager()
    sections = manager.get_sections()
    return jsonify({
        "sections": [asdict(s) for s in sections]
    })


@app.route("/api/memory/sections/<section_title>", methods=["PUT"])
def api_memory_section_update(section_title: str):
    """Met à jour une section spécifique."""
    from flask import request
    from app.memory_manager import get_memory_manager

    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Content required"}), 400

    manager = get_memory_manager()
    version = manager.update_section(
        section_title=section_title,
        new_content=data["content"],
        change_summary=data.get("change_summary", "")
    )

    if not version:
        return jsonify({"error": "Section not found"}), 404

    return jsonify({"success": True, "version_id": version.id})


@app.route("/api/memory/sections", methods=["POST"])
def api_memory_section_add():
    """Ajoute une nouvelle section."""
    from flask import request
    from app.memory_manager import get_memory_manager

    data = request.get_json()
    if not data or "title" not in data or "content" not in data:
        return jsonify({"error": "Title and content required"}), 400

    manager = get_memory_manager()
    version = manager.add_section(
        title=data["title"],
        content=data["content"],
        level=data.get("level", 2),
        position=data.get("position", "end")
    )

    return jsonify({"success": True, "version_id": version.id})


@app.route("/api/memory/sections/<section_title>", methods=["DELETE"])
def api_memory_section_delete(section_title: str):
    """Supprime une section."""
    from app.memory_manager import get_memory_manager
    manager = get_memory_manager()
    version = manager.delete_section(section_title)

    if not version:
        return jsonify({"error": "Section not found"}), 404

    return jsonify({"success": True, "version_id": version.id})


@app.route("/api/memory/search")
def api_memory_search():
    """Recherche dans la mémoire."""
    from flask import request
    from app.memory_manager import get_memory_manager

    query = request.args.get("q", "")
    if not query:
        return jsonify({"error": "Query required"}), 400

    manager = get_memory_manager()
    results = manager.search(query)
    return jsonify({"results": results, "count": len(results)})


@app.route("/api/memory/history")
def api_memory_history():
    """Récupère l'historique des versions."""
    from flask import request
    from app.memory_manager import get_memory_manager
    from dataclasses import asdict

    limit = request.args.get("limit", 20, type=int)
    offset = request.args.get("offset", 0, type=int)

    manager = get_memory_manager()
    history = manager.get_history(limit=limit, offset=offset)

    return jsonify({
        "history": [asdict(v) for v in history],
        "total": len(manager.history)
    })


@app.route("/api/memory/export")
def api_memory_export():
    """Exporte la mémoire dans différents formats."""
    from flask import request, Response
    from app.memory_manager import get_memory_manager

    format = request.args.get("format", "markdown")
    manager = get_memory_manager()
    content = manager.export_memory(format=format)

    if format == "json":
        return Response(content, mimetype="application/json")
    elif format == "text":
        return Response(content, mimetype="text/plain")
    else:
        return Response(content, mimetype="text/markdown")


@app.route("/api/memory/import", methods=["POST"])
def api_memory_import():
    """Importe du contenu dans la mémoire."""
    from flask import request
    from app.memory_manager import get_memory_manager

    data = request.get_json()
    if not data or "content" not in data:
        return jsonify({"error": "Content required"}), 400

    manager = get_memory_manager()
    version = manager.import_memory(
        content=data["content"],
        merge=data.get("merge", False)
    )

    return jsonify({"success": True, "version_id": version.id})


# ============================================================================
# WEBSOCKET EVENTS
# ============================================================================

if SOCKETIO_AVAILABLE and socketio is not None:
    @socketio.on("connect")
    def handle_connect():
        """Client connecté au WebSocket."""
        emit("connection_status", {"status": "connected"})

    @socketio.on("request_stats")
    def handle_request_stats():
        """Client demande les statistiques actuelles."""
        container = get_container()
        history = container.get_draft_history()
        stats = history.get_stats()
        emit("stats_update", stats)

    @socketio.on("disconnect")
    def handle_disconnect():
        """Client déconnecté."""
        pass


# ============================================================================
# FONCTIONS D'EMISSION
# ============================================================================

def notify_email_processed(subject: str, status: str, category: str = "") -> None:
    """
    Notifie le dashboard qu'un email a été traité.

    Args:
        subject: Sujet de l'email
        status: Statut du traitement (V1, V2, etc.)
        category: Catégorie de l'email (URGENT, NORMAL, etc.)
    """
    if socketio is None:
        return
    socketio.emit("email_processed", {
        "subject": subject[:50] + "..." if len(subject) > 50 else subject,
        "status": status,
        "category": category,
        "timestamp": datetime.now().isoformat(),
    })


def notify_draft_created(subject: str, recipient: str) -> None:
    """
    Notifie le dashboard qu'un brouillon a été créé.

    Args:
        subject: Sujet de l'email
        recipient: Destinataire
    """
    if socketio is None:
        return
    socketio.emit("draft_created", {
        "subject": subject[:50] + "..." if len(subject) > 50 else subject,
        "recipient": recipient,
        "timestamp": datetime.now().isoformat(),
    })


def notify_error(message: str, error_type: str = "error") -> None:
    """
    Notifie le dashboard d'une erreur.

    Args:
        message: Message d'erreur
        error_type: Type d'erreur
    """
    if socketio is None:
        return
    socketio.emit("error_notification", {
        "message": message,
        "type": error_type,
        "timestamp": datetime.now().isoformat(),
    })


def notify_budget_alert(usage_percent: float, remaining: float) -> None:
    """
    Notifie le dashboard d'une alerte budget.

    Args:
        usage_percent: Pourcentage du budget utilisé
        remaining: Budget restant en USD
    """
    if socketio is None:
        return
    socketio.emit("budget_alert", {
        "usage_percent": round(usage_percent, 1),
        "remaining_usd": round(remaining, 2),
        "timestamp": datetime.now().isoformat(),
    })


def broadcast_stats_update() -> None:
    """Diffuse les statistiques actuelles à tous les clients."""
    if socketio is None:
        return
    container = get_container()
    history = container.get_draft_history()
    stats = history.get_stats()
    socketio.emit("stats_update", stats)


# ============================================================================
# POINT D'ENTRÉE
# ============================================================================

def run_dashboard(host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
    """Lance le serveur dashboard avec support WebSocket."""
    if not SOCKETIO_AVAILABLE:
        print("""
╔═══════════════════════════════════════════════════════════════╗
║              Agentys - Dashboard (mode basique)             ║
╚═══════════════════════════════════════════════════════════════╝

flask-socketio n'est pas installé. Mode temps réel désactivé.
Installez avec: pip install flask-socketio

Lancement en mode Flask standard...
""")
        print(f"Dashboard disponible sur : http://{host}:{port}")
        app.run(host=host, port=port, debug=debug)
        return

    print(f"""
╔═══════════════════════════════════════════════════════════════╗
║              Agentys - Dashboard                            ║
╚═══════════════════════════════════════════════════════════════╝

Dashboard disponible sur : http://{host}:{port}
WebSocket temps réel activé

Appuyez sur Ctrl+C pour arrêter le serveur.
""")
    socketio.run(app, host=host, port=port, debug=debug, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    run_dashboard(debug=True)
