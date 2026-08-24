# Agentys — voice-first email assistant.
# Copyright (C) 2026 Sovattha Sok and Alexandre Sauvageau
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at your
# option) any later version. See the LICENSE file for details.
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Seed 20 blog article topics into article_requests queue.

Topics from Gemini Deep Research dump (2026-04-28). Each topic has:
- 3 verified metrics with values
- Analytical angle (second-order insight beyond surface-level)
- 2-3 source URLs hand-picked for citation

The writer reads these as briefs and cites the stats with the source URLs
inline (no fabrication). Schedules cover 10 weeks at 2 articles/week
(Tuesday + Friday cron `ecrivain`).

Run inside the agentys-pm container against the prod DB:
  docker exec agentys-pm python3 /tmp/seed_blog_topics.py
"""

from __future__ import annotations

import sys

from ai_team.agents.content import store

# Each topic = (heading, metrics_block, analytical_angle, source_urls, keywords, category)
TOPICS = [
    {
        "topic": "AI Email for Healthcare Professionals",
        "category": "Case Study",
        "keywords": ["AI email healthcare", "clinician burnout AI", "HIPAA email automation", "medical email AI"],
        "metrics": [
            ("75%", "sonographer burnout rate"),
            ("42%", "clinicians considering industry exit"),
            ("75-95%", "passive AI burnout prediction accuracy"),
        ],
        "angle": (
            "Beyond drafting velocity, AI email assistants act as diagnostic telemetry for organizational "
            "health. By monitoring email timing, semantic patterns, and sentiment, they predict clinician "
            "burnout risk non-invasively. As they intercept routine patient inquiries, they flatten "
            "unpredictable spikes in administrative load and become critical retention mechanisms."
        ),
        "sources": [
            ("American Hospital Association", "https://www.aha.org/"),
            ("PMC NIH (Passive AI Burnout)", "https://pmc.ncbi.nlm.nih.gov/"),
            ("GE Healthcare", "https://www.gehealthcare.com/"),
        ],
    },
    {
        "topic": "AI Email for Accountants and CPAs",
        "category": "Case Study",
        "keywords": ["AI email accountants", "CPA productivity AI", "accounting automation", "month-end close AI"],
        "metrics": [
            ("8.5% (3.5 hrs/week)", "time reallocated from routine data entry"),
            ("21%", "increase in billable hours via AI use"),
            ("7.5 days", "acceleration of month-end book closing"),
        ],
        "angle": (
            "AI email in accounting yields a documented 12% increase in general ledger granularity. "
            "Manual entry encourages broad categorization to save time; AI processes correspondence "
            "and extracts fine-grained context per expense or revenue. Junior staff pivot from data "
            "clerks to analytical interpreters of richer financial data."
        ),
        "sources": [
            ("Journal of Accountancy", "https://www.journalofaccountancy.com/"),
            ("Intuit QuickBooks Survey", "https://investors.intuit.com/"),
            ("Stanford GSB", "https://www.gsb.stanford.edu/"),
        ],
    },
    {
        "topic": "AI Email for Startup Founders",
        "category": "Business Tips",
        "keywords": ["AI email startup", "founder productivity", "solopreneur email automation", "startup inbox"],
        "metrics": [
            ("96 minutes daily", "productivity lost to tool switching"),
            ("60%+", "founders underestimating operational roles"),
            ("50.5%", "conversion rate of abandoned cart emails"),
        ],
        "angle": (
            "Agentic email reframes the inbox from passive repository to autonomous command center. "
            "Tool proliferation is itself a meta-pain point; founders waste time across disconnected "
            "platforms. AI email assistants integrate with databases, project management, and CRMs to "
            "unify context and act as a synthetic Chief of Staff for solopreneurs."
        ),
        "sources": [
            ("Salesforce Slack Survey", "https://www.salesforce.com/"),
            ("Business.com", "https://www.business.com/"),
            ("OptinMonster Email Stats", "https://optinmonster.com/"),
        ],
    },
    {
        "topic": "How AI Email Handles Confidential Data",
        "category": "Developer Guide",
        "keywords": ["AI email security", "PII handling AI", "enterprise AI compliance", "SOC 2 email AI"],
        "metrics": [
            ("$9.48 million", "average healthcare data breach cost"),
            ("81%", "healthcare organizations using cloud solutions"),
            ("38% to 100%", "call answer rate improvement post-AI deployment"),
        ],
        "angle": (
            "Enterprise-grade AI email assistants use ephemeral capture buffers and zero model data "
            "retention. The AI processes context to draft a response then deletes prompt data from "
            "memory cache; corporate data never trains the foundational model. Identity governance "
            "enforces role-based access where the agent inherits the user's exact permissions."
        ),
        "sources": [
            ("Kiteworks HIPAA Email", "https://www.kiteworks.com/"),
            ("Cloud Security Alliance", "https://cloudsecurityalliance.org/"),
            ("Enter.health HIPAA AI", "https://enter.health/"),
        ],
    },
    {
        "topic": "The Future of AI Email Agents in 2026",
        "category": "AI Productivity",
        "keywords": ["AI email 2026", "agentic email future", "multi-agent email", "AI email trends"],
        "metrics": [
            ("40%", "enterprise apps integrating AI agents by 2026"),
            ("86%", "executives expecting to outsource digital assistance"),
            ("282%", "CIO-reported AI adoption growth"),
        ],
        "angle": (
            "The transition is from reactive text generation to autonomous action in multi-agent "
            "ecosystems. Specialized agents collaborate: one extracts data, another queries the CRM "
            "for context, a third drafts in your tone, a fourth audits against compliance. The inbox "
            "becomes a digital assembly line; humans shift from creators to strategic approvers."
        ),
        "sources": [
            ("Salesforce AI Trends 2026", "https://www.salesforce.com/"),
            ("Google Cloud AI Agent Trends", "https://cloud.google.com/"),
            ("MuleSoft Agentic Trends", "https://blogs.mulesoft.com/"),
        ],
    },
    {
        "topic": "AI Email Etiquette Guidelines for 2026",
        "category": "Business Tips",
        "keywords": ["AI email etiquette", "AI disclosure email", "professional AI communication", "email AI ethics"],
        "metrics": [
            ("16%", "trust decline from students upon AI grading disclosure"),
            ("18%", "trust decline from investors upon AI ad disclosure"),
            ("20%", "trust decline in graphic designers upon AI disclosure"),
        ],
        "angle": (
            "Research from 5,000 University of Arizona participants shows recipients demand "
            "transparency yet penalize it in practice. AI labels signal a sender did not deem the "
            "interaction worthy of biological time. Etiquette pivots from disclosure to a "
            "human-in-the-loop that injects emotional friction and conversational nuance."
        ),
        "sources": [
            ("University of Arizona", "https://news.arizona.edu/"),
            ("Reuters Institute Oxford", "https://reutersinstitute.politics.ox.ac.uk/"),
            ("PMC Servant Perception Study", "https://pmc.ncbi.nlm.nih.gov/"),
        ],
    },
    {
        "topic": "How to Train Your AI Email Assistant",
        "category": "Developer Guide",
        "keywords": ["AI email training", "few-shot email AI", "personalize AI email", "AI writing voice"],
        "metrics": [
            ("2-5 examples", "optimal for few-shot learning"),
            ("35%", "open rate increase via name personalization"),
            ("26%", "open rate increase via personalized subject lines"),
        ],
        "angle": (
            "Default LLMs output sanitized verbose prose that damages personal branding. Advanced "
            "few-shot prompting with 2-5 carefully curated input-output pairs extracts the user's "
            "narrative architecture. RLHF principles teach the system conversational rhythms, "
            "intentional brevity, and rhetorical imperfections that mark authentic human writing."
        ),
        "sources": [
            ("IBM Few-Shot Prompting", "https://www.ibm.com/"),
            ("OpenAI InstructGPT", "https://cdn.openai.com/"),
            ("Prompt Engineering Guide", "https://www.promptingguide.ai/"),
        ],
    },
    {
        "topic": "AI Email vs Traditional Email Clients",
        "category": "AI Productivity",
        "keywords": ["AI email vs traditional", "agentic email client", "MCP email integration", "smart inbox"],
        "metrics": [
            ("75 minutes", "time wasted daily on unimportant tasks"),
            ("~33%", "small business owners juggling 5+ digital tools"),
            ("29%", "business owners repeating messages across platforms"),
        ],
        "angle": (
            "Architectures using the Model Context Protocol let AI perceive the digital environment, "
            "reason through multi-step objectives, and execute actions. When a client emails about a "
            "delayed project, the agent queries the tracking database, adjusts the timeline in PM "
            "software, drafts the explanation, and schedules a follow-up, all within one framework."
        ),
        "sources": [
            ("HP Tech Takes Agentic AI", "https://www.hp.com/"),
            ("Coursera Agentic vs Generative", "https://www.coursera.org/"),
            ("Salesforce Agentic AI", "https://www.salesforce.com/"),
        ],
    },
    {
        "topic": "Email Burnout and AI Work-Life Balance",
        "category": "Business Tips",
        "keywords": ["email burnout AI", "work life balance email", "email overload psychology", "Zeigarnik effect"],
        "metrics": [
            ("23%", "workers constantly living in email systems"),
            ("79%", "employees distracted by email at work"),
            ("34%", "checking email every hour or more"),
        ],
        "angle": (
            "The Zeigarnik Effect explains the toll: the brain obsessively remembers uncompleted "
            "tasks. Every unanswered email is an open psychological loop generating subconscious "
            "tension. AI email assistants close those loops by drafting holding responses and "
            "summarizing threads, transitioning workflow from anxious reactivity to controlled flow."
        ),
        "sources": [
            ("Psychology Today (Zeigarnik)", "https://www.psychologytoday.com/"),
            ("PMC Email Stress Study", "https://pmc.ncbi.nlm.nih.gov/"),
            ("AttendanceBot Zeigarnik", "https://attendancebot.com/"),
        ],
    },
    {
        "topic": "AI Email for Remote and Async Teams",
        "category": "Business Tips",
        "keywords": ["AI email remote teams", "async communication AI", "distributed team email", "remote work productivity"],
        "metrics": [
            ("61%", "employees desiring more asynchronous work"),
            ("44%", "workers who dread meetings"),
            ("5 hours", "unproductive meeting time per week"),
        ],
        "angle": (
            "Async messages lack verbal cues, so text must be flawlessly structured. AI assistants "
            "analyze rough thoughts and structure them into briefs with extracted action items and "
            "contextual links. By ensuring an email across a 12-hour time difference contains total "
            "clarity, AI eliminates clarification calls and protects focused work time."
        ),
        "sources": [
            ("Zoom Sync vs Async", "https://www.zoom.com/"),
            ("Notta Workplace Stats", "https://www.notta.ai/"),
            ("Coveo Async Communication", "https://www.coveo.com/"),
        ],
    },
    {
        "topic": "Why AI Must Learn Your Writing Voice",
        "category": "AI Productivity",
        "keywords": ["AI writing voice", "personalized AI email", "author voice profile", "AI tone matching"],
        "metrics": [
            ("52%", "likelihood to switch brands due to lack of personalization"),
            ("57%", "increase in engagement with personalized content"),
            ("72%", "shoppers responding only to personal feeling messages"),
        ],
        "angle": (
            "The uncanny valley applies to text. Even when AI mimics human structure, recipients "
            "unconsciously detect missing emotional intent and find the message untrustworthy. AI "
            "must replicate intentional biological imperfections by mapping punctuation habits, "
            "sentence length variations, and metaphor domains into an Author Voice Profile."
        ),
        "sources": [
            ("Business of Story Voice Profiles", "https://www.businessofstory.com/"),
            ("Max Planck Voice Research", "https://maxplanckneuroscience.org/"),
            ("Stripo Personalization Stats", "https://stripo.email/"),
        ],
    },
    {
        "topic": "AI Email for Customer Support Teams",
        "category": "Case Study",
        "keywords": ["AI customer support email", "support ticket AI", "helpdesk automation", "CSAT AI"],
        "metrics": [
            ("32 hrs to 32 mins", "ticket resolution time decrease at top companies"),
            ("45%-53%", "incoming query deflection rate via AI agents"),
            ("55%", "customer support wait time reduction"),
        ],
        "angle": (
            "Modern AI deflects up to 53% of queries by interfacing directly with backend systems "
            "to process refunds, update shipping, and resolve billing without human intervention. "
            "Agents pivot from data retrieval to complex problem solving. CSAT rises from 89% to "
            "99% because resolutions are instant and accurate; operational costs drop 30%."
        ),
        "sources": [
            ("Zendesk AI Support Stats", "https://www.zendesk.com/"),
            ("Master of Code AI Stats", "https://masterofcode.com/"),
            ("Freshworks AI ROI", "https://www.freshworks.com/"),
        ],
    },
    {
        "topic": "ROI of AI Email Tools for SMBs",
        "category": "Business Tips",
        "keywords": ["AI email ROI", "AI investment return", "AI productivity ROI", "agentic AI ROI"],
        "metrics": [
            ("$3.70", "average ROI per $1 invested in AI"),
            ("333%", "three-year ROI for agentic AI platforms"),
            ("56%", "wage premium for AI-skilled workers"),
        ],
        "angle": (
            "Standard ROI models miss the systemic value of cognitive offloading. Time saved must be "
            "quantified by how it gets reused. If an executive saves 5 hours a week on triage, ROI "
            "is the new revenue from redirecting those hours to high-tier client work, not the "
            "hourly rate. This converts cost centers into measurable profit centers."
        ),
        "sources": [
            ("Microsoft Tech Community", "https://techcommunity.microsoft.com/"),
            ("Writer.com ROI Calculator", "https://writer.com/"),
            ("PwC AI Jobs Barometer", "https://www.pwc.com/"),
        ],
    },
    {
        "topic": "AI Email Privacy and GDPR Compliance",
        "category": "Developer Guide",
        "keywords": ["AI email GDPR", "GDPR compliance email", "EU data privacy AI", "data residency AI"],
        "metrics": [
            ("€20M or 4% revenue", "maximum GDPR penalty threshold"),
            ("122 emails daily", "average work emails per user"),
            ("€1.2 billion", "Meta's record fine for cross-border violations"),
        ],
        "angle": (
            "Data residency and model training are the nuanced compliance challenges. Using EU "
            "citizen email data to train foundational models without explicit consent contaminates "
            "the algorithmic weights, an issue called model poisoning. EEA-localized data centers "
            "with Standard Contractual Clauses keep AI processing inside Europe."
        ),
        "sources": [
            ("GDPR.eu Email Guide", "https://gdpr.eu/"),
            ("EU Your Europe", "https://europa.eu/"),
            ("InCountry AI Residency", "https://incountry.com/"),
        ],
    },
    {
        "topic": "Agentic AI in Professional Communication",
        "category": "AI Productivity",
        "keywords": ["agentic AI email", "professional AI communication", "Model Context Protocol", "AI agents"],
        "metrics": [
            ("85%", "organizations increasing AI investment"),
            ("95%", "firms adopting automation tech within a year"),
            ("91%", "executives foreseeing digitized automated workflows"),
        ],
        "angle": (
            "Agentic systems use the Model Context Protocol to plug into broader digital ecosystems. "
            "The verification loop perceives data, extracts intent, plans actions, retrieves external "
            "data via APIs, and drafts the message. Humans elevate from manual data-bridge between "
            "platforms to strategic orchestrators of autonomous digital labor."
        ),
        "sources": [
            ("Red Hat Agentic vs Generative", "https://www.redhat.com/"),
            ("Robylon AI Agents 2026", "https://www.robylon.ai/"),
            ("Salesforce Agentic Differences", "https://www.salesforce.com/"),
        ],
    },
    {
        "topic": "AI Email for Teachers and Educators",
        "category": "Case Study",
        "keywords": ["AI email teachers", "educator productivity AI", "teacher burnout", "school admin automation"],
        "metrics": [
            ("44%-53%", "K-12 teachers reporting frequent burnout"),
            ("62%", "educators experiencing high job-related stress"),
            ("86%", "school districts reporting open positions"),
        ],
        "angle": (
            "Auburn University research shows new digital platforms increase burnout when old ones "
            "stay active, due to cognitive friction from managing yet another inbox. AI integration "
            "must operate invisibly inside the existing client. By drafting parental updates and "
            "summarizing administrative directives, AI preserves pedagogical energy for the classroom."
        ),
        "sources": [
            ("Research.com Teacher Burnout", "https://research.com/"),
            ("National Education Association", "https://www.nea.org/"),
            ("The Hartford Education", "https://www.thehartford.com/"),
        ],
    },
    {
        "topic": "Best Practices for AI Email Writing",
        "category": "Business Tips",
        "keywords": ["AI email best practices", "human in the loop email", "AI email governance", "AI writing guidelines"],
        "metrics": [
            ("51%", "marketers believing AI emails outperform traditional"),
            ("47%", "enterprise companies automating self-service"),
            ("80%", "employees stating AI improved work quality"),
        ],
        "angle": (
            "Human-in-the-Loop must transcend an approve checkbox. Drawing from aviation Crew "
            "Resource Management, true HITL governance requires timely context, intervention "
            "authority, and defensible rationale. The EU AI Act Article 14 and NIST AI Risk "
            "Management Framework mandate this oversight; design must allow micro-edits without "
            "context-switching."
        ),
        "sources": [
            ("Strata HITL Guide 2026", "https://strata.io/"),
            ("Salesforce HITL Trust", "https://www.salesforce.com/"),
            ("n8n HITL Automation", "https://blog.n8n.io/"),
        ],
    },
    {
        "topic": "Gmail vs Outlook AI Integration",
        "category": "Email Automation",
        "keywords": ["Gmail vs Outlook AI", "Workspace vs M365 AI", "Gemini vs Copilot", "email AI comparison"],
        "metrics": [
            ("£16.10/user/month", "cost premium for Microsoft Copilot integration"),
            ("82%", "users finding genuine value in bundled AI"),
            ("1,000,000 tokens", "Gemini 3 Pro context window size"),
        ],
        "angle": (
            "Bundling vs add-on pricing creates a workforce-equality dichotomy: organizations buy "
            "selective Copilot licenses, accidentally creating two-tier teams. Bundled Workspace AI "
            "democratizes access. Gemini handles 1M tokens vs 32K for Copilot. Ubiquitous contextual "
            "AI access drives higher aggregate organizational velocity than siloed specialist tools."
        ),
        "sources": [
            ("Compare the Cloud Gemini vs Copilot", "https://www.comparethecloud.net/"),
            ("Section AI Comparison", "https://www.sectionai.com/"),
            ("Tactiq Gemini vs Copilot", "https://tactiq.io/"),
        ],
    },
    {
        "topic": "Psychology of Email Overload",
        "category": "AI Productivity",
        "keywords": ["email overload psychology", "email fatigue", "cognitive load email", "decision fatigue email"],
        "metrics": [
            ("75 minutes", "daily time wasted on unimportant tasks"),
            ("79%", "employees distracted by email at work"),
            ("63%", "employees feeling out of control at work"),
        ],
        "angle": (
            "Interaction style signals relational norms and role expectations. When professionals "
            "are crushed by volume, communication devolves into transactional exchanges that erode "
            "the organizational fabric. AI email assistants are psychological intervention tools: "
            "automating categorization unburdens working memory and restores capacity for deep work."
        ),
        "sources": [
            ("Mailpro Email Fatigue", "https://www.mailpro.com/"),
            ("InboxDone Overload", "https://inboxdone.com/"),
            ("Timewatch Time Stats", "https://www.timewatch.com/"),
        ],
    },
    {
        "topic": "AI Email for Small Business Owners",
        "category": "Business Tips",
        "keywords": ["AI email small business", "SMB email automation", "small business productivity AI", "SMB inbox"],
        "metrics": [
            ("80%", "SMBs citing email as top retention tool"),
            ("59%", "small businesses introducing time-saving tech"),
            ("$3.45", "average revenue per abandoned cart email"),
        ],
        "angle": (
            "Agentic email democratizes operational scale for the small business sector. A single "
            "proprietor can mimic the structure of a much larger corporation: AI analyzes incoming "
            "inquiries, queries the internal database for product availability, and drafts "
            "personalized responses with tailored discount codes. AI lowers the barrier to "
            "exceptional customer experience."
        ),
        "sources": [
            ("OptinMonster Email Stats 2026", "https://optinmonster.com/"),
            ("ElectroIQ Personalization", "https://electroiq.com/"),
            ("MailMend Personalization", "https://mailmend.io/"),
        ],
    },
]


def _format_brief(topic: dict) -> str:
    """Build a structured brief the writer can cite verbatim."""
    metrics_lines = "\n".join(f"- {value}: {label}" for value, label in topic["metrics"])
    sources_lines = "\n".join(f"- [{name}]({url})" for name, url in topic["sources"])
    return (
        "VERIFIED METRICS (cite each with one of the source URLs below; never invent numbers):\n"
        f"{metrics_lines}\n\n"
        "ANALYTICAL ANGLE (use as second-order insight, integrate into one H2 section):\n"
        f"{topic['angle']}\n\n"
        "SOURCES TO CITE INLINE (pick contextually appropriate URL per stat):\n"
        f"{sources_lines}\n\n"
        "INSTRUCTIONS:\n"
        "- Cite each metric with its source: ([Source Name](url), 2025).\n"
        "- The Quick Answer box and at least one H2 must contain a stat with citation.\n"
        "- Include 2-3 [INTERNAL-LINK: anchor → topic] placeholders.\n"
        "- Add a FAQ section with 3-5 Q&A; each answer cites one stat from the metrics."
    )


def main() -> int:
    inserted = []
    for t in TOPICS:
        brief = _format_brief(t)
        req_id = store.insert_request(
            source="seo",
            topic=t["topic"],
            keywords=t["keywords"],
            brief=brief,
            requested_by="research",
        )
        inserted.append((req_id, t["topic"], t["category"]))

    print(f"Inserted {len(inserted)} article requests:")
    for rid, topic, cat in inserted:
        print(f"  {rid}  [{cat:18s}]  {topic}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
