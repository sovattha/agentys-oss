"""Synthetic evaluation dataset for SelfCritiqueAgent vs CriticAgent comparison.

200 cases — 50 good drafts (control) + 30 per failure category × 5 categories.
Each case is (email_in, draft_v1, mode, expected_risks, expected_a_confirmer_count).

The corpus is intentionally simple and short — calibration is about verdict
agreement on clear-cut cases, not about edge cases.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    email_in: str
    draft_v1: str
    mode: str  # 'reply' | 'compose'
    expected_risks: tuple[str, ...] = field(default_factory=tuple)
    expected_a_confirmer_count: int = 0
    category: str = "control"  # 'good' | 'hallucination' | 'placeholder' | ...


# ---------------------------------------------------------------------------
# 50 GOOD DRAFTS (control group — should pass with high self_score)
# ---------------------------------------------------------------------------

_GOOD_REPLIES = [
    ("Pouvez-vous me confirmer le rendez-vous de mardi ?", "Bonjour, oui je confirme notre rendez-vous de mardi. Bonne journée."),
    ("Avez-vous reçu ma facture ?", "Bonjour, oui votre facture est bien arrivée. Merci."),
    ("Le rapport est-il prêt ?", "Bonjour, oui le rapport est terminé, je vous l'envoie demain matin."),
    ("Quand pouvez-vous me rappeler ?", "Bonjour, je vous appelle vendredi après-midi."),
    ("Avez-vous pu lire mon document ?", "Bonjour, oui j'ai bien lu le document, c'est validé pour moi."),
    ("Êtes-vous disponible jeudi ?", "Bonjour, oui je suis disponible jeudi, à quelle heure vous arrange ?"),
    ("Le projet avance-t-il bien ?", "Bonjour, oui le projet avance comme prévu, livraison fin de mois."),
    ("Avez-vous validé le devis ?", "Bonjour, oui le devis est validé, vous pouvez démarrer."),
    ("Pouvez-vous m'envoyer les chiffres ?", "Bonjour, je vous envoie les chiffres dans la journée."),
    ("Le contrat est-il signé ?", "Bonjour, oui le contrat est signé, je vous l'envoie scanné."),
]

_GOOD_COMPOSES = [
    ("Demande de devis pour 50 licences", "Bonjour, je souhaite obtenir un devis pour 50 licences de votre logiciel. Merci."),
    ("Annulation rendez-vous demain", "Bonjour, je dois annuler notre rendez-vous de demain. Je vous propose de le reporter à la semaine prochaine."),
    ("Demande de RIB", "Bonjour, pourriez-vous me transmettre votre RIB pour le virement ? Merci."),
    ("Confirmation de présence à la réunion", "Bonjour, je confirme ma présence à la réunion de jeudi 14h."),
    ("Demande de bilan trimestriel", "Bonjour, j'aimerais recevoir le bilan du premier trimestre. Pouvez-vous me l'envoyer ?"),
]

GOOD_CASES: list[EvalCase] = []
for i, (email, draft) in enumerate(_GOOD_REPLIES * 4):
    GOOD_CASES.append(EvalCase(
        case_id=f"good-reply-{i:03d}",
        email_in=email, draft_v1=draft, mode="reply",
        expected_risks=(), expected_a_confirmer_count=0, category="good",
    ))
for i, (subject, draft) in enumerate(_GOOD_COMPOSES * 2):
    GOOD_CASES.append(EvalCase(
        case_id=f"good-compose-{i:03d}",
        email_in=subject, draft_v1=draft, mode="compose",
        expected_risks=(), expected_a_confirmer_count=0, category="good",
    ))
GOOD_CASES = GOOD_CASES[:50]


# ---------------------------------------------------------------------------
# 30 HALLUCINATION CASES — drafts inventing facts not in the email
# ---------------------------------------------------------------------------

_HALLUCINATIONS = [
    ("Quand peut-on se voir ?",
     "Bonjour, on se voit mardi 14 mars à 15h30 chez vous comme convenu.",
     ()),  # 14 mars + 15h30 + chez vous = 3 inventions
    ("Pouvez-vous m'envoyer le devis ?",
     "Bonjour, je vous envoie le devis de 4500€ par email à dpt-finance@xyz.com.",
     ()),
    ("Le rapport est-il prêt ?",
     "Bonjour, j'ai terminé le rapport hier à 22h, 47 pages au total.",
     ()),
    ("Avez-vous recu mon paiement ?",
     "Bonjour, oui votre paiement de 1234,56€ est bien arrivé sur le compte FR76 1234 5678.",
     ()),
    ("Confirmez-vous le rendez-vous ?",
     "Bonjour, je confirme notre rendez-vous du 12 avril à la Brasserie du Centre, 14h pile.",
     ()),
    ("Avez-vous appelé le client ?",
     "Bonjour, oui j'ai appelé Mme Dupont hier à 16h, elle accepte la proposition à 8500€.",
     ()),
]

HALLUCINATION_CASES: list[EvalCase] = []
for i, (email, draft, _) in enumerate((_HALLUCINATIONS * 5)[:30]):
    HALLUCINATION_CASES.append(EvalCase(
        case_id=f"halluc-{i:03d}",
        email_in=email, draft_v1=draft, mode="reply",
        expected_risks=("hallucination",), category="hallucination",
    ))


# ---------------------------------------------------------------------------
# 30 PLACEHOLDER CASES — drafts containing [À confirmer] etc.
# ---------------------------------------------------------------------------

_PLACEHOLDERS = [
    ("Quand est la livraison ?", "Bonjour, livraison prévue [À confirmer] dans la semaine.", 1),
    ("Quel est le tarif ?", "Bonjour, le tarif est de [TBD]€ HT, je reviens vers vous.", 1),
    ("Quel est le délai ?", "Bonjour, délai estimé : [À valider] semaines.", 1),
    ("Avez-vous un devis ?", "Bonjour, devis joint : [REDACTE]. Bonne lecture.", 1),
    ("Confirmez le RDV", "Bonjour, RDV confirmé pour [À confirmer] à [À confirmer]. Merci.", 2),
    ("Adresse de livraison ?", "Bonjour, adresse : [placeholder address]. À bientôt.", 1),
]

PLACEHOLDER_CASES: list[EvalCase] = []
for i, (email, draft, count) in enumerate((_PLACEHOLDERS * 5)[:30]):
    PLACEHOLDER_CASES.append(EvalCase(
        case_id=f"placeholder-{i:03d}",
        email_in=email, draft_v1=draft, mode="reply",
        expected_risks=("placeholder",), expected_a_confirmer_count=count,
        category="placeholder",
    ))


# ---------------------------------------------------------------------------
# 30 TONE_MISMATCH CASES — tu/vous mix
# ---------------------------------------------------------------------------

_TONE_MIX = [
    "Bonjour, je vous remercie de votre message. Tu peux me rappeler demain ?",
    "Cher Monsieur, comme tu le sais, vous m'avez demandé un devis. Je te l'envoie.",
    "Salut, comme tu m'as demandé hier, vous trouverez le document ci-joint.",
    "Bonjour, votre commande est prête. Tu peux passer la chercher quand tu veux.",
    "Madame, je vous prie de m'excuser pour le retard. Tu comprends que c'est compliqué.",
    "Bonjour, merci pour ta patience. Vous recevrez la facture demain.",
]

TONE_CASES: list[EvalCase] = []
for i, draft in enumerate((_TONE_MIX * 5)[:30]):
    TONE_CASES.append(EvalCase(
        case_id=f"tone-{i:03d}",
        email_in="Pouvez-vous me confirmer ?",
        draft_v1=draft, mode="reply",
        expected_risks=("tone_mismatch",), category="tone_mismatch",
    ))


# ---------------------------------------------------------------------------
# 30 FILLER CASES — corporate bloat
# ---------------------------------------------------------------------------

_FILLERS = [
    "Bonjour, merci pour votre email. I'd be happy to help. N'hésitez pas si vous avez des questions. Cordialement.",
    "Bonjour, j'espère que ce message vous trouve bien. Je reste à votre entière disposition. Au plaisir de vous lire.",
    "Hello, thank you for reaching out. I'm here to help with anything you need. Looking forward to hearing from you.",
    "Bonjour, c'est parti pour une nouvelle semaine ! Super, je m'occupe de ça. N'hésitez pas.",
    "Bonjour, merci pour votre message. Je reviens vers vous sous peu. À votre disposition.",
    "Hi! Happy to help. Feel free to reach out. Looking forward to hearing from you. Best.",
]

FILLER_CASES: list[EvalCase] = []
for i, draft in enumerate((_FILLERS * 5)[:30]):
    FILLER_CASES.append(EvalCase(
        case_id=f"filler-{i:03d}",
        email_in="J'ai une question rapide.",
        draft_v1=draft, mode="reply",
        expected_risks=("filler",), category="filler",
    ))


# ---------------------------------------------------------------------------
# 30 OFF_TOPIC CASES — draft doesn't answer the question
# ---------------------------------------------------------------------------

_OFF_TOPIC = [
    ("Pouvez-vous me dire le prix ?", "Bonjour, notre société a été fondée en 1995 et compte 200 employés."),
    ("Quand est la livraison ?", "Bonjour, nos bureaux sont ouverts du lundi au vendredi de 9h à 18h."),
    ("Avez-vous validé le contrat ?", "Bonjour, voici les coordonnées de notre service comptabilité."),
    ("Le rapport est-il prêt ?", "Bonjour, j'aimerais vous proposer un nouvel abonnement premium."),
    ("Quel est le numéro de suivi ?", "Bonjour, je vous remercie pour votre fidélité de 5 ans."),
    ("Confirmez le RDV de jeudi", "Bonjour, notre prochaine newsletter sortira le 15."),
]

OFF_TOPIC_CASES: list[EvalCase] = []
for i, (email, draft) in enumerate((_OFF_TOPIC * 5)[:30]):
    OFF_TOPIC_CASES.append(EvalCase(
        case_id=f"offtopic-{i:03d}",
        email_in=email, draft_v1=draft, mode="reply",
        expected_risks=("off_topic",), category="off_topic",
    ))


# ---------------------------------------------------------------------------
# Aggregate
# ---------------------------------------------------------------------------

ALL_CASES: list[EvalCase] = (
    GOOD_CASES
    + HALLUCINATION_CASES
    + PLACEHOLDER_CASES
    + TONE_CASES
    + FILLER_CASES
    + OFF_TOPIC_CASES
)

assert len(ALL_CASES) == 200, f"Expected 200 cases, got {len(ALL_CASES)}"
