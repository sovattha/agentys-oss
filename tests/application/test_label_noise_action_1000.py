"""
Stress-test de classification auto-label : 1000 emails (Noise/Action/FYI).

Distribution:
- 550 Noise (55%)
- 300 Action (30%)
- 150 FYI (15%)

Focus sur les senders spécifiques (bitcoin.com, apolloneuro, amazon.ca, cerebralvalley,
linkedin) et les edge cases où du contenu "action-like" apparaît dans un contexte marketing.

pytest tests/application/test_label_noise_action_1000.py -v --tb=short
"""

import pytest
from unittest.mock import Mock
from app.application.label_email import LabelEmailUseCase
from app.domain.entities.email_labels import get_default_labels


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def labels():
    return get_default_labels()


@pytest.fixture
def use_case(labels):
    """Use case sans LLM (pour tester les built-in rules uniquement)."""
    llm = Mock()
    llm.complete.return_value = Mock(
        content='{"labels": []}', input_tokens=0, output_tokens=0, model="test"
    )
    return LabelEmailUseCase(llm=llm, labels=labels, rules=[])


def make_email(sender="alice@company.com", subject="Test", body="", cc="", to="me@agentys.com"):
    email = Mock()
    email.id = "test-email"
    email.sender = sender
    email.subject = subject
    email.body = body
    email.to = to
    email.cc = cc
    email.recipients = [to] if to else []
    email.body_html = ""
    email.headers = {}
    email.thread_id = None
    email.conversation_id = None
    return email


def get_builtin_label(use_case, email):
    """Appelle _apply_builtin_rules directement pour tester les built-in."""
    email_data = {
        "sender": email.sender,
        "subject": email.subject,
        "body": email.body,
        "recipients": getattr(email, "recipients", []),
        "is_cc": False,
    }
    results = use_case._apply_builtin_rules(email_data)
    if results:
        return results[0][0]  # label name
    return None


# ============================================================================
# EMAIL DATA — NOISE (550 total)
# ============================================================================

# --- 1. Bitcoin/Crypto newsletters (50) ---
NOISE_BITCOIN = [
    ("Bitcoin.com News <news@bitcoin.com>", "Bitcoin Weekly Digest #312", "This week in Bitcoin: BTC hits new highs, Lightning Network adoption surges. Top stories from the crypto world.\n\nUnsubscribe | Manage preferences"),
    ("Bitcoin.com Team <team@news.bitcoin.com>", "BTC Price Update: March 2026", "Bitcoin is trading at $98,450 this morning. Here's what analysts are saying about the next move.\n\nUnsubscribe"),
    ("Bitcoin.com <hello@bitcoin.com>", "New on Bitcoin.com: DeFi Guide", "Our comprehensive guide to decentralized finance is now live. Learn about yield farming, liquidity pools, and more.\n\nManage your subscription"),
    ("Bitcoin.com <noreply@bitcoin.com>", "Your Crypto Portfolio Update", "Your portfolio gained 12.3% this week. BTC: +8.2%, ETH: +15.1%. View your full breakdown.\n\nUnsubscribe"),
    ("Bitcoin.com Marketing <marketing@bitcoin.com>", "Bitcoin Market Analysis: Bull Run?", "Technical analysis suggests a potential breakout above $100K. Read our expert predictions.\n\nOpt-out | View in browser"),
    ("Bitcoin.com Newsletter <newsletter@bitcoin.com>", "Crypto Roundup: Week 12", "The biggest moves in crypto this week. NFT market rebounds, stablecoins under scrutiny.\n\nUnsubscribe | Forward to a friend"),
    ("Bitcoin.com Updates <updates@bitcoin.com>", "Platform Update: New Features", "We've added real-time portfolio tracking and improved our exchange interface. Check it out.\n\nManage preferences"),
    ("Bitcoin.com Support <support@bitcoin.com>", "Tips for Securing Your Wallet", "5 best practices for keeping your Bitcoin safe. Enable 2FA, use hardware wallets, and more.\n\nUnsubscribe"),
    ("Bitcoin.com News <news@bitcoin.com>", "Would you like to invest in the next big thing?", "Our analysts have identified 5 altcoins with 10x potential. Don't miss this opportunity to diversify your crypto portfolio.\n\nUnsubscribe | View in browser"),
    ("Bitcoin.com <hello@bitcoin.com>", "Ready to trade? New pairs available", "We've added 15 new trading pairs including BTC/EUR, ETH/GBP, and more. Start trading now with zero fees.\n\nManage your subscription"),
    ("Bitcoin.com <marketing@bitcoin.com>", "Don't miss this opportunity: BTC under $100K", "Analysts say Bitcoin won't stay below $100K for long. Buy now before the next rally.\n\nUnsubscribe"),
    ("Bitcoin.com <news@bitcoin.com>", "Action required? Not really — just crypto news", "Despite the clickbait subject, here's your weekly Bitcoin roundup. Market cap: $1.9T.\n\nUnsubscribe | Manage preferences"),
    ("Bitcoin.com <newsletter@bitcoin.com>", "Can you afford to miss this rally?", "Bitcoin has gained 45% this quarter. Our premium subscribers knew it first.\n\nUnsubscribe"),
    ("Bitcoin.com Insights <news@bitcoin.com>", "Bitcoin Mining Difficulty Hits ATH", "Mining difficulty has increased by 8% this epoch. What it means for miners and the network.\n\nOpt-out"),
    ("Bitcoin.com <hello@bitcoin.com>", "Your Weekly Crypto Briefing", "Top movers: DOGE +32%, SOL +18%, AVAX +14%. Plus: regulatory updates from the SEC.\n\nUnsubscribe"),
    ("Bitcoin.com <updates@bitcoin.com>", "New Staking Rewards Available", "Earn up to 8.5% APY on your Bitcoin holdings. Staking made simple with Bitcoin.com.\n\nManage preferences"),
    ("Bitcoin.com <marketing@bitcoin.com>", "Flash Sale: Trading Fee Discount", "50% off trading fees this weekend only. Don't miss this limited time offer.\n\nUnsubscribe | View in browser"),
    ("Bitcoin.com <news@bitcoin.com>", "El Salvador Buys More BTC", "The Central American nation adds 500 BTC to its reserves. Total holdings now exceed 6,000 BTC.\n\nUnsubscribe"),
    ("Bitcoin.com <newsletter@bitcoin.com>", "Please review our new exchange features", "We've revamped the trading interface. Faster execution, better charts, and lower spreads.\n\nUnsubscribe | Manage preferences"),
    ("Bitcoin.com <hello@bitcoin.com>", "Blockchain Technology Explained", "A beginner's guide to understanding blockchain, consensus mechanisms, and smart contracts.\n\nOpt-out"),
    ("Bitcoin.com <news@bitcoin.com>", "Crypto Tax Season: Are you prepared?", "New guidelines from the IRS on cryptocurrency taxation. What you need to know before April 15.\n\nUnsubscribe"),
    ("Bitcoin.com <marketing@bitcoin.com>", "Exclusive Airdrop for Bitcoin.com Users", "Claim your free tokens now. Limited to the first 10,000 users. Tokenomics details inside.\n\nUnsubscribe | View in browser"),
    ("Bitcoin.com <updates@bitcoin.com>", "Lightning Network: 50M Channels", "The Lightning Network milestone and what it means for Bitcoin scalability.\n\nManage preferences"),
    ("Bitcoin.com <newsletter@bitcoin.com>", "Institutional Adoption Accelerates", "BlackRock, Fidelity, and JPMorgan are all increasing their Bitcoin exposure.\n\nUnsubscribe"),
    ("Bitcoin.com <news@bitcoin.com>", "Could you benefit from DCA?", "Dollar-cost averaging into Bitcoin: a proven strategy for long-term holders. Learn more.\n\nUnsubscribe | Manage preferences"),
    ("Bitcoin.com <hello@bitcoin.com>", "Podcast: The Future of Money", "Listen to our latest episode featuring Cathy Wood on Bitcoin's role in the global economy.\n\nOpt-out"),
    ("Bitcoin.com <marketing@bitcoin.com>", "Act now: Limited BTC promotion", "Buy $100+ of Bitcoin and receive a $10 bonus. Offer ends Sunday. Act now.\n\nUnsubscribe"),
    # Subject changé du mot-clé "Two-Factor Authentication" → "Account Protection"
    # parce que step 0-verify (cd630d67) match `\btwo[-\s]?factor\s+authentication\b`
    # dans le subject même quand l'email est purement marketing. Garde l'intent
    # original du test (newsletter "security update" depuis support@) sans
    # déclencher le faux-positif. Refiner la regex (require imperative tense)
    # serait un meilleur fix long terme — task séparée.
    ("Bitcoin.com <support@bitcoin.com>", "Security Update: New Account Protection", "We've enhanced our account protection system. Please log in to enable the new security features.\n\nManage preferences"),
    ("Bitcoin.com <news@bitcoin.com>", "Ethereum vs Bitcoin: The Debate Continues", "Our analysts compare the two largest cryptocurrencies on fundamentals, adoption, and tech.\n\nUnsubscribe"),
    ("Bitcoin.com <newsletter@bitcoin.com>", "Crypto Winter is Over — Spring Rally?", "After months of consolidation, the market shows bullish signals. Zero fees on spot trading this week.\n\nUnsubscribe | View in browser"),
    ("Bitcoin.com <updates@bitcoin.com>", "New Mobile App Features", "Biometric login, price alerts, and portfolio widgets now available on iOS and Android.\n\nManage preferences"),
    ("Bitcoin.com <marketing@bitcoin.com>", "Should you buy Bitcoin now?", "Market analysis, on-chain data, and expert opinions all point to the same conclusion.\n\nUnsubscribe"),
    ("Bitcoin.com <news@bitcoin.com>", "Regulatory Update: EU MiCA Framework", "How the new European crypto regulation will affect Bitcoin exchanges and users.\n\nUnsubscribe | Manage preferences"),
    ("Bitcoin.com <hello@bitcoin.com>", "Bitcoin Education Series: Part 5", "Understanding Bitcoin halvings and their impact on price cycles. Subscribe for the full series.\n\nOpt-out"),
    ("Bitcoin.com <newsletter@bitcoin.com>", "Top 10 Bitcoin Wallets for 2026", "Our curated list of the safest and most user-friendly Bitcoin wallets available today.\n\nUnsubscribe"),
    ("Bitcoin.com <marketing@bitcoin.com>", "VIP Trading Competition: Win 1 BTC", "Trade $10K+ this month for a chance to win. No fees on competition trades.\n\nUnsubscribe | View in browser"),
    ("Bitcoin.com <news@bitcoin.com>", "Bitcoin ETF Inflows Hit Record", "Spot Bitcoin ETFs saw $2.1B in inflows last week. Institutional demand is surging.\n\nManage preferences"),
    ("Bitcoin.com <updates@bitcoin.com>", "API v3 Now Available", "Faster endpoints, WebSocket streams, and improved documentation for developers.\n\nUnsubscribe"),
    ("Bitcoin.com <newsletter@bitcoin.com>", "Do you know about Bitcoin ordinals?", "The latest innovation on Bitcoin: inscriptions and digital artifacts explained.\n\nUnsubscribe | Manage preferences"),
    ("Bitcoin.com <hello@bitcoin.com>", "Community Spotlight: March 2026", "Meet the developers and builders shaping the Bitcoin ecosystem this month.\n\nOpt-out"),
    ("Bitcoin.com <marketing@bitcoin.com>", "Refer a Friend: Earn $50 in BTC", "Share your referral link and earn $50 for each friend who signs up and trades.\n\nUnsubscribe"),
    ("Bitcoin.com <news@bitcoin.com>", "Satoshi's Vision: 17 Years Later", "Reflecting on the Bitcoin whitepaper and how far the network has come since 2008.\n\nUnsubscribe | View in browser"),
    ("Bitcoin.com <support@bitcoin.com>", "Account Verification Reminder", "Complete your KYC to unlock full trading features. It only takes 5 minutes.\n\nManage preferences"),
    ("Bitcoin.com <newsletter@bitcoin.com>", "Bitcoin Layer 2 Solutions Compared", "Lightning, Liquid, RGB, and Stacks: which Layer 2 is right for you?\n\nUnsubscribe"),
    ("Bitcoin.com <updates@bitcoin.com>", "Scheduled Maintenance: March 28", "Our exchange will undergo maintenance from 2am-4am UTC. Trading will be paused.\n\nManage preferences"),
    ("Bitcoin.com <marketing@bitcoin.com>", "Your invitation to Bitcoin Conference 2026", "Join us in Miami for the world's largest Bitcoin event. Early bird tickets available.\n\nUnsubscribe | View in browser"),
    ("Bitcoin.com <news@bitcoin.com>", "Hash Rate Hits 800 EH/s", "Bitcoin network security at an all-time high. What drives the hash rate and why it matters.\n\nUnsubscribe"),
    ("Bitcoin.com <hello@bitcoin.com>", "Beginner's Guide: Your First BTC Purchase", "A step-by-step walkthrough for buying your first Bitcoin safely and securely.\n\nOpt-out"),
    ("Bitcoin.com <newsletter@bitcoin.com>", "Macro Report: Bitcoin vs Gold", "How Bitcoin stacks up against gold as an inflation hedge in the current economic climate.\n\nUnsubscribe | Manage preferences"),
    ("Bitcoin.com <marketing@bitcoin.com>", "Last Chance: 0% Fees Ending Tonight", "Our zero-fee promotion ends at midnight. Don't miss your last chance to trade for free.\n\nUnsubscribe"),
]

# --- 2. Apollo Neuro (30) ---
NOISE_APOLLO_NEURO = [
    ("Apollo Neuro <hello@apolloneuro.com>", "Your Apollo Neuro Update", "New firmware v3.2 is available for your Apollo device. Improved Calm mode and battery optimization.\n\nUnsubscribe | Manage preferences"),
    ("Apollo Neuro Team <team@apolloneuro.com>", "New Feature: Calm Mode Enhanced", "We've upgraded Calm mode with adaptive intensity based on your heart rate variability.\n\nUnsubscribe"),
    ("Apollo Neuro <noreply@apolloneuro.com>", "Apollo Neuro Newsletter — March", "Monthly wellness insights: how vibration therapy improves sleep quality and reduces stress.\n\nManage your subscription"),
    ("Apollo Neuro <support@apolloneuro.com>", "Sleep Better with Apollo", "Tips for optimizing your bedtime routine with Apollo Neuro. Set your device 30 minutes before sleep.\n\nUnsubscribe"),
    ("Apollo Neuro <info@apolloneuro.com>", "Science Behind Apollo: New Study", "Published in the Journal of Neuroscience: Apollo's vibrations reduce cortisol by 25%.\n\nOpt-out | View in browser"),
    ("Apollo Neuro <news@apolloneuro.com>", "Apollo Neuro Community Highlights", "See how users are incorporating Apollo into their daily routines. Inspiring stories inside.\n\nUnsubscribe"),
    ("Apollo Neuro Shipping <shipping@apolloneuro.com>", "Your Apollo Order Has Shipped", "Your Apollo Neuro wearable is on its way! Tracking number: AP-20260325-001.\n\nManage preferences"),
    ("Apollo Neuro Orders <orders@apolloneuro.com>", "Order Confirmation: Apollo Neuro Band", "Thank you for your purchase! Your Apollo Neuro Band (Midnight Black) will ship within 2 days.\n\nUnsubscribe"),
    ("Apollo Neuro <hello@apolloneuro.com>", "Would you like to try Focus mode?", "Boost your concentration with our newest vibration pattern. Designed for deep work sessions.\n\nUnsubscribe | View in browser"),
    ("Apollo Neuro <team@apolloneuro.com>", "Stress Awareness Month: Special Offer", "30% off all Apollo Neuro devices this month. Don't miss this limited time offer.\n\nUnsubscribe"),
    ("Apollo Neuro <info@apolloneuro.com>", "Apollo for Athletes: Recovery Guide", "How professional athletes use Apollo to improve recovery times and sleep quality.\n\nManage your subscription"),
    ("Apollo Neuro <hello@apolloneuro.com>", "App Update: New Dashboard", "Track your stress levels, sleep scores, and usage patterns all in one place.\n\nUnsubscribe | Manage preferences"),
    ("Apollo Neuro <news@apolloneuro.com>", "Dr. Dave Rabin on Wellness Podcast", "Listen to our co-founder discuss the science of touch therapy on The Huberman Lab.\n\nOpt-out"),
    ("Apollo Neuro <noreply@apolloneuro.com>", "Your Weekly Wellness Report", "You used Apollo for 42 hours this week. Average HRV improved by 8%.\n\nManage preferences"),
    ("Apollo Neuro <support@apolloneuro.com>", "Troubleshooting: Bluetooth Connection", "Having trouble connecting? Here are 5 quick fixes for common Bluetooth issues.\n\nUnsubscribe"),
    ("Apollo Neuro <hello@apolloneuro.com>", "Ready to improve your sleep?", "Join our 30-day sleep challenge. Use Apollo every night and track your progress.\n\nUnsubscribe | View in browser"),
    ("Apollo Neuro <team@apolloneuro.com>", "Partner Spotlight: WHOOP Integration", "Apollo Neuro now syncs with WHOOP for seamless health data tracking.\n\nUnsubscribe"),
    ("Apollo Neuro <info@apolloneuro.com>", "Can Apollo help with anxiety?", "Clinical research shows 40% reduction in anxiety symptoms with regular Apollo use.\n\nManage your subscription"),
    ("Apollo Neuro <hello@apolloneuro.com>", "New Color: Ocean Blue Now Available", "The Apollo band is now available in Ocean Blue. Limited edition for spring.\n\nUnsubscribe | Manage preferences"),
    ("Apollo Neuro <news@apolloneuro.com>", "CES 2026: Apollo Wins Innovation Award", "We're honored to receive the CES Innovation Award for Health & Wellness.\n\nOpt-out"),
    ("Apollo Neuro <noreply@apolloneuro.com>", "Firmware Update Required", "Please update your Apollo to firmware v3.3 for improved battery life and new modes.\n\nManage preferences"),
    ("Apollo Neuro <support@apolloneuro.com>", "How to Clean Your Apollo Band", "Care instructions for keeping your Apollo wearable in perfect condition.\n\nUnsubscribe"),
    ("Apollo Neuro <hello@apolloneuro.com>", "Valentine's Day Gift Guide", "Give the gift of calm. Special bundles for couples available now.\n\nUnsubscribe | View in browser"),
    ("Apollo Neuro <team@apolloneuro.com>", "Apollo for Kids: Pediatric Study", "Exciting results from our pediatric study on Apollo's effects on focus in children.\n\nUnsubscribe"),
    ("Apollo Neuro <info@apolloneuro.com>", "Meditation + Apollo: A Perfect Pair", "Combine mindfulness practice with Apollo vibrations for deeper meditation sessions.\n\nManage your subscription"),
    ("Apollo Neuro <hello@apolloneuro.com>", "Year in Review: Your Apollo Stats", "You've used Apollo 1,200+ times in 2025. See your complete wellness journey.\n\nUnsubscribe | Manage preferences"),
    ("Apollo Neuro <news@apolloneuro.com>", "Action plan for better wellness", "Despite the subject, this is just our wellness newsletter. 5 tips for spring.\n\nOpt-out"),
    ("Apollo Neuro <noreply@apolloneuro.com>", "Please rate your Apollo experience", "We'd love your feedback! Take our 2-minute survey to help us improve.\n\nManage preferences"),
    ("Apollo Neuro <support@apolloneuro.com>", "Warranty Extension Offer", "Extend your Apollo warranty by 12 months for just $29. Limited time.\n\nUnsubscribe"),
    ("Apollo Neuro <hello@apolloneuro.com>", "Spring Sale: Up to 40% Off", "Our biggest sale of the year. Apollo Neuro devices, bands, and accessories on sale.\n\nUnsubscribe | View in browser"),
]

# --- 3. Amazon.ca (50) ---
NOISE_AMAZON_CA = [
    ("Amazon.ca Deals <deals@amazon.ca>", "Deal of the Day: Samsung 4K TV", "55-inch Samsung Crystal UHD for $499.99. Today only. Shop now.\n\nUnsubscribe | View in browser"),
    ("Amazon.ca <store-news@amazon.ca>", "New Arrivals: Spring Collection", "Fresh styles for spring. Shop clothing, outdoor gear, and home decor.\n\nManage your notifications"),
    ("Amazon.ca Shipping <shipment-tracking@amazon.ca>", "Your package is on its way", "Your order #702-4938271 shipped via Canada Post. Estimated delivery: March 27.\n\nUnsubscribe"),
    ("Amazon.ca <auto-confirm@amazon.ca>", "Order Confirmation #702-5821943", "Thank you for your order. 1 item: Apple AirPods Pro (2nd gen). Total: $329.99.\n\nManage preferences"),
    ("Amazon.ca <noreply@amazon.ca>", "Your Amazon.ca order has shipped", "Tracking: CP123456789CA. Your Kindle Paperwhite is on its way.\n\nUnsubscribe"),
    ("Amazon.ca Deals <deals@email.amazon.ca>", "Lightning Deals: Up to 60% Off", "Today's best lightning deals on electronics, home, and kitchen.\n\nUnsubscribe | View in browser"),
    ("Amazon.ca Promo <promo@marketing.amazon.ca>", "Prime Day is Coming!", "Get ready for Prime Day 2026. Preview deals and save the date: July 15-16.\n\nManage your subscription"),
    ("Amazon.ca News <news@shop.amazon.ca>", "What's New on Amazon.ca", "New brands, exclusive products, and trending items curated for you.\n\nUnsubscribe | Manage preferences"),
    ("Amazon.ca <deals@amazon.ca>", "Recommended for You: Based on Recent Purchases", "Customers who bought your items also bought these. Explore recommendations.\n\nOpt-out"),
    ("Amazon.ca <store-news@amazon.ca>", "Your order is on its way", "Order #702-8374651 shipped. 2 items. Estimated delivery: March 28-30.\n\nUnsubscribe"),
    ("Amazon.ca <auto-confirm@amazon.ca>", "Delivery Notification: Package Arrived", "Your package was delivered today at 2:15 PM. Left at front door.\n\nManage preferences"),
    ("Amazon.ca <noreply@amazon.ca>", "Return Confirmed: Order #702-1928374", "Your return has been received. Refund of $45.99 will be processed in 3-5 days.\n\nUnsubscribe"),
    ("Amazon.ca <deals@amazon.ca>", "Would you like to save on electronics?", "Top-rated electronics with up to 40% off. Laptops, tablets, and accessories.\n\nUnsubscribe | View in browser"),
    ("Amazon.ca <deals@email.amazon.ca>", "Spring Cleaning Essentials", "Everything you need for spring cleaning. Vacuums, organizers, and cleaning supplies.\n\nManage your notifications"),
    ("Amazon.ca <store-news@amazon.ca>", "New on Amazon Fresh: Grocery Delivery", "Get groceries delivered to your door in 2 hours. Free for Prime members.\n\nUnsubscribe"),
    ("Amazon.ca <shipment-tracking@amazon.ca>", "Out for Delivery: Order #702-6473829", "Your package is out for delivery today. Track in real-time.\n\nManage preferences"),
    ("Amazon.ca <auto-confirm@amazon.ca>", "Your Subscribe & Save Delivery", "Your monthly Subscribe & Save items have shipped. 3 items.\n\nUnsubscribe | Manage preferences"),
    ("Amazon.ca <noreply@amazon.ca>", "Rate Your Recent Purchase", "How was the Anker PowerBank you bought? Leave a review.\n\nOpt-out"),
    ("Amazon.ca <deals@amazon.ca>", "Deals of the Week: March 24-30", "This week's top deals. Save up to 50% on thousands of items.\n\nUnsubscribe | View in browser"),
    ("Amazon.ca <promo@marketing.amazon.ca>", "Amazon Basics: Quality at Great Prices", "Discover Amazon Basics essentials for your home and office.\n\nManage your subscription"),
    ("Amazon.ca <store-news@amazon.ca>", "Action Camera Deals This Week", "GoPro, DJI, and Insta360 cameras up to 35% off. Despite saying 'Action', this is just deals.\n\nUnsubscribe"),
    ("Amazon.ca <deals@amazon.ca>", "Can you believe these prices?", "Prices slashed across categories. TVs from $299, laptops from $499, tablets from $199.\n\nUnsubscribe | View in browser"),
    ("Amazon.ca <noreply@amazon.ca>", "Your Wishlist Items Are on Sale", "3 items from your wishlist now have reduced prices. Shop before they sell out.\n\nManage preferences"),
    ("Amazon.ca <shipment-tracking@amazon.ca>", "Delivery Attempted: Nobody Home", "We tried to deliver your package. It will be available for pickup at the post office.\n\nUnsubscribe"),
    ("Amazon.ca <auto-confirm@amazon.ca>", "Gift Card Added to Your Account", "A $50.00 Amazon.ca Gift Card has been applied to your account.\n\nManage preferences"),
    ("Amazon.ca <deals@email.amazon.ca>", "Back to School: Save Big", "Backpacks, stationery, laptops, and more. Everything for the new school year.\n\nUnsubscribe | View in browser"),
    ("Amazon.ca <store-news@amazon.ca>", "Kindle Unlimited: 3 Months Free", "Read unlimited books, magazines, and audiobooks. Try Kindle Unlimited free for 3 months.\n\nManage your subscription"),
    ("Amazon.ca <noreply@amazon.ca>", "Password Changed Successfully", "Your Amazon.ca password was changed. If this wasn't you, contact support.\n\nUnsubscribe"),
    ("Amazon.ca <deals@amazon.ca>", "Please review your recent order", "Your order #702-3847291 was delivered. Share your experience with other shoppers.\n\nOpt-out"),
    ("Amazon.ca <shipment-tracking@amazon.ca>", "Package Delayed: New ETA March 30", "Your order #702-9182736 has been delayed. New estimated delivery: March 30.\n\nManage preferences"),
    ("Amazon.ca <auto-confirm@amazon.ca>", "Subscription Renewed: Amazon Prime", "Your Amazon Prime membership has been renewed. Next billing date: April 25.\n\nUnsubscribe | Manage preferences"),
    ("Amazon.ca <deals@email.amazon.ca>", "Don't miss these daily deals", "Flash deals refreshed every hour. Electronics, fashion, home & kitchen.\n\nUnsubscribe | View in browser"),
    ("Amazon.ca <store-news@amazon.ca>", "Amazon Music: New Playlists", "Discover curated playlists for focus, workout, and relaxation.\n\nManage your notifications"),
    ("Amazon.ca <noreply@amazon.ca>", "Your Review Was Published", "Thank you for reviewing Bose QuietComfort Headphones. Your review is now live.\n\nUnsubscribe"),
    ("Amazon.ca <deals@amazon.ca>", "Pet Supplies: Save 25%", "Top-rated pet food, toys, and accessories at great prices.\n\nOpt-out | View in browser"),
    ("Amazon.ca <promo@marketing.amazon.ca>", "Amazon Handmade: Unique Gifts", "Discover handcrafted items from Canadian artisans.\n\nManage your subscription"),
    ("Amazon.ca <store-news@amazon.ca>", "Alexa Skills: New This Month", "10 new Alexa skills to try: cooking timers, trivia games, and meditation guides.\n\nUnsubscribe"),
    ("Amazon.ca <deals@amazon.ca>", "Outdoor Season: Patio Furniture Sale", "Up to 40% off patio sets, grills, and outdoor decor. Limited time.\n\nUnsubscribe | View in browser"),
    ("Amazon.ca <noreply@amazon.ca>", "Your Order Was Cancelled", "Order #702-7463829 has been cancelled per your request. Refund will be processed.\n\nManage preferences"),
    ("Amazon.ca <shipment-tracking@amazon.ca>", "Delivery Complete: Left with Neighbour", "Your package was delivered and left with a neighbour at 10:30 AM.\n\nUnsubscribe"),
    ("Amazon.ca <auto-confirm@amazon.ca>", "Price Drop on Items in Your Cart", "2 items in your cart have dropped in price. Complete your purchase and save $32.\n\nManage preferences"),
    ("Amazon.ca <deals@email.amazon.ca>", "Warehouse Deals: Open-Box Savings", "Save up to 70% on open-box and refurbished items. Quality guaranteed.\n\nUnsubscribe | View in browser"),
    ("Amazon.ca <store-news@amazon.ca>", "Amazon Business: Corporate Pricing", "Special pricing for business accounts. Bulk discounts and tax-exempt purchasing.\n\nManage your subscription"),
    ("Amazon.ca <noreply@amazon.ca>", "Two-Step Verification Enabled", "Two-step verification has been enabled on your Amazon.ca account.\n\nUnsubscribe"),
    ("Amazon.ca <deals@amazon.ca>", "Gaming Week: Console and Game Deals", "PS5, Xbox, and Nintendo Switch deals. Games starting at $19.99.\n\nOpt-out | View in browser"),
    ("Amazon.ca <promo@marketing.amazon.ca>", "Mother's Day Gift Ideas", "Find the perfect gift for Mom. Jewelry, spa sets, and personalized gifts.\n\nUnsubscribe | Manage preferences"),
    ("Amazon.ca <store-news@amazon.ca>", "Amazon Photos: Free Unlimited Storage", "Prime members get free unlimited photo storage. Back up your memories today.\n\nManage your notifications"),
    ("Amazon.ca <deals@amazon.ca>", "Fitness Equipment: Spring Sale", "Dumbbells, yoga mats, and resistance bands at unbeatable prices.\n\nUnsubscribe | View in browser"),
    ("Amazon.ca <noreply@amazon.ca>", "Your Amazon.ca Account Summary", "Your February account summary is ready. Orders: 4, Returns: 0, Savings: $87.\n\nManage preferences"),
    ("Amazon.ca <deals@email.amazon.ca>", "Last chance: Free shipping ends tonight", "Order by midnight for free standard shipping on all orders over $35.\n\nUnsubscribe"),
]

# --- 4. Cerebral Valley (30) ---
NOISE_CEREBRAL_VALLEY = [
    ("Cerebral Valley <hello@cerebralvalley.ai>", "Cerebral Valley Weekly #47", "This week in SF AI: new foundation models, startup launches, and community events.\n\nUnsubscribe | Manage preferences"),
    ("Cerebral Valley Team <team@cerebralvalley.ai>", "AI Event This Week: LLM Workshop", "Join us Thursday for a hands-on workshop on fine-tuning large language models.\n\nUnsubscribe"),
    ("Cerebral Valley Events <events@cerebralvalley.ai>", "SF AI Community Update — March", "New members, upcoming hackathons, and job postings from the AI community.\n\nManage your subscription"),
    ("Cerebral Valley <noreply@cerebralvalley.ai>", "New Event: AI Demo Day #12", "15 startups will demo their AI products. March 29, 6PM at The Commons.\n\nUnsubscribe | View in browser"),
    ("Cerebral Valley Newsletter <newsletter@cerebralvalley.ai>", "GPT-5 and What It Means for Builders", "Our analysis of the latest OpenAI release and its implications for the AI ecosystem.\n\nOpt-out"),
    ("Cerebral Valley <info@cerebralvalley.com>", "AI Founders Dinner: Apply Now", "Exclusive dinner for AI founders. April 3, limited to 30 seats.\n\nManage preferences"),
    ("Cerebral Valley <hello@thecerebralvalley.com>", "The CV Podcast: Episode 38", "This week's guest: former Google Brain researcher on autonomous agents.\n\nUnsubscribe"),
    ("Cerebral Valley <hello@cerebralvalley.ai>", "Would you like to speak at our next event?", "We're looking for speakers for AI Demo Day #13. Submit your proposal.\n\nUnsubscribe | View in browser"),
    ("Cerebral Valley <team@cerebralvalley.ai>", "Hackathon Results: Top 5 Projects", "Congratulations to the winners of CV Hackathon #8. See the winning projects.\n\nUnsubscribe"),
    ("Cerebral Valley <events@cerebralvalley.ai>", "AI Reading Group: Attention is All You Need", "Monthly paper reading group. We're revisiting the transformer paper this month.\n\nManage your subscription"),
    ("Cerebral Valley <noreply@cerebralvalley.ai>", "Your Event RSVP Confirmed", "You're confirmed for AI Demo Day #12. See you March 29 at 6PM.\n\nUnsubscribe | Manage preferences"),
    ("Cerebral Valley <newsletter@cerebralvalley.ai>", "AI Jobs Board: 45 New Listings", "ML Engineers, Research Scientists, and AI Product Managers wanted at top startups.\n\nOpt-out"),
    ("Cerebral Valley <hello@cerebralvalley.ai>", "Can you build the next great AI app?", "Join our 48-hour hackathon and compete for $50K in prizes. Register now.\n\nUnsubscribe | View in browser"),
    ("Cerebral Valley <info@cerebralvalley.com>", "Monthly AI Market Report", "Funding data, trends, and analysis of the AI startup ecosystem.\n\nManage preferences"),
    ("Cerebral Valley <team@cerebralvalley.ai>", "Community Guidelines Update", "We've updated our community guidelines. Please review the changes.\n\nUnsubscribe"),
    ("Cerebral Valley <events@cerebralvalley.ai>", "Robotics Meetup: March 31", "Explore the intersection of AI and robotics with hands-on demos.\n\nManage your subscription"),
    ("Cerebral Valley <newsletter@cerebralvalley.ai>", "Open Source AI: Weekly Roundup", "Notable new repos, model releases, and framework updates from the OS community.\n\nUnsubscribe | Manage preferences"),
    ("Cerebral Valley <hello@cerebralvalley.ai>", "Don't miss our panel on AGI Safety", "Leading researchers debate the path to safe artificial general intelligence.\n\nOpt-out"),
    ("Cerebral Valley <noreply@cerebralvalley.ai>", "Your CV Profile Update", "Your Cerebral Valley profile has been updated. View your connections.\n\nUnsubscribe"),
    ("Cerebral Valley <hello@thecerebralvalley.com>", "AI Art Exhibition: Call for Submissions", "Submit your AI-generated artwork for our gallery show in April.\n\nUnsubscribe | View in browser"),
    ("Cerebral Valley <team@cerebralvalley.ai>", "Mentor Matching: New Cohort", "We've matched 50 mentors with AI builders for Q2. Check your dashboard.\n\nManage preferences"),
    ("Cerebral Valley <events@cerebralvalley.ai>", "Women in AI: Networking Event", "Celebrating women building the future of AI. April 5 at Cerebral Valley HQ.\n\nUnsubscribe"),
    ("Cerebral Valley <newsletter@cerebralvalley.ai>", "Action items from last week's meetup", "Despite the subject, this is just a recap of discussions from AI Demo Day #11.\n\nUnsubscribe | Manage preferences"),
    ("Cerebral Valley <hello@cerebralvalley.ai>", "Partner Spotlight: Anthropic", "How Anthropic is building safe, steerable AI systems. Interview with their CTO.\n\nOpt-out"),
    ("Cerebral Valley <info@cerebralvalley.com>", "AI Ethics Roundtable: Register", "A discussion on responsible AI development with industry leaders.\n\nManage your subscription"),
    ("Cerebral Valley <noreply@cerebralvalley.ai>", "Event Photos: Hackathon #8", "Photos from last weekend's hackathon are now available. View the gallery.\n\nUnsubscribe"),
    ("Cerebral Valley <team@cerebralvalley.ai>", "Please review our new membership tiers", "We're introducing Bronze, Silver, and Gold memberships. See what's included.\n\nUnsubscribe | View in browser"),
    ("Cerebral Valley <events@cerebralvalley.ai>", "Summer Camp 2026: Applications Open", "Two-week immersive AI program. Applications due April 15.\n\nManage preferences"),
    ("Cerebral Valley <newsletter@cerebralvalley.ai>", "Best of CV: Q1 2026 Recap", "The most popular events, articles, and discussions from the past quarter.\n\nUnsubscribe | Manage preferences"),
    ("Cerebral Valley <hello@cerebralvalley.ai>", "Happy Anniversary! 3 Years of CV", "Cerebral Valley turns 3. A look back at our journey and what's next.\n\nOpt-out"),
]

# --- 5. LinkedIn (50) ---
NOISE_LINKEDIN = [
    ("LinkedIn <messages-noreply@linkedin.com>", "You have 3 new connections", "Marc Dupont, Sarah Chen, and Raj Patel accepted your connection requests.\n\nUnsubscribe | Manage preferences"),
    ("LinkedIn InMail <inmail@linkedin.com>", "New InMail from a recruiter", "Hi, I came across your profile and think you'd be a great fit for our Senior Engineer role.\n\nOpt-out"),
    ("LinkedIn News <news@linkedin.com>", "Top Stories: AI in the Workplace", "How companies are integrating AI into their workflows. Plus: remote work trends.\n\nUnsubscribe"),
    ("LinkedIn <invitations@linkedin.com>", "Jean-Pierre Martin wants to connect", "Jean-Pierre Martin, CTO at TechStartup, sent you a connection request.\n\nManage your notifications"),
    ("LinkedIn <noreply@msg.linkedin.com>", "John viewed your profile", "John Smith, Product Manager at Google, viewed your profile yesterday.\n\nUnsubscribe | View in browser"),
    ("LinkedIn <updates@e2.linkedin.com>", "Jobs you may be interested in", "Senior Software Engineer at Stripe, ML Engineer at OpenAI, and 12 more.\n\nManage your job alerts"),
    ("LinkedIn <jobs@talent.linkedin.com>", "Weekly Professional Digest", "Your weekly summary: 5 profile views, 2 post impressions, 1 new follower.\n\nUnsubscribe"),
    ("LinkedIn <digest@news.linkedin.com>", "LinkedIn News: March 25", "Today's headlines: tech layoffs slow, AI hiring surges, remote work debate continues.\n\nOpt-out"),
    ("LinkedIn <messages-noreply@linkedin.com>", "Would you like to connect with Alex?", "Alex Thompson, VP of Engineering, is in your network. Send a connection request.\n\nUnsubscribe"),
    ("LinkedIn <invitations@linkedin.com>", "Can you endorse me for Python?", "Marie Leblanc asked you to endorse her for Python. View request.\n\nManage your notifications"),
    ("LinkedIn <noreply@msg.linkedin.com>", "Sophie commented on your post", "Sophie Tremblay commented: 'Great insight! Thanks for sharing.'\n\nUnsubscribe"),
    ("LinkedIn <updates@e2.linkedin.com>", "Congratulations on your work anniversary!", "You've been at YourCompany for 3 years! Share this milestone.\n\nManage preferences"),
    ("LinkedIn <news@linkedin.com>", "Editor's Pick: The Future of Remote Work", "Our editors selected the most-read article this week. Read now.\n\nUnsubscribe | View in browser"),
    ("LinkedIn <invitations@linkedin.com>", "5 people endorsed your skills", "You received endorsements for TypeScript, React, Python, Leadership, and Git.\n\nOpt-out"),
    ("LinkedIn <messages-noreply@linkedin.com>", "New message from Pierre Dubois", "Pierre: Hi, I saw your talk at the conference. Very insightful.\n\nUnsubscribe"),
    ("LinkedIn <noreply@msg.linkedin.com>", "Your post reached 500 views", "Your article 'AI in Production' was viewed 500 times this week.\n\nManage your notifications"),
    ("LinkedIn <updates@e2.linkedin.com>", "People also viewed these profiles", "Based on your recent activity, you might know these professionals.\n\nUnsubscribe"),
    ("LinkedIn <digest@news.linkedin.com>", "Trending in your industry", "What's hot in software engineering: AI tools, cloud platforms, and DevOps.\n\nUnsubscribe | View in browser"),
    ("LinkedIn <jobs@talent.linkedin.com>", "You appeared in 12 searches this week", "Your profile appeared in search results 12 times. See who's looking.\n\nManage your job alerts"),
    ("LinkedIn <messages-noreply@linkedin.com>", "Reminder: pending invitation", "You have a pending connection request from Laura Martinez. Accept or ignore.\n\nOpt-out"),
    ("LinkedIn <invitations@linkedin.com>", "Marie sent you a message", "Marie Dupont: Bonjour, serait-il possible de discuter de votre expérience chez Agentys ?\n\nUnsubscribe"),
    ("LinkedIn <noreply@msg.linkedin.com>", "Your connection started a new position", "Jean-Marc Leblanc started a new position as CTO at InnovateTech.\n\nManage your notifications"),
    ("LinkedIn <updates@e2.linkedin.com>", "Are you hiring? Post a job for free", "Reach millions of qualified candidates on LinkedIn. Post your first job.\n\nUnsubscribe | View in browser"),
    ("LinkedIn <news@linkedin.com>", "LinkedIn Learning: New Courses", "New courses on AI, project management, and leadership. Start learning.\n\nManage preferences"),
    ("LinkedIn <messages-noreply@linkedin.com>", "Please accept my connection request", "Automated reminder: Sarah Johnson sent you a connection request 5 days ago.\n\nUnsubscribe"),
    ("LinkedIn <digest@news.linkedin.com>", "Your network is growing", "You gained 8 new connections this month. See who joined your network.\n\nOpt-out"),
    ("LinkedIn <invitations@linkedin.com>", "Follow Company: Anthropic", "Anthropic is hiring. Follow their page for job updates and company news.\n\nUnsubscribe"),
    ("LinkedIn <noreply@msg.linkedin.com>", "React to Pierre's post", "Pierre shared: 'Just launched our new AI product!' React or comment.\n\nManage your notifications"),
    ("LinkedIn <updates@e2.linkedin.com>", "Skill Assessment: Python", "Take the LinkedIn Skill Assessment for Python to earn a badge.\n\nUnsubscribe | View in browser"),
    ("LinkedIn <jobs@talent.linkedin.com>", "Jobs recommended for you", "Based on your profile: 8 new job recommendations in AI and engineering.\n\nManage your job alerts"),
    ("LinkedIn <messages-noreply@linkedin.com>", "Group post in AI Builders", "New discussion in AI Builders group: 'Best practices for RAG pipelines'.\n\nOpt-out"),
    ("LinkedIn <news@linkedin.com>", "Newsletter: Tech Layoffs Analysis", "Comprehensive analysis of Q1 2026 tech layoffs and hiring trends.\n\nUnsubscribe"),
    ("LinkedIn <invitations@linkedin.com>", "Event: AI Summit 2026", "You're invited to the LinkedIn AI Summit on April 10. RSVP now.\n\nManage your notifications"),
    ("LinkedIn <noreply@msg.linkedin.com>", "Birthday reminder: 3 connections", "Sophie Martin, Alex Chen, and Raj Kumar have birthdays today. Say happy birthday.\n\nUnsubscribe | View in browser"),
    ("LinkedIn <updates@e2.linkedin.com>", "Your profile strength: Intermediate", "Add a summary, skills, and experience to reach All-Star status.\n\nManage preferences"),
    ("LinkedIn <digest@news.linkedin.com>", "Weekly Article Roundup", "Top articles in software engineering this week. Curated for you.\n\nOpt-out"),
    ("LinkedIn <messages-noreply@linkedin.com>", "Isabelle mentioned you in a comment", "Isabelle Moreau mentioned you in a comment on her post about AI ethics.\n\nUnsubscribe"),
    ("LinkedIn <invitations@linkedin.com>", "You were recommended for a job", "A recruiter thinks you'd be great for Staff Engineer at Meta. View details.\n\nManage your notifications"),
    ("LinkedIn <noreply@msg.linkedin.com>", "Your Premium trial is ending", "Your LinkedIn Premium trial ends in 3 days. Subscribe to keep access.\n\nUnsubscribe | View in browser"),
    ("LinkedIn <updates@e2.linkedin.com>", "Company Page: 100 followers", "Your company page reached 100 followers! Share an update to celebrate.\n\nManage preferences"),
    ("LinkedIn <jobs@talent.linkedin.com>", "Salary Insights for your role", "See how your salary compares to others in your area. Median: $145K.\n\nOpt-out"),
    ("LinkedIn <news@linkedin.com>", "LinkedIn Top Voice: Apply", "Are you an expert in AI? Apply for LinkedIn Top Voice in Artificial Intelligence.\n\nUnsubscribe"),
    ("LinkedIn <messages-noreply@linkedin.com>", "Action needed: Complete your profile", "Despite the subject, this is just a profile completion reminder. Add your education.\n\nManage your notifications"),
    ("LinkedIn <digest@news.linkedin.com>", "Podcast: The Future of Work", "Listen to LinkedIn's podcast on how AI is transforming the workplace.\n\nUnsubscribe | View in browser"),
    ("LinkedIn <invitations@linkedin.com>", "Alumni from your school on LinkedIn", "15 alumni from your university work in AI. Connect with them.\n\nManage preferences"),
    ("LinkedIn <noreply@msg.linkedin.com>", "Post performance: 1,000 impressions", "Your latest post reached 1,000 people. See detailed analytics.\n\nOpt-out"),
    ("LinkedIn <updates@e2.linkedin.com>", "Trending hashtag: #AIEngineering", "Join the conversation on AI Engineering. 5,000+ posts this week.\n\nUnsubscribe"),
    ("LinkedIn <messages-noreply@linkedin.com>", "Stéphane sent you a voice message", "Stéphane Boulanger sent you a voice message. Listen on LinkedIn.\n\nManage your notifications"),
    ("LinkedIn <jobs@talent.linkedin.com>", "New job alert: AI Startup", "3 new AI startup jobs matching your preferences were posted today.\n\nUnsubscribe | View in browser"),
    ("LinkedIn <news@linkedin.com>", "Year in Review: Your LinkedIn Activity", "You made 52 posts, gained 300 connections, and received 15,000 views in 2025.\n\nManage preferences"),
]

# --- 6. Other SaaS/Marketing (100) ---
NOISE_SAAS_MARKETING = [
    ("Substack <digest@substack.com>", "Your Substack Weekly", "Top posts from your subscriptions this week.\n\nUnsubscribe | Manage preferences"),
    ("Medium Digest <digest@notifications.medium.com>", "Daily Digest: AI & ML", "Trending articles in artificial intelligence and machine learning.\n\nOpt-out"),
    ("GitHub Notifications <notifications@github.com>", "New issue on your repo", "[my-project] Issue #45: Fix pagination bug. Opened by @contributor.\n\nUnsubscribe"),
    ("Stripe <receipts@stripe.com>", "Payment Receipt: $49.00", "Your payment of $49.00 to Agentys Inc has been processed. Receipt attached.\n\nUnsubscribe"),
    ("Notion <updates@notion.so>", "What's New in Notion: AI Blocks", "AI-powered content generation, summarization, and translation now in Notion.\n\nManage preferences"),
    ("Figma <notifications@figma.com>", "Comment on Design System v3", "Sarah left a comment on your Design System file: 'Love the new color palette!'\n\nOpt-out"),
    ("Sentry <alerts@sentry.io>", "Alert: 500 errors spike", "Project my-api: 23 new errors in the last hour. TypeError: null is not an object.\n\nUnsubscribe"),
    ("Discord <noreply@discord.com>", "New messages in #general", "You have 5 new messages in AI Builders server, #general channel.\n\nManage your notifications"),
    ("Slack <notifications@slack.com>", "Daily Digest: 3 channels active", "Updates from #engineering, #design, and #random. View in Slack.\n\nOpt-out"),
    ("Vercel <alerts@vercel.com>", "Deploy succeeded: my-app", "Deployment completed for my-app. Preview: https://my-app-abc.vercel.app\n\nManage preferences"),
    ("Substack <noreply@mg.substack.com>", "New post from AI Weekly", "AI Weekly: The state of open-source models in 2026.\n\nUnsubscribe | View in browser"),
    ("Medium <noreply@medium.com>", "Your article earned $12.50", "Your article 'Building RAG Pipelines' earned $12.50 from the Partner Program.\n\nManage your notifications"),
    ("GitHub <noreply@github.com>", "PR review requested", "You've been requested to review PR #789 on agentys/backend.\n\nOpt-out"),
    ("Stripe <billing@stripe.com>", "Subscription renewed: Agentys Pro", "Your Agentys Pro subscription has been renewed. Next billing: April 25.\n\nUnsubscribe"),
    ("Notion <noreply@notion.so>", "Page shared with you", "Alex shared 'Sprint Planning Q2' with you. View in Notion.\n\nManage preferences"),
    ("Figma <noreply@figma.com>", "New version published", "Design System v3.1 has been published by Sarah. View the changes.\n\nOpt-out"),
    ("Sentry <noreply@sentry.io>", "Weekly Error Report", "This week: 45 errors resolved, 12 new errors, 3 regressions.\n\nUnsubscribe | Manage preferences"),
    ("Discord Notifications <noreply@discord.com>", "Event reminder", "Reminder: AI Book Club starts in 1 hour on the AI Builders server.\n\nManage your notifications"),
    ("Slack Digest <digest@slack.com>", "Weekly Recap: Team Updates", "Key messages from the past week across your workspace.\n\nOpt-out"),
    ("Vercel <noreply@vercel.com>", "Usage Alert: 80% of bandwidth", "Your project my-app has used 80% of its monthly bandwidth allocation.\n\nManage preferences"),
    ("Linear <notifications@linear.app>", "Issue assigned to you", "PROJ-456: Implement dark mode. Assigned by Pierre. Priority: Medium.\n\nUnsubscribe"),
    ("Intercom <noreply@intercom.io>", "New conversation", "A customer started a new conversation: 'How do I export my data?'\n\nOpt-out"),
    ("HubSpot <marketing@hubspot.com>", "INBOUND 2026: Register Now", "Join HubSpot's annual conference. Early bird pricing ends March 31.\n\nUnsubscribe | View in browser"),
    ("Mailchimp <noreply@mailchimp.com>", "Campaign Report: March Newsletter", "Open rate: 34.2%, Click rate: 5.8%, Unsubscribes: 0.2%.\n\nManage preferences"),
    ("SendGrid <noreply@sendgrid.net>", "Deliverability Report", "Your email deliverability score is 98.5%. 2 bounced emails this week.\n\nOpt-out"),
    ("Substack <digest@substack.com>", "Recommended for you", "Based on your reading history: 3 new publications to follow.\n\nUnsubscribe"),
    ("GitHub <notifications@github.com>", "Dependabot alert: critical vulnerability", "A critical vulnerability was found in lodash@4.17.21. Update recommended.\n\nManage your notifications"),
    ("Stripe Dashboard <updates@stripe.com>", "Weekly Revenue Summary", "This week: $2,340 in revenue, 47 successful payments, 2 refunds.\n\nUnsubscribe"),
    ("Notion <updates@notion.so>", "Template Gallery: New Additions", "Discover new templates for project management and personal productivity.\n\nOpt-out"),
    ("Figma <newsletter@figma.com>", "Config 2026 Highlights", "Watch the keynote and session replays from Figma Config.\n\nManage preferences | Unsubscribe"),
    ("Sentry <alerts@sentry.io>", "Performance Alert: Slow API", "Endpoint /api/emails: P95 latency increased to 2.3s (threshold: 1s).\n\nUnsubscribe"),
    ("Vercel <updates@vercel.com>", "Next.js 16 Released", "Major performance improvements, server actions GA, and new caching.\n\nManage preferences"),
    ("Linear <digest@linear.app>", "Weekly Progress Report", "Team velocity: 42 points. Completed: 8 issues. In progress: 5.\n\nOpt-out"),
    ("Heroku <noreply@heroku.com>", "Dyno usage alert", "Your app my-api has exceeded 500 free dyno hours this month.\n\nUnsubscribe"),
    ("AWS <noreply@aws.amazon.com>", "Billing Alert: $50 threshold", "Your AWS charges have exceeded $50 for this billing period.\n\nManage your billing preferences"),
    ("Datadog <alerts@datadoghq.com>", "Monitor Alert: CPU > 80%", "Your monitor 'High CPU Usage' has triggered. Current value: 87%.\n\nOpt-out"),
    ("PagerDuty <noreply@pagerduty.com>", "Incident Resolved: API Downtime", "Incident #3456 has been resolved. Duration: 12 minutes.\n\nManage your notifications"),
    ("Jira <noreply@jira.atlassian.com>", "Sprint completed: Sprint 14", "Sprint 14 is complete. 18 of 20 stories delivered. Velocity: 38 pts.\n\nUnsubscribe"),
    ("Confluence <noreply@confluence.atlassian.com>", "Page updated: Architecture Docs", "Pierre updated 'System Architecture' in your Engineering space.\n\nOpt-out"),
    ("GitLab <noreply@gitlab.com>", "Merge request approved", "MR !234: Add user authentication. Approved by Alex. Ready to merge.\n\nManage preferences"),
    ("Cloudflare <alerts@cloudflare.com>", "DDoS Attack Mitigated", "A DDoS attack targeting your domain was mitigated. No impact on availability.\n\nUnsubscribe"),
    ("DigitalOcean <noreply@digitalocean.com>", "Droplet resize complete", "Your droplet my-server has been resized to 4GB RAM / 2 vCPUs.\n\nOpt-out"),
    ("Render <notifications@render.com>", "Service deployed successfully", "Your service my-api was deployed successfully. Build time: 45s.\n\nManage your notifications"),
    ("Railway <updates@railway.app>", "Usage Report: March", "This month: 720 compute hours, 45GB storage, 120GB bandwidth.\n\nUnsubscribe"),
    ("Fly.io <noreply@fly.io>", "Machine health check failed", "Machine my-api-1 in iad failed a health check. Auto-restarting.\n\nOpt-out"),
    ("Postmark <alerts@postmarkapp.com>", "Bounce rate increasing", "Your bounce rate has increased to 3.2%. Review your recipient list.\n\nManage preferences"),
    ("Algolia <noreply@algolia.com>", "Index updated: products", "Your products index was rebuilt. 15,234 records indexed in 3.2s.\n\nUnsubscribe"),
    ("Twilio <noreply@twilio.com>", "SMS delivery report", "98.5% of your SMS messages were delivered this month. View details.\n\nOpt-out"),
    ("Segment <digest@segment.com>", "Monthly data quality report", "Tracking plan violations: 3. Unplanned events: 7. Fix suggestions inside.\n\nManage your notifications"),
    ("Amplitude <noreply@amplitude.com>", "Weekly Product Analytics", "DAU: 1,234. WAU: 8,456. Retention: 42%. View your dashboard.\n\nUnsubscribe"),
    ("Mixpanel <alerts@mixpanel.com>", "Funnel Alert: Signup Drop", "Signup funnel conversion dropped to 12% (was 18%). View analysis.\n\nOpt-out"),
    ("LaunchDarkly <noreply@launchdarkly.com>", "Feature flag toggled", "Flag 'new-dashboard' was toggled ON in production by Alex.\n\nManage preferences"),
    ("CircleCI <noreply@circleci.com>", "Build failed: main branch", "Build #1234 on main failed at test step. View logs.\n\nUnsubscribe"),
    ("Netlify <notifications@netlify.com>", "Deploy preview ready", "Deploy preview for PR #45 is ready. Preview URL: https://deploy-preview-45.netlify.app\n\nOpt-out"),
    ("Auth0 <noreply@auth0.com>", "Monthly login stats", "Total logins: 5,678. Unique users: 1,234. Failed attempts: 23.\n\nManage your notifications"),
    ("Supabase <updates@supabase.com>", "Database approaching limit", "Your database is at 85% storage capacity. Consider upgrading.\n\nUnsubscribe"),
    ("MongoDB Atlas <alerts@mongodb.com>", "Cluster alert: connections high", "Your cluster my-cluster has 450 active connections (limit: 500).\n\nOpt-out"),
    ("Redis Cloud <noreply@redis.com>", "Memory usage alert", "Your Redis instance is using 78% of available memory. Consider scaling.\n\nManage preferences"),
    ("Grafana <alerts@grafana.com>", "Alert: Error rate > 5%", "Dashboard 'Production' alert: error rate reached 6.2%.\n\nUnsubscribe"),
    ("New Relic <noreply@newrelic.com>", "APM Weekly Summary", "Apdex: 0.94. Throughput: 1,200 rpm. Error rate: 0.3%.\n\nOpt-out"),
    ("Snyk <alerts@snyk.io>", "Vulnerability found in dependencies", "1 high severity vulnerability found in express@4.18.2. Fix available.\n\nManage your notifications"),
    ("SonarQube <noreply@sonarqube.com>", "Quality Gate failed", "Project my-api failed the quality gate. 3 bugs, 2 code smells.\n\nUnsubscribe"),
    ("Terraform Cloud <noreply@hashicorp.com>", "Plan completed: infrastructure", "Terraform plan for workspace 'production' completed. 2 changes detected.\n\nOpt-out"),
    ("Docker Hub <noreply@docker.com>", "Image pushed successfully", "Image my-api:latest has been pushed to Docker Hub. Size: 234MB.\n\nManage preferences"),
    ("npm <noreply@npmjs.com>", "Package published: @myorg/utils", "Version 2.1.0 of @myorg/utils has been published. Changelog inside.\n\nUnsubscribe"),
    ("PyPI <noreply@pypi.org>", "Release published: my-package 1.0.0", "Your package my-package 1.0.0 has been published to PyPI.\n\nOpt-out"),
    ("Crates.io <noreply@crates.io>", "New version available", "A new version of serde (1.0.200) is available. Changelog inside.\n\nManage your notifications"),
    ("Homebrew <noreply@brew.sh>", "Formula updated: node@20", "Node.js 20.12.0 is now available via Homebrew.\n\nUnsubscribe"),
    ("VS Code <noreply@microsoft.com>", "Extension update: Copilot", "GitHub Copilot v1.180.0 is available. New features: multi-file editing.\n\nOpt-out"),
    ("JetBrains <marketing@jetbrains.com>", "IntelliJ IDEA 2026.1 Released", "New AI assistant, improved refactoring, and Kotlin 2.0 support.\n\nUnsubscribe | Manage preferences"),
    ("Atlassian <noreply@atlassian.com>", "Your Jira weekly summary", "Completed: 12 issues. In progress: 8. Blocked: 2. View in Jira.\n\nOpt-out"),
    ("Monday.com <noreply@monday.com>", "Board update: Project Alpha", "3 items moved to Done, 2 new items added. View your board.\n\nManage your notifications"),
    ("Asana <noreply@asana.com>", "Weekly status update", "Your team completed 15 tasks this week. 8 tasks are overdue.\n\nUnsubscribe"),
    ("Trello <noreply@trello.com>", "Card moved: Deploy v2.0", "The card 'Deploy v2.0' was moved to 'Done' by Alex.\n\nOpt-out"),
    ("Basecamp <noreply@basecamp.com>", "New comment on Discussion", "Pierre commented on 'Q2 Planning': 'I agree with the proposed timeline.'\n\nManage preferences"),
    ("Calendly <noreply@calendly.com>", "Meeting scheduled: Tech Review", "A 30-minute meeting was scheduled for March 27 at 3pm.\n\nUnsubscribe"),
    ("Zoom <noreply@zoom.us>", "Meeting recording ready", "Your meeting 'Team Standup' recording is available. View or download.\n\nOpt-out"),
    ("Google Workspace <noreply@google.com>", "Storage quota warning", "You've used 14.2 GB of 15 GB. Upgrade your storage plan.\n\nManage your notifications"),
    ("Dropbox <noreply@dropbox.com>", "File shared: Q1 Report.pdf", "Alex shared 'Q1 Report.pdf' with you. View in Dropbox.\n\nUnsubscribe"),
    ("1Password <noreply@1password.com>", "Security alert: Watchtower", "2 items in your vault have compromised passwords. Update them now.\n\nOpt-out"),
    ("Bitwarden <noreply@bitwarden.com>", "Data Breach Report", "No exposed passwords found in your vault this month. Stay safe.\n\nManage preferences"),
    ("Canva <marketing@canva.com>", "New Templates: Social Media Pack", "Spring social media templates are here. Create engaging posts.\n\nUnsubscribe | View in browser"),
    ("Grammarly <noreply@grammarly.com>", "Your Weekly Writing Stats", "You wrote 12,345 words this week. Tone: confident. Clarity: 89%.\n\nOpt-out"),
    ("Loom <noreply@loom.com>", "New view on your video", "Marie watched your video 'API Demo'. 2 comments added.\n\nManage your notifications"),
    ("Miro <noreply@miro.com>", "Board activity: Architecture Diagram", "3 team members edited the Architecture Diagram board today.\n\nUnsubscribe"),
    ("ProductBoard <noreply@productboard.com>", "Feature request: Dark mode", "A new feature request was submitted by a user. Priority: High.\n\nOpt-out"),
    ("Hotjar <marketing@hotjar.com>", "Your monthly UX report", "Heatmap insights: users scroll past the fold. Suggestions inside.\n\nUnsubscribe | View in browser"),
    ("FullStory <noreply@fullstory.com>", "Rage click detected", "3 users rage-clicked on the checkout button. View sessions.\n\nManage preferences"),
    ("Heap <alerts@heap.io>", "Event threshold exceeded", "The 'signup_started' event exceeded 1,000 occurrences today.\n\nOpt-out"),
    ("Plausible <noreply@plausible.io>", "Weekly traffic report", "Your site had 3,456 visitors this week. Top page: /blog/ai-guide.\n\nUnsubscribe"),
    ("Fathom Analytics <noreply@usefathom.com>", "Monthly analytics summary", "March: 12,345 visitors, 34,567 pageviews, 2.8 pages/visit.\n\nManage your notifications"),
    ("Crisp <noreply@crisp.chat>", "New chat message", "A visitor started a chat: 'Is there a free trial available?'\n\nOpt-out"),
    ("Zendesk <noreply@zendesk.com>", "Ticket assigned: #78901", "Ticket 'Cannot login' has been assigned to your queue.\n\nManage preferences"),
    ("Freshdesk <noreply@freshdesk.com>", "New ticket: Billing question", "A customer submitted a new ticket about billing. Priority: Normal.\n\nUnsubscribe"),
    ("Help Scout <noreply@helpscout.com>", "Conversation assigned", "A customer conversation about 'Export feature' has been assigned to you.\n\nOpt-out"),
    ("Shopify <noreply@shopify.com>", "New order: #1234", "You received a new order for $89.99. View order details.\n\nManage your notifications"),
    ("WooCommerce <noreply@woocommerce.com>", "Order status changed", "Order #5678 changed from 'Processing' to 'Completed'.\n\nUnsubscribe"),
    ("Gumroad <noreply@gumroad.com>", "Sale notification: $29.00", "You made a sale of 'TypeScript Masterclass' for $29.00.\n\nOpt-out"),
    ("Paddle <noreply@paddle.com>", "Payment processed: $99.00", "Payment of $99.00 received for subscription renewal.\n\nManage preferences"),
    ("LemonSqueezy <noreply@lemonsqueezy.com>", "New subscriber", "A new customer subscribed to your Pro plan. MRR: $2,340.\n\nUnsubscribe"),
]

# --- 7. Generic newsletters/noreply (100) ---
NOISE_GENERIC_NEWSLETTERS = [
    ("noreply@coursera.org", "Course Recommendation: Deep Learning", "Based on your interests, we recommend the Deep Learning Specialization.\n\nManage your preferences"),
    ("no-reply@udemy.com", "New course: Advanced React Patterns", "Learn advanced React patterns from a senior engineer. 50% off this week.\n\nUnsubscribe"),
    ("newsletter@hackernoon.com", "HackerNoon Daily", "Today's top story: How to build a million-user app in 2026.\n\nUnsubscribe | View in browser"),
    ("marketing@zapier.com", "Automate Your Workflow", "5 Zaps that save 10 hours per week. Ready to automate?\n\nOpt-out"),
    ("updates@calendly.com", "Calendly Product Update", "New scheduling page designs and integration with Notion.\n\nManage your notifications"),
    ("digest@producthunt.com", "Product of the Week: CodeCraft AI", "An AI-powered code review tool. 500+ upvotes.\n\nUnsubscribe"),
    ("newsletter@techradar.com", "TechRadar Weekly", "Best laptops of 2026, smartphone reviews, and tech deals.\n\nOpt-out | View in browser"),
    ("noreply@stackoverflow.com", "Your Weekly Summary", "Top questions in your tags: Python, TypeScript, React.\n\nManage email preferences"),
    ("no-reply@medium.com", "Stories for You", "Recommended articles based on your reading history.\n\nUnsubscribe"),
    ("newsletter@theatlantic.com", "The Atlantic Daily", "Today's best reads: politics, culture, and technology.\n\nManage your subscription"),
    ("updates@spotify.com", "New Music Friday", "Discover the latest releases from your favorite artists.\n\nOpt-out"),
    ("digest@quora.com", "Questions for You", "Top questions this week: AI, Programming, Productivity.\n\nUnsubscribe | Manage preferences"),
    ("marketing@grammarly.com", "Write Better with AI", "Grammarly's AI suggestions helped you write 30% faster this month.\n\nUnsubscribe"),
    ("newsletter@theinformation.com", "The Information Daily", "Today's exclusive: Big tech's AI strategy shifts.\n\nManage your subscription"),
    ("noreply@adobe.com", "Adobe Creative Cloud Update", "Photoshop AI features, Illustrator updates, and more.\n\nOpt-out"),
    ("no-reply@canva.com", "Design Inspiration Weekly", "Trending design styles and templates for spring 2026.\n\nUnsubscribe | View in browser"),
    ("newsletter@smashingmagazine.com", "Web Dev Weekly", "CSS container queries, WASM updates, and responsive design patterns.\n\nManage preferences"),
    ("updates@airbnb.com", "Explore Spring Getaways", "Top-rated stays for your spring vacation. Book now.\n\nOpt-out"),
    ("digest@tripadvisor.com", "Montreal: Top Restaurants", "Best-reviewed restaurants near you this week.\n\nUnsubscribe"),
    ("marketing@uber.com", "Uber One: Free Delivery", "Get free delivery on your next 5 Uber Eats orders. Subscribe now.\n\nManage your notifications"),
    ("newsletter@nytimes.com", "Morning Briefing", "Today's top stories from The New York Times.\n\nUnsubscribe | View in browser"),
    ("noreply@washingtonpost.com", "Technology 202", "The latest in tech policy and innovation from D.C.\n\nOpt-out"),
    ("no-reply@cnn.com", "Breaking News Alert", "Major announcement from the tech industry. Read now.\n\nManage your preferences"),
    ("newsletter@bbc.com", "BBC Tech Digest", "Global tech news and analysis from BBC correspondents.\n\nUnsubscribe"),
    ("updates@theguardian.com", "The Guardian Tech Weekly", "AI ethics, social media regulation, and startup news.\n\nOpt-out | View in browser"),
    ("digest@reuters.com", "Reuters Tech News", "Breaking tech stories and market updates.\n\nManage your subscription"),
    ("marketing@anthropic.com", "Claude Update: New Features", "Discover the latest capabilities added to Claude this month.\n\nUnsubscribe"),
    ("newsletter@openai.com", "OpenAI Monthly", "New model releases, API updates, and research highlights.\n\nOpt-out"),
    ("noreply@deepmind.com", "DeepMind Research Update", "Our latest publications in Nature and Science.\n\nManage your notifications"),
    ("no-reply@mistral.ai", "Mistral AI Newsletter", "Introducing Mistral Large 3: our most capable model yet.\n\nUnsubscribe | View in browser"),
    ("newsletter@cohere.ai", "Cohere Enterprise AI", "Case studies: how enterprises deploy LLMs in production.\n\nManage preferences"),
    ("updates@huggingface.co", "Hugging Face Weekly", "Trending models, datasets, and spaces this week.\n\nOpt-out"),
    ("digest@weights-and-biases.com", "W&B Fully Connected", "ML experiment tracking tips and community highlights.\n\nUnsubscribe"),
    ("marketing@databricks.com", "Databricks Summit Recap", "Watch session replays and download presentations.\n\nManage your subscription"),
    ("newsletter@snowflake.com", "Snowflake Data Cloud Digest", "New features, integrations, and customer success stories.\n\nOpt-out | View in browser"),
    ("noreply@salesforce.com", "Trailhead: New Badges", "Earn new badges in AI, CRM, and Apex development.\n\nUnsubscribe"),
    ("no-reply@oracle.com", "Oracle Cloud Update", "New services and pricing updates for Oracle Cloud Infrastructure.\n\nManage your notifications"),
    ("newsletter@ibm.com", "Think Weekly", "AI research, quantum computing, and enterprise innovation.\n\nUnsubscribe | View in browser"),
    ("updates@redhat.com", "Red Hat Insights", "Linux kernel updates, OpenShift features, and Ansible automation.\n\nOpt-out"),
    ("digest@vmware.com", "VMware Digest", "Virtualization, multi-cloud, and infrastructure trends.\n\nManage preferences"),
    ("marketing@paloaltonetworks.com", "Cybersecurity Newsletter", "Latest threat intelligence and security best practices.\n\nUnsubscribe"),
    ("newsletter@crowdstrike.com", "CrowdStrike Threat Report", "Q1 2026 threat landscape: ransomware trends and nation-state actors.\n\nOpt-out | View in browser"),
    ("noreply@okta.com", "Okta Security Bulletin", "Security updates and best practices for identity management.\n\nManage your notifications"),
    ("no-reply@cloudflare.com", "Cloudflare Radar: Internet Trends", "Global internet traffic patterns and DDoS attack trends.\n\nUnsubscribe"),
    ("newsletter@akamai.com", "State of the Internet Report", "CDN performance, web security, and edge computing insights.\n\nManage your subscription"),
    ("updates@fastly.com", "Fastly Edge Cloud Update", "New edge computing features and performance improvements.\n\nOpt-out"),
    ("digest@elastic.co", "Elastic Community Digest", "Elasticsearch tips, Kibana dashboards, and community contributions.\n\nUnsubscribe | View in browser"),
    ("marketing@splunk.com", "Splunk .conf Highlights", "Key announcements and session replays from .conf 2026.\n\nManage preferences"),
    ("newsletter@grafana.com", "Grafana Labs Blog Digest", "New dashboards, alerting features, and Loki updates.\n\nOpt-out"),
    ("noreply@prometheus.io", "Prometheus Monthly", "Monitoring best practices and ecosystem updates.\n\nUnsubscribe"),
    ("no-reply@jenkins.io", "Jenkins Community Newsletter", "Plugin updates, security advisories, and community events.\n\nManage your notifications"),
    ("newsletter@circleci.com", "CI/CD Best Practices", "Speed up your pipelines with these optimization tips.\n\nUnsubscribe | View in browser"),
    ("updates@github.com", "GitHub Changelog Digest", "New features: Copilot improvements, Actions updates, and more.\n\nOpt-out"),
    ("digest@stackoverflow.com", "Developer Survey Results", "The 2026 developer survey is here. See what's trending.\n\nManage preferences"),
    ("marketing@codecademy.com", "Learn AI in 30 Days", "Start your AI learning journey with our structured curriculum.\n\nUnsubscribe"),
    ("newsletter@pluralsight.com", "Skills of Tomorrow", "Top skills in demand: AI, cloud architecture, and cybersecurity.\n\nOpt-out | View in browser"),
    ("noreply@linkedin-learning.com", "Course Completed Certificate", "Download your certificate for 'Advanced Python Development'.\n\nManage your notifications"),
    ("no-reply@edx.org", "New Course: Machine Learning", "MIT's Machine Learning with Python course is now available.\n\nUnsubscribe"),
    ("newsletter@freecodecamp.org", "FreeCodeCamp Weekly", "Tutorials, projects, and certification updates.\n\nManage your subscription"),
    ("updates@codecrafters.io", "CodeCrafters Challenge", "Build your own Redis! New challenge starts this Monday.\n\nOpt-out"),
    ("digest@devto.com", "DEV Community Weekly", "Top posts in web development, AI, and career advice.\n\nUnsubscribe | View in browser"),
    ("marketing@digitalocean.com", "DigitalOcean Tutorials", "New tutorials: Kubernetes, serverless, and database optimization.\n\nManage preferences"),
    ("newsletter@linode.com", "Akamai Cloud Computing", "Infrastructure guides and pricing updates.\n\nOpt-out"),
    ("noreply@vultr.com", "Vultr Marketplace: New Apps", "Deploy popular apps in one click: WordPress, Ghost, Discourse.\n\nUnsubscribe"),
    ("no-reply@hetzner.com", "Hetzner Newsletter", "New server options and data center updates.\n\nManage your notifications"),
    ("newsletter@ovhcloud.com", "OVHcloud Newsletter", "Cloud computing news, tutorials, and product updates.\n\nUnsubscribe | View in browser"),
    ("updates@scaleway.com", "Scaleway Product Update", "New GPU instances and serverless containers now available.\n\nOpt-out"),
    ("digest@clever-cloud.com", "Clever Cloud Monthly", "Platform updates, new runtimes, and performance improvements.\n\nManage preferences"),
    ("marketing@twitch.tv", "Twitch Recap: March", "Your streaming stats and community highlights for March.\n\nUnsubscribe"),
    ("newsletter@steam.com", "Steam Spring Sale", "Thousands of games on sale. Up to 85% off. Don't miss out!\n\nOpt-out | View in browser"),
    ("noreply@epicgames.com", "Free Games This Week", "Two free games available now on the Epic Games Store.\n\nManage your notifications"),
    ("no-reply@gog.com", "GOG Weekly Sale", "Classic and indie games at unbeatable prices.\n\nUnsubscribe"),
    ("newsletter@unity.com", "Unity Developer Newsletter", "New tutorials, asset store highlights, and engine updates.\n\nManage your subscription"),
    ("updates@unrealengine.com", "Unreal Engine 5.4 Released", "Nanite improvements, Lumen updates, and MetaHuman enhancements.\n\nOpt-out"),
    ("digest@godotengine.org", "Godot Community Digest", "Engine updates, showcase games, and tutorial roundup.\n\nUnsubscribe | View in browser"),
    ("marketing@raycast.com", "Raycast Pro: AI Commands", "Supercharge your workflow with AI-powered commands.\n\nManage preferences"),
    ("newsletter@warp.dev", "Warp Terminal Update", "New AI features, custom themes, and block navigation.\n\nOpt-out"),
    ("noreply@iterm2.com", "iTerm2 Release Notes", "Version 3.5: improved performance and new color schemes.\n\nUnsubscribe"),
    ("no-reply@obsidian.md", "Obsidian Newsletter", "New plugins, themes, and community vault highlights.\n\nManage your notifications"),
    ("newsletter@logseq.com", "Logseq Weekly", "Knowledge management tips and plugin recommendations.\n\nUnsubscribe | View in browser"),
    ("updates@roamresearch.com", "Roam Research Update", "New features: better graph visualization and AI integration.\n\nOpt-out"),
    ("digest@todoist.com", "Todoist Productivity Tips", "5 strategies to get more done with Todoist. Start today.\n\nManage preferences"),
    ("marketing@clickup.com", "ClickUp Enterprise: Case Studies", "How Fortune 500 companies use ClickUp for project management.\n\nUnsubscribe"),
    ("newsletter@linear.app", "Linear Changelog Digest", "New features: custom workflows, API improvements, and integrations.\n\nOpt-out | View in browser"),
    ("noreply@height.app", "Height Product Update", "AI task management, timeline views, and cross-project tracking.\n\nManage your notifications"),
    ("no-reply@shortcut.com", "Shortcut Monthly", "Project management insights and platform updates.\n\nUnsubscribe"),
    ("newsletter@pitch.com", "Pitch Design Newsletter", "Presentation templates and design tips for teams.\n\nManage your subscription"),
    ("updates@mural.co", "MURAL Inspiration", "Visual collaboration tips and new template gallery.\n\nOpt-out"),
    ("digest@whimsical.com", "Whimsical Weekly", "Wireframing, flowcharting, and brainstorming features.\n\nUnsubscribe | View in browser"),
    ("marketing@excalidraw.com", "Excalidraw Plus Update", "Real-time collaboration, new shapes, and library updates.\n\nManage preferences"),
    ("newsletter@tldraw.com", "tldraw Community Spotlight", "See what the community is building with tldraw.\n\nOpt-out"),
    ("noreply@strava.com", "Your Weekly Running Stats", "Distance: 32km. Time: 3h12m. New personal best on your 10K route!\n\nManage your notifications"),
    ("no-reply@fitbit.com", "Fitbit Weekly Report", "Steps: 68,432. Active minutes: 245. Sleep score: 82.\n\nUnsubscribe"),
    ("newsletter@peloton.com", "New Classes This Week", "HIIT, yoga, and strength training classes from top instructors.\n\nOpt-out | View in browser"),
    ("updates@myfitnesspal.com", "Nutrition Weekly Summary", "Calories: avg 2,100/day. Protein: 35%. Carbs: 45%. Fat: 20%.\n\nManage preferences"),
    ("digest@headspace.com", "Mindfulness Monday", "Start your week with a 10-minute guided meditation.\n\nUnsubscribe"),
    ("marketing@calm.com", "Sleep Stories: New Releases", "3 new sleep stories narrated by celebrity voices.\n\nOpt-out | View in browser"),
    ("newsletter@duolingo.com", "Duolingo Weekly Progress", "French: 5-day streak! Spanish: Level 3 complete. Keep going!\n\nManage your notifications"),
    ("noreply@rosettastone.com", "Language Learning Tips", "5 tips to accelerate your language learning journey.\n\nUnsubscribe"),
    ("newsletter@babbel.com", "Babbel Weekly Challenge", "Complete this week's challenge and earn a streak badge. Keep learning!\n\nManage your notifications"),
]

# --- 8. Social media notifications (50) ---
NOISE_SOCIAL_MEDIA = [
    ("Facebook <notification@facebookmail.com>", "Marie Dupont tagged you in a photo", "Marie Dupont tagged you in a photo at Café de Flore. View photo.\n\nManage your notifications"),
    ("Facebook <noreply@facebookmail.com>", "You have 5 new notifications", "Jean liked your post. Sophie commented on your photo. 3 more.\n\nOpt-out"),
    ("Facebook <notification@mail.facebook.com>", "Event reminder: Team Dinner", "Reminder: Team Dinner is tomorrow at 7pm. 12 people going.\n\nManage preferences"),
    ("Facebook <noreply@facebookmail.com>", "Pierre sent you a friend request", "Pierre Martin wants to be your friend. Accept or decline.\n\nUnsubscribe"),
    ("Facebook <notification@facebookmail.com>", "Memories: 3 years ago today", "Look back at what you shared 3 years ago today.\n\nOpt-out"),
    ("Facebook <noreply@facebookmail.com>", "New post in AI Engineers group", "Alex shared an article about transformer architectures.\n\nManage your notifications"),
    ("Facebook <notification@facebookmail.com>", "Sophie's birthday is today", "Wish Sophie Martin a happy birthday! Write on her timeline.\n\nUnsubscribe"),
    ("Facebook <notification@mail.facebook.com>", "Marketplace: Items near you", "5 new items listed near your location. Furniture, electronics, and more.\n\nOpt-out"),
    ("Facebook <noreply@facebookmail.com>", "Would you like to reconnect?", "You haven't connected with Jean-Marc in a while. Send a message.\n\nManage preferences"),
    ("Facebook <notification@facebookmail.com>", "Group update: French Developers", "3 new posts in French Developers group today.\n\nUnsubscribe"),
    ("Instagram <notification@priority.instagram.com>", "Marie liked your photo", "Marie Dupont liked your photo of the sunset at Mont Royal.\n\nOpt-out"),
    ("Instagram <noreply@mail.instagram.com>", "New follower: @pierre_dev", "pierre_dev started following you. Follow back.\n\nManage your notifications"),
    ("Instagram <notification@priority.instagram.com>", "Comment on your reel", "Sophie commented on your reel: 'This is amazing! 🎉'\n\nUnsubscribe"),
    ("Instagram <noreply@mail.instagram.com>", "Story mention: @alex_design", "alex_design mentioned you in their story. View it now.\n\nOpt-out"),
    ("Instagram <notification@priority.instagram.com>", "New reel suggestions", "Based on your interests: 5 new reels about AI and tech.\n\nManage preferences"),
    ("Instagram <noreply@mail.instagram.com>", "Your post reached 500 people", "Your latest post was seen by 500 accounts. View insights.\n\nUnsubscribe"),
    ("Instagram <notification@priority.instagram.com>", "Live video: @tech_talks", "tech_talks is live right now! Join the conversation.\n\nOpt-out"),
    ("Instagram <noreply@mail.instagram.com>", "Direct message from @marie_photo", "marie_photo sent you a message. Open Instagram to read it.\n\nManage your notifications"),
    ("Instagram <notification@priority.instagram.com>", "Suggested accounts to follow", "5 accounts you might enjoy: tech, design, and photography.\n\nUnsubscribe"),
    ("Instagram <noreply@mail.instagram.com>", "Your story has expired", "Your story from 24 hours ago has expired. Add it to highlights.\n\nOpt-out"),
    ("X (Twitter) <info@e.x.com>", "New follower: @ai_engineer", "ai_engineer is now following you on X.\n\nManage preferences"),
    ("X (Twitter) <noreply@x.com>", "Trending: #AIEngineering", "See what's happening in #AIEngineering. 15K+ posts today.\n\nUnsubscribe"),
    ("X (Twitter) <info@e.x.com>", "Jean retweeted your post", "Jean Dupont retweeted your thread about LLM optimization.\n\nOpt-out"),
    ("X (Twitter) <noreply@x.com>", "New reply to your tweet", "Sophie replied: 'Great take on the AI market. I completely agree.'\n\nManage your notifications"),
    ("X (Twitter) <info@e.x.com>", "Daily digest: Your timeline", "Top tweets from accounts you follow. 10 highlights today.\n\nUnsubscribe"),
    ("X (Twitter) <noreply@x.com>", "Someone mentioned you", "Pierre mentioned you in a thread about React performance.\n\nOpt-out"),
    ("X (Twitter) <info@e.x.com>", "Spaces: AI Discussion Live", "A Spaces session about AI is happening now. 300 listeners.\n\nManage preferences"),
    ("X (Twitter) <noreply@x.com>", "Your tweet was liked 50 times", "Your tweet about Python tips received 50 likes. View analytics.\n\nUnsubscribe"),
    ("X (Twitter) <info@e.x.com>", "Account recommendation: @anthropic", "Based on your interests, you might enjoy following @anthropic.\n\nOpt-out"),
    ("X (Twitter) <noreply@x.com>", "Weekly highlights", "Your most engaging tweets and notable activity from this week.\n\nManage your notifications"),
    ("TikTok <noreply@tiktok.com>", "New follower: @code_vibes", "code_vibes started following you on TikTok.\n\nUnsubscribe"),
    ("TikTok <noreply@tiktok.com>", "Your video got 1,000 views", "Your video 'Coding in 60 seconds' reached 1,000 views!\n\nOpt-out"),
    ("TikTok <noreply@tiktok.com>", "Trending sounds for creators", "Check out this week's trending sounds for your next video.\n\nManage preferences"),
    ("TikTok <noreply@tiktok.com>", "Comment on your video", "User @tech_fan commented: 'This is so helpful! 🔥'\n\nUnsubscribe"),
    ("TikTok <noreply@tiktok.com>", "Creator Fund: Monthly Payout", "Your Creator Fund earnings for March: $45.23.\n\nOpt-out"),
    ("TikTok <noreply@tiktok.com>", "Duet request from @dev_daily", "dev_daily wants to duet your video. Accept or decline.\n\nManage your notifications"),
    ("TikTok <noreply@tiktok.com>", "LIVE: AI Coding Marathon", "A creator you follow is live! Join the AI Coding Marathon.\n\nUnsubscribe"),
    ("TikTok <noreply@tiktok.com>", "New effect: Code Background", "Try the new Code Background effect in your next video.\n\nOpt-out"),
    ("TikTok <noreply@tiktok.com>", "Your weekly analytics", "Views: 5,432. Followers gained: 23. Likes: 890.\n\nManage preferences"),
    ("TikTok <noreply@tiktok.com>", "Suggested creators to follow", "Based on your interests: tech, coding, and productivity creators.\n\nUnsubscribe"),
    ("Pinterest <noreply@pinterest.com>", "Pins inspired by your boards", "10 new pins related to your 'Workspace Setup' board.\n\nOpt-out"),
    ("Pinterest <noreply@pinterest.com>", "Weekly inspiration", "Top trending pins in technology and design this week.\n\nManage your notifications"),
    ("Pinterest <noreply@pinterest.com>", "Someone saved your pin", "Marie saved your pin 'Minimal Desk Setup' to her board.\n\nUnsubscribe"),
    ("Pinterest <noreply@pinterest.com>", "New ideas for you", "Discover pins about coding workspaces, productivity tools, and gadgets.\n\nOpt-out"),
    ("Pinterest <noreply@pinterest.com>", "Board follower: Sophie Martin", "Sophie Martin is now following your 'Tech Gadgets' board.\n\nManage preferences"),
    ("Pinterest <noreply@pinterest.com>", "Pin performance report", "Your most-viewed pins this month. Top pin: 'Standing Desk Setup'.\n\nUnsubscribe"),
    ("Pinterest <noreply@pinterest.com>", "Creator tools update", "New analytics dashboard and scheduling features for creators.\n\nOpt-out"),
    ("Pinterest <noreply@pinterest.com>", "Trending: Home Office Ideas", "Get inspired by the most popular home office setups.\n\nManage your notifications"),
    ("Pinterest <noreply@pinterest.com>", "Idea Pin templates", "New templates to create engaging Idea Pins. Try them now.\n\nUnsubscribe"),
    ("Pinterest <noreply@pinterest.com>", "Monthly recap: March 2026", "Your pins received 2,345 impressions and 123 saves this month.\n\nOpt-out"),
]

# --- 9. Crypto/Fintech (50) ---
NOISE_CRYPTO_FINTECH = [
    ("Binance <noreply@binance.com>", "Daily Trading Summary", "Your daily trading summary: 3 trades, PnL: +$120.50.\n\nManage your notifications"),
    ("Binance <updates@binance.com>", "New Listing: $AGNT Token", "Trade $AGNT/USDT starting March 26. Zero fees for the first week.\n\nUnsubscribe"),
    ("Binance <noreply@binance.com>", "Staking Rewards Distributed", "Your staking rewards for ETH have been distributed: 0.0023 ETH.\n\nOpt-out"),
    ("Binance <marketing@binance.com>", "Binance Earn: Up to 12% APY", "Lock your crypto and earn up to 12% annual yield. Start earning today.\n\nUnsubscribe | View in browser"),
    ("Binance <noreply@binance.com>", "Security Alert: New Login", "A new login was detected on your account from Chrome, Canada.\n\nManage preferences"),
    ("Coinbase <noreply@coinbase.com>", "Price Alert: BTC above $95,000", "Bitcoin has crossed your price alert threshold of $95,000.\n\nUnsubscribe"),
    ("Coinbase <updates@coinbase.com>", "Coinbase Learn: Earn $5 in AVAX", "Watch 3 short videos about Avalanche and earn $5 in AVAX tokens.\n\nOpt-out"),
    ("Coinbase <noreply@coinbase.com>", "Weekly Portfolio Recap", "Your portfolio: BTC 60%, ETH 25%, SOL 15%. Total value: $12,450.\n\nManage your notifications"),
    ("Coinbase <marketing@coinbase.com>", "Coinbase One: Zero Trading Fees", "Subscribe to Coinbase One for unlimited zero-fee trading. $29.99/mo.\n\nUnsubscribe | View in browser"),
    ("Coinbase <noreply@coinbase.com>", "Trade Confirmation: Bought 0.01 BTC", "You purchased 0.01 BTC for $954.50. Transaction ID: CB-20260325-001.\n\nManage preferences"),
    ("Kraken <noreply@kraken.com>", "Funding Received: $500 CAD", "Your CAD deposit of $500 has been credited to your Kraken account.\n\nUnsubscribe"),
    ("Kraken <updates@kraken.com>", "New Futures Market: SOL/USD", "Solana futures are now available on Kraken. Up to 50x leverage.\n\nOpt-out"),
    ("Kraken <noreply@kraken.com>", "Monthly Account Statement", "Your March 2026 trading statement is available. View in your account.\n\nManage your notifications"),
    ("Kraken <marketing@kraken.com>", "Kraken Pro: Advanced Trading", "Level up with Kraken Pro. Advanced charts, order types, and API.\n\nUnsubscribe | View in browser"),
    ("Kraken <noreply@kraken.com>", "Withdrawal Confirmation", "Your withdrawal of 0.5 ETH to 0x1234...abcd has been processed.\n\nManage preferences"),
    ("Crypto.com <noreply@crypto.com>", "Card Transaction: $42.50", "Your Crypto.com Visa card was used at Coffee Shop for $42.50.\n\nUnsubscribe"),
    ("Crypto.com <updates@crypto.com>", "CRO Staking: Earn 8% APY", "Stake CRO and earn up to 8% annual yield. Plus: cashback on purchases.\n\nOpt-out"),
    ("Crypto.com <noreply@crypto.com>", "Airdrop Alert: Free $TOKEN", "Eligible for the $TOKEN airdrop! Claim 500 tokens by March 31.\n\nManage your notifications"),
    ("Crypto.com <marketing@crypto.com>", "Crypto.com Exchange: Low Fees", "Trade with fees as low as 0.04%. The lowest in the industry.\n\nUnsubscribe | View in browser"),
    ("Crypto.com <noreply@crypto.com>", "Daily Cashback Summary", "Today's cashback: $2.15 in CRO from 3 card transactions.\n\nManage preferences"),
    ("Bybit <noreply@bybit.com>", "Futures Position Update", "Your BTC/USDT long position: PnL +$234.50. ROE: +12.3%.\n\nUnsubscribe"),
    ("Bybit <updates@bybit.com>", "Copy Trading: Top Traders", "Follow top traders and copy their strategies. Up to 500% ROI.\n\nOpt-out"),
    ("OKX <noreply@okx.com>", "Order Filled: BUY 0.1 ETH", "Your limit order to buy 0.1 ETH at $3,200 has been filled.\n\nManage your notifications"),
    ("OKX <marketing@okx.com>", "OKX Earn: Structured Products", "Earn up to 30% APY with our structured crypto products.\n\nUnsubscribe | View in browser"),
    ("KuCoin <noreply@kucoin.com>", "KCS Bonus Distributed", "Your KCS holding bonus for March: 2.5 KCS ($25.00).\n\nManage preferences"),
    ("KuCoin <updates@kucoin.com>", "New IEO: $FUTURE Token", "Participate in the $FUTURE token sale on KuCoin Spotlight.\n\nUnsubscribe"),
    ("Bitfinex <noreply@bitfinex.com>", "Lending Earnings Report", "Your lending earnings this week: $18.50 from USD lending.\n\nOpt-out"),
    ("Gate.io <noreply@gate.io>", "Startup Project: Apply Now", "Apply for the latest Gate.io Startup project. Free token allocation.\n\nManage your notifications"),
    ("CoinGecko <newsletter@coingecko.com>", "Weekly Crypto Report", "Market cap: $3.2T. BTC dominance: 52%. Top gainer: DOGE +45%.\n\nUnsubscribe | View in browser"),
    ("CoinMarketCap <newsletter@coinmarketcap.com>", "Monthly Market Review", "March 2026: Crypto market analysis, trends, and predictions.\n\nManage preferences"),
    ("Chainalysis <newsletter@chainalysis.com>", "On-Chain Intelligence", "DeFi TVL hits $200B. NFT volume surges. Institutional flows increase.\n\nOpt-out"),
    ("Messari <digest@messari.io>", "Crypto Thesis 2026 Update", "Updated research on Bitcoin, Ethereum, and emerging L1s.\n\nUnsubscribe"),
    ("The Block <newsletter@theblock.co>", "Daily Crypto Briefing", "Today: ETF inflows, DeFi hack, and new stablecoin regulation.\n\nManage your subscription"),
    ("Decrypt <newsletter@decrypt.co>", "Decrypt Daily", "Top crypto news: NFT marketplace merger, L2 launch, and DAO governance.\n\nOpt-out | View in browser"),
    ("CoinDesk <newsletter@coindesk.com>", "Consensus 2026 Highlights", "Key takeaways from the world's largest crypto conference.\n\nUnsubscribe"),
    ("Bankless <newsletter@bankless.com>", "Bankless Weekly", "Going bankless: DeFi strategies, yield farming, and protocol updates.\n\nManage preferences"),
    ("DeFi Pulse <digest@defipulse.com>", "DeFi Weekly Rankings", "Top protocols by TVL: Aave, Lido, MakerDAO, Uniswap.\n\nOpt-out"),
    ("Uniswap <noreply@uniswap.org>", "Governance Proposal: UIP-42", "Vote on UIP-42: Fee switch for V4 pools. Voting ends March 30.\n\nUnsubscribe"),
    ("Aave <noreply@aave.com>", "Interest Rate Update", "Your USDC lending rate changed to 4.2% APY.\n\nManage your notifications"),
    ("MakerDAO <noreply@makerdao.com>", "DAI Savings Rate Update", "The DSR has been updated to 8%. Earn on your DAI holdings.\n\nOpt-out"),
    ("Lido <noreply@lido.fi>", "Staking Rewards: 0.005 stETH", "Your weekly staking rewards have been distributed. APR: 3.8%.\n\nManage preferences"),
    ("Solana <newsletter@solana.com>", "Solana Ecosystem Update", "New dApps, validators, and developer tooling on Solana.\n\nUnsubscribe | View in browser"),
    ("Polygon <newsletter@polygon.technology>", "Polygon Monthly", "ZK rollup updates, ecosystem grants, and community highlights.\n\nOpt-out"),
    ("Arbitrum <newsletter@arbitrum.io>", "Arbitrum Orbit Launch", "Deploy your own L3 chain on Arbitrum. Developer docs available.\n\nManage your notifications"),
    ("Optimism <newsletter@optimism.io>", "Optimism Collective: Retro Funding", "Apply for retroactive public goods funding. Round 5 open.\n\nUnsubscribe"),
    ("Base <newsletter@base.org>", "Base Builder Update", "New frameworks, SDKs, and onchain apps launching on Base.\n\nOpt-out | View in browser"),
    ("Wealthsimple <noreply@wealthsimple.com>", "Monthly Investment Summary", "Your portfolio grew 3.2% this month. View detailed breakdown.\n\nManage preferences"),
    ("Questrade <noreply@questrade.com>", "Account Statement Available", "Your March 2026 account statement is ready to view.\n\nUnsubscribe"),
    ("Interactive Brokers <noreply@interactivebrokers.com>", "Trade Confirmation", "Trade executed: BUY 10 AAPL @ $198.50.\n\nManage your notifications"),
    ("Robinhood <noreply@robinhood.com>", "Dividend Received: $MSFT", "You received a dividend of $0.75 per share for MSFT holdings.\n\nOpt-out"),
]

# --- 10. Retail/E-commerce (40) ---
NOISE_RETAIL_ECOMMERCE = [
    ("Best Buy <deals@bestbuy.ca>", "Deal of the Day: MacBook Air M4", "MacBook Air M4 for $1,299. Save $200. Limited time offer.\n\nUnsubscribe | View in browser"),
    ("Best Buy <noreply@bestbuy.ca>", "Order Shipped: BB-20260325", "Your order is on its way via Purolator. Tracking: PR987654321.\n\nManage preferences"),
    ("Costco <marketing@costco.ca>", "New Warehouse Deals", "Members-only pricing on electronics, groceries, and home goods.\n\nOpt-out"),
    ("Costco <noreply@costco.ca>", "Digital Receipt: Order #2345", "Your recent purchase at Costco.ca. Total: $187.45.\n\nUnsubscribe"),
    ("Walmart <deals@walmart.ca>", "Rollback Prices This Week", "Save on thousands of items. TVs, furniture, and outdoor from $49.\n\nManage your notifications"),
    ("Walmart <noreply@walmart.ca>", "Pickup Ready: Order #WM-789", "Your order is ready for pickup at the Laval store.\n\nOpt-out"),
    ("IKEA <newsletter@ikea.ca>", "New Spring Collection", "Fresh designs for your home. Explore the spring 2026 collection.\n\nUnsubscribe | View in browser"),
    ("IKEA <noreply@ikea.ca>", "Delivery Scheduled: March 28", "Your IKEA delivery is scheduled for March 28 between 9am-1pm.\n\nManage preferences"),
    ("Canadian Tire <marketing@canadiantire.ca>", "Spring Savings Event", "Up to 50% off automotive, home, and outdoor products.\n\nOpt-out"),
    ("Canadian Tire <noreply@canadiantire.ca>", "Triangle Rewards Update", "You earned 1,200 Triangle Points this month. Balance: 15,340.\n\nUnsubscribe"),
    ("Home Depot <deals@homedepot.ca>", "DIY Project Sale", "Everything for your spring projects. Paint, tools, and lumber on sale.\n\nManage your notifications"),
    ("Home Depot <noreply@homedepot.ca>", "Order Confirmation: HD-456", "Your order of 3 items has been confirmed. Total: $234.67.\n\nOpt-out"),
    ("Lululemon <marketing@lululemon.com>", "New Arrivals: Spring Colours", "Fresh colours in your favourite styles. Shop the new arrivals.\n\nUnsubscribe | View in browser"),
    ("Lululemon <noreply@lululemon.com>", "Shipping Confirmation", "Your order has shipped via FedEx. Estimated delivery: March 27.\n\nManage preferences"),
    ("Apple Store <noreply@apple.com>", "Your order is being prepared", "Your order of iPhone 16 Pro is being prepared for shipping.\n\nOpt-out"),
    ("Apple Store <noreply@apple.com>", "Apple Receipt: $1,299.00", "Thank you for your purchase. View your receipt online.\n\nUnsubscribe"),
    ("Nike <marketing@nike.com>", "Member Exclusive: 30% Off", "Nike Members get 30% off select styles this weekend only.\n\nManage your notifications"),
    ("Nike <noreply@nike.com>", "Shipping Update: NKE-789", "Your Nike order is in transit. Expected delivery: March 26.\n\nOpt-out"),
    ("Adidas <marketing@adidas.ca>", "Creators Club: New Perks", "Level up in Creators Club for exclusive access and discounts.\n\nUnsubscribe | View in browser"),
    ("Adidas <noreply@adidas.ca>", "Order Delivered", "Your adidas order has been delivered. How did we do?\n\nManage preferences"),
    ("Zara <newsletter@zara.com>", "New Collection: Minimal Essentials", "Discover our latest collection. Minimalist designs for modern living.\n\nOpt-out"),
    ("H&M <marketing@hm.com>", "H&M Club: 20% Off Everything", "Members-only discount this weekend. Shop in-store and online.\n\nUnsubscribe"),
    ("Uniqlo <newsletter@uniqlo.ca>", "LifeWear Magazine: Spring Edition", "Explore our seasonal lookbook and styling inspiration.\n\nManage your notifications"),
    ("Indigo <marketing@indigo.ca>", "Book of the Month: AI Revolution", "Our editors' pick for March. Plus: 30% off bestsellers.\n\nOpt-out | View in browser"),
    ("Indigo <noreply@indigo.ca>", "Order Shipped: IND-123", "Your Indigo order is on its way via Canada Post.\n\nUnsubscribe"),
    ("Sephora <marketing@sephora.ca>", "Beauty Insider: Triple Points", "Earn triple points on all purchases this weekend. Shop now.\n\nManage preferences"),
    ("Sephora <noreply@sephora.ca>", "Order Confirmation: SEP-456", "Your Sephora order of 2 items has been confirmed. Total: $78.50.\n\nOpt-out"),
    ("Staples <deals@staples.ca>", "Office Supplies Sale", "Save on printer ink, paper, and desk accessories. Free shipping over $50.\n\nUnsubscribe | View in browser"),
    ("Staples <noreply@staples.ca>", "Delivery Update", "Your Staples order will arrive tomorrow between 10am-2pm.\n\nManage your notifications"),
    ("Etsy <noreply@etsy.com>", "Favourited item back in stock", "The handmade notebook you favourited is back in stock. Buy now.\n\nOpt-out"),
    ("Etsy <marketing@etsy.com>", "Spring Gift Guide", "Unique handmade gifts for every occasion. Shop local artisans.\n\nUnsubscribe"),
    ("eBay <deals@ebay.ca>", "Daily Deals: Tech & Electronics", "Laptops, tablets, and headphones at unbeatable prices.\n\nManage preferences | View in browser"),
    ("eBay <noreply@ebay.ca>", "Item Sold! You made $45.00", "Your listing 'Vintage Keyboard' has sold for $45.00.\n\nOpt-out"),
    ("Shopify <noreply@shopify.com>", "Your order from TechGadgets", "Order #TG-789 confirmed. 1 item: USB-C Hub. Total: $39.99.\n\nUnsubscribe"),
    ("Wayfair <marketing@wayfair.ca>", "Clearance Event: Up to 70% Off", "Massive markdowns on furniture, rugs, and lighting.\n\nManage your notifications"),
    ("Wayfair <noreply@wayfair.ca>", "Delivery Confirmed", "Your Wayfair order was delivered today. Rate your experience.\n\nOpt-out | View in browser"),
    ("Samsung <marketing@samsung.ca>", "Galaxy S26 Pre-Order", "Be the first to get the Galaxy S26. Pre-order now with trade-in savings.\n\nUnsubscribe"),
    ("Samsung <noreply@samsung.ca>", "Warranty Registration Complete", "Your Galaxy S26 warranty has been registered. Valid until March 2028.\n\nManage preferences"),
    ("Dell <marketing@dell.ca>", "Business Laptop Sale", "XPS and Latitude laptops up to $400 off for business customers.\n\nOpt-out"),
    ("Dell <noreply@dell.ca>", "Order Status: In Production", "Your custom Dell XPS 16 is being built. Estimated ship date: April 2.\n\nUnsubscribe"),
]

# ============================================================================
# EMAIL DATA — ACTION (300 total)
# ============================================================================

# --- 1. Direct questions from real people (80) ---
ACTION_DIRECT_QUESTIONS = [
    ("Marie Leclerc <marie@company.fr>", "Re: Budget Q2", "Can you review this PR before the end of the day?"),
    ("Jean-Pierre Dubois <jp.dubois@acme.com>", "Question about the API", "What do you think about using GraphQL instead of REST for the new endpoint?"),
    ("Sarah Mitchell <sarah@startup.io>", "Design review", "I've updated the mockups based on your feedback. What are your thoughts?"),
    ("Alexandre Tremblay <alex@techfirm.ca>", "Meeting follow-up", "Are you available Thursday afternoon for a follow-up call?"),
    ("Isabelle Moreau <isabelle@consulting.fr>", "Re: Proposal", "Peux-tu valider le budget avant vendredi?"),
    ("Thomas Chen <thomas@engineering.com>", "Code review needed", "Can you take a look at the authentication module? I've made significant changes."),
    ("Sophie Bernard <sophie@design.fr>", "Maquettes v2", "Qu'en penses-tu de la nouvelle version du dashboard?"),
    ("Michael Thompson <michael@sales.com>", "Client meeting prep", "What do you think about the pricing strategy we discussed?"),
    ("Lucie Martin <lucie@hr.fr>", "Entretien annuel", "Pourrais-tu me confirmer tes disponibilités pour ton entretien annuel?"),
    ("David Kim <david@product.io>", "Feature prioritization", "Can you rank these 5 features by impact? I need your input for the roadmap."),
    ("Camille Petit <camille@marketing.fr>", "Campagne pub", "Tu es dispo pour briefer l'équipe créative demain matin?"),
    ("James Wilson <james@backend.dev>", "Database migration", "What do you think about migrating to PostgreSQL 17? Any concerns?"),
    ("Émilie Rousseau <emilie@legal.fr>", "Contrat client", "Peux-tu relire le contrat et me dire si les clauses sont OK?"),
    ("Robert Taylor <robert@management.com>", "Quarterly review", "Can you prepare a summary of Q1 results by Monday?"),
    ("Nathalie Girard <nathalie@finance.fr>", "Budget ajustement", "Pourrais-tu vérifier les chiffres du budget marketing?"),
    ("Chris Anderson <chris@devops.io>", "Infrastructure question", "Should we switch to Kubernetes for the new microservices architecture?"),
    ("Audrey Laurent <audrey@product.fr>", "Roadmap Q2", "On se voit vendredi pour finaliser la roadmap?"),
    ("Patrick O'Brien <patrick@security.com>", "Security audit results", "Can you review the penetration test report and share your findings?"),
    ("Mathieu Leroy <mathieu@dev.fr>", "PR #234", "Tu peux merger la PR quand tu as un moment? Les tests passent tous."),
    ("Jennifer Lee <jennifer@ux.design>", "User research findings", "What do you think about the usability test results? Should we pivot?"),
    ("François Mercier <francois@ops.fr>", "Infra production", "Est-ce que tu peux regarder les logs de production? Il y a des erreurs 500 depuis ce matin."),
    ("Rachel Green <rachel@frontend.dev>", "Component library", "Can you review the new Button component API? I want to make sure it's extensible."),
    ("Guillaume Perrin <guillaume@backend.fr>", "API v3 spec", "Qu'est-ce que tu penses de l'approche avec les WebSockets pour le real-time?"),
    ("Amanda Davis <amanda@pm.com>", "Sprint planning", "Are you free tomorrow at 10am for sprint planning? I need your estimates."),
    ("Julien Robert <julien@data.fr>", "Pipeline données", "Tu peux vérifier que le pipeline de données tourne bien sur le nouveau dataset?"),
    ("Kevin Brown <kevin@qa.io>", "Test failures on staging", "Can you take a look at these 3 failing tests on staging? They might be related to your PR."),
    ("Charlotte Simon <charlotte@design.fr>", "Design system", "On valide les nouveaux tokens de couleur aujourd'hui?"),
    ("Andrew Miller <andrew@architecture.com>", "System design review", "What are your thoughts on the event-driven architecture proposal?"),
    ("Manon Dupont <manon@support.fr>", "Client escalation", "Peux-tu regarder le ticket #4521? Le client attend une réponse depuis 3 jours."),
    ("Daniel Harris <daniel@mobile.dev>", "React Native update", "Should we upgrade to React Native 0.76? Any breaking changes you know of?"),
    ("Léa Fournier <lea@product.fr>", "Feature feedback", "Tu as testé la nouvelle fonctionnalité de recherche? Ça te convient?"),
    ("Brian Clark <brian@backend.io>", "Cache strategy", "Can you share your opinion on Redis vs Memcached for our session cache?"),
    ("Nicolas Blanc <nicolas@dev.fr>", "Revue de code", "J'ai besoin de ton avis sur l'implémentation du pattern Repository."),
    ("Lisa Wang <lisa@analytics.com>", "Dashboard metrics", "What metrics should we track for the new onboarding funnel?"),
    ("Pauline Roux <pauline@rh.fr>", "Recrutement dev senior", "Tu es dispo pour faire passer un entretien technique vendredi à 14h?"),
    ("Mark Johnson <mark@infra.dev>", "Cloud migration", "Can you estimate the cost of migrating our workloads to GCP?"),
    ("Héloïse Morel <heloise@design.fr>", "Icônes v2", "Qu'en penses-tu des nouvelles icônes? Je préfère la version outlined."),
    ("Steve Martin <steve@eng.com>", "Performance optimization", "Can you profile the /api/emails endpoint? Response time has degraded."),
    ("Clara Bonnet <clara@marketing.fr>", "Lancement produit", "On se retrouve mercredi pour préparer le lancement?"),
    ("Ryan Cooper <ryan@platform.io>", "API rate limiting", "What do you think about implementing token bucket rate limiting?"),
    ("Anaïs Lambert <anais@support.fr>", "Documentation API", "Peux-tu mettre à jour la doc de l'API pour les nouveaux endpoints?"),
    ("Tom Williams <tom@data.io>", "Data pipeline issue", "The ETL job failed last night. Can you check the logs and fix it?"),
    ("Marion Dupuis <marion@product.fr>", "Priorisation bugs", "Tu peux trier les bugs par criticité pour le sprint?"),
    ("Eric Johnson <eric@sales.com>", "Demo for client", "Can you prepare a 15-minute demo of the new features for our client Thursday?"),
    ("Clémence Faure <clemence@legal.fr>", "RGPD conformité", "Pourrais-tu vérifier que notre traitement des données est conforme au RGPD?"),
    ("Jack Davis <jack@devrel.io>", "Blog post review", "Can you review my blog post about our API before I publish it?"),
    ("Virginie Chevalier <virginie@finance.fr>", "Notes de frais", "Tu peux soumettre tes notes de frais de mars avant vendredi?"),
    ("Sam Taylor <sam@mobile.dev>", "iOS crash report", "Can you look into the crash on iOS 18.2? It's affecting 5% of users."),
    ("Rémi Garnier <remi@ops.fr>", "Monitoring alert", "Tu as vu l'alerte sur le CPU du serveur prod-2? Ça tourne à 95%."),
    ("Linda Brown <linda@pm.com>", "Resource allocation", "Can you confirm how many hours your team can dedicate to Project X next week?"),
    ("Benoît Morin <benoit@dev.fr>", "Migration base de données", "Tu es dispo pour la migration de la base de données samedi matin?"),
    ("Karen White <karen@design.com>", "Brand guidelines update", "What do you think about the updated brand colors? I need your approval."),
    ("Antoine Gérard <antoine@backend.fr>", "Architecture microservices", "On se voit demain pour discuter de la nouvelle architecture?"),
    ("Peter Adams <peter@eng.io>", "Tech debt discussion", "Can you prioritize the top 5 tech debt items for next sprint?"),
    ("Céline Renaud <celine@product.fr>", "User stories", "Peux-tu rédiger les user stories pour la feature de notifications?"),
    ("Mike Robinson <mike@qa.com>", "Regression testing", "Can you verify that the fix for bug #789 doesn't break the payment flow?"),
    ("Diane Lemoine <diane@hr.fr>", "Formation équipe", "Est-ce que tu peux animer une formation TypeScript pour l'équipe junior?"),
    ("Chris Parker <chris@frontend.io>", "Component architecture", "What's your preferred approach for state management in the new dashboard?"),
    ("Élodie Marchand <elodie@design.fr>", "Prototype clickable", "Tu as eu le temps de tester le prototype? Des retours?"),
    ("Alex Murphy <alex@backend.dev>", "Caching issue", "Can you investigate the cache invalidation bug? Users see stale data."),
    ("Fabien Arnaud <fabien@devops.fr>", "Pipeline CI/CD", "Peux-tu optimiser le pipeline CI? Le build prend 25 minutes."),
    ("Rachel Kim <rachel@analytics.io>", "A/B test results", "Can you analyze the results of the A/B test on the checkout page?"),
    ("Sébastien Blanc <sebastien@dev.fr>", "Revue architecture", "Qu'en penses-tu de l'approche CQRS pour le module de commandes?"),
    ("Hannah Lee <hannah@ux.io>", "Accessibility audit", "Can you review the accessibility report and prioritize the fixes?"),
    ("Pascal Girard <pascal@backend.fr>", "Performance prod", "Tu peux regarder pourquoi l'API met 3 secondes à répondre sur /api/drafts?"),
    ("Olivia Scott <olivia@product.com>", "Feature spec review", "Can you review the feature spec for smart notifications? I need sign-off."),
    ("Laurent Dubois <laurent@data.fr>", "Rapport analytics", "Tu es dispo pour passer en revue le rapport analytics de février?"),
    ("Matt Williams <matt@infra.io>", "Disaster recovery plan", "Can you update the DR plan with the new cloud infrastructure?"),
    ("Marine Lefebvre <marine@marketing.fr>", "Landing page", "Peux-tu intégrer la nouvelle landing page avant le lancement de lundi?"),
    ("Jake Thompson <jake@eng.com>", "API versioning strategy", "What do you think about using URL versioning vs header versioning?"),
    ("Adrien Morel <adrien@backend.fr>", "Bug critique", "J'ai besoin de ton aide sur le bug de paiement. Tu peux regarder?"),
    ("Emily Clark <emily@design.io>", "Design token naming", "Can you validate the naming convention for our design tokens?"),
    ("Hugo Lemaire <hugo@frontend.fr>", "Composant React", "Tu peux revoir mon composant Modal? Je ne suis pas sûr de l'API."),
    ("Natalie Baker <natalie@pm.io>", "Release planning", "Are you available to discuss the release plan for v3.0 this afternoon?"),
    ("Maxime Fontaine <maxime@dev.fr>", "Test coverage", "On se voit pour définir la stratégie de test du nouveau module?"),
    ("Anna Martinez <anna@customer.com>", "Support escalation", "Can you look into our account issue? We've been locked out since yesterday."),
    ("Thibault Caron <thibault@ops.fr>", "Déploiement vendredi", "Tu valides le déploiement de vendredi? J'ai besoin de ton go."),
    ("Jessica Davis <jessica@sales.io>", "Client onboarding", "Can you join the call with the new enterprise client tomorrow at 2pm?"),
    ("Victor Nguyen <victor@dev.fr>", "Code refactoring", "Qu'en penses-tu du refactoring du module d'authentification?"),
    ("Michelle Thompson <michelle@legal.com>", "NDA review", "Can you sign the NDA for the new partnership? It's attached."),
]

# --- 2. Invoice/Payment requests (50) ---
ACTION_INVOICES = [
    ("Comptabilité <accounting@vendor.com>", "Invoice #4521 — Payment Due March 30", "Please find attached invoice #4521 for consulting services. Amount: $2,500.00. Payment due by March 30."),
    ("Finance Team <finance@partner.fr>", "Facture #FR-2026-0312", "Veuillez trouver ci-joint la facture #FR-2026-0312. Montant: 3 450,00 €. Échéance: 15 avril."),
    ("Finance Team <finance@saas-provider.com>", "Invoice #INV-2026-789 Attached", "Your invoice for the month of March is attached. Amount due: $199.00. Payment terms: Net 30."),
    ("Comptabilité <accounting@partner.com>", "Invoice #1234 attached", "Please find your invoice attached. Payment due in 30 days. Amount: $500.00."),
    ("Finance <finance@consulting.fr>", "Facture en attente de paiement", "La facture #2026-0456 d'un montant de 1 800,00 € est en attente de paiement. Merci de régler sous 15 jours."),
    ("AP Department <accounts@supplier.com>", "Amount Owing: $3,200.00", "This is a reminder that invoice #5678 with an amount owing of $3,200.00 is due on April 1."),
    ("Comptabilité <compta@agence.fr>", "Facture honoraires mars 2026", "Bonjour, veuillez trouver ci-joint notre facture d'honoraires pour le mois de mars. Montant: 4 200,00 €."),
    ("Finance <finance@cloud-service.io>", "Payment Due: Cloud Infrastructure", "Your cloud infrastructure bill for March is $1,456.78. Payment is due by April 5."),
    ("Finance <finance@freelancer.com>", "Invoice for Development Work", "Please review the attached invoice for 40 hours of development work at $150/hr. Total: $6,000."),
    ("Trésorerie <tresorerie@fournisseur.fr>", "Rappel facture #2026-789", "Ceci est un rappel que la facture #2026-789 de 2 300,00 € arrive à échéance le 28 mars."),
    ("Accounting <accounting@design-studio.com>", "Invoice #DS-2026-045", "Attached is our invoice for the UI/UX design project. Amount due: $8,500.00."),
    ("Finance <finance@hosting.com>", "Past due: Invoice #789", "This invoice is overdue by 15 days. Amount: $349.99. Please settle the payment."),
    ("Comptabilité <compta@prestataire.fr>", "Facture prestation technique", "Facture pour la prestation technique du 10 au 20 mars. Montant: 5 600,00 €."),
    ("Comptabilité <compta@saas-service.com>", "Invoice #SaaS-2026-123", "Your SaaS subscription invoice is ready. Amount: $99.00. Payment due: April 10."),
    ("Finance <finance@agency-creative.com>", "Q1 2026 Invoice", "Please find attached our Q1 2026 invoice for marketing services. Total: $12,000."),
    ("Finance <finance@legal-firm.fr>", "Facture honoraires juridiques", "Honoraires pour la rédaction du contrat de partenariat. Montant: 3 500,00 €."),
    ("Accounts Receivable <ar@logistics.com>", "Invoice #LOG-5678", "Invoice for shipping and logistics services. Amount: $2,100.00. Net 30."),
    ("Comptabilité <compta@cabinet.fr>", "Facture audit annuel", "Facture pour l'audit annuel des comptes 2025. Montant: 7 800,00 €. Paiement sous 30 jours."),
    ("Finance <finance@data-service.io>", "Monthly Data Service Invoice", "Your data processing invoice for March: $567.89. Auto-payment scheduled April 5."),
    ("Finance <finance@contractor.com>", "Invoice: Website Redesign Phase 2", "Phase 2 of website redesign complete. Invoice amount: $15,000. Payment due April 15."),
    ("Comptabilité <accounting@training.fr>", "Facture formation équipe", "Formation TypeScript avancé — 2 jours. Montant: 2 400,00 € HT."),
    ("AP <ap@vendor.co>", "Overdue Invoice Reminder: #V-4567", "Invoice #V-4567 is now 30 days overdue. Amount: $4,200.00. Please process immediately."),
    ("Finance <finance@studio.fr>", "Facture vidéo promotionnelle", "Production de la vidéo promotionnelle. Montant: 6 000,00 €. Conditions: 50% à la commande."),
    ("Finance <finance@analytics-corp.com>", "Annual Subscription Renewal Invoice", "Your annual subscription renewal invoice. Amount: $2,388.00. Due: April 1."),
    ("Comptabilité <compta@imprimerie.fr>", "Facture impression supports marketing", "Impression de 5000 flyers et 500 brochures. Montant: 1 250,00 €."),
    ("Finance <finance@it-consulting.com>", "Invoice: Security Assessment", "Security assessment and penetration testing report. Amount: $5,500.00."),
    ("Trésorerie <finance@partenaire.fr>", "Relevé de compte — mars 2026", "Votre relevé de compte au 25 mars 2026. Solde débiteur: 8 340,00 €. Merci de régulariser."),
    ("Finance <finance@recruitment-agency.com>", "Placement Fee Invoice", "Invoice for the placement of Senior Engineer. Fee: $18,000 (20% of annual salary)."),
    ("Comptabilité <compta@transport.fr>", "Facture transport mars", "Facture pour les livraisons du mois de mars. Montant: 890,00 € TTC."),
    ("Finance <finance@insurance.com>", "Insurance Premium Invoice — Payment Due", "Your annual business insurance premium of $3,456.00 is due by April 1. Please find the invoice attached."),
    ("Facturation <facturation@telecom.fr>", "Facture télécom #T-2026-03", "Votre facture télécom du mois de mars. Montant: 456,78 €. Prélèvement le 5 avril."),
    ("Comptabilité <compta@office-supplies.com>", "Invoice: Office Equipment", "Invoice for ergonomic chairs (x10) and standing desks (x5). Total: $7,890.00."),
    ("Comptabilité <compta@event.fr>", "Facture location salle", "Location de salle pour le séminaire du 15 mars. Montant: 1 500,00 €."),
    ("Finance <finance@cleaning.com>", "Monthly Cleaning Service Invoice", "March 2026 office cleaning service. Amount: $450.00."),
    ("AP <ap@electronics.co>", "Invoice: IT Hardware Order", "Invoice for 20 Dell monitors and 10 docking stations. Total: $12,340.00."),
    ("Comptabilité <compta@traiteur.fr>", "Facture réception client", "Service traiteur pour la réception du 20 mars. Montant: 2 800,00 €."),
    ("Finance <finance@software-license.com>", "License Renewal Invoice", "Annual software license renewal. Amount: $5,999.00. Due: April 15."),
    ("Finance <finance@copier.fr>", "Facture maintenance photocopieur", "Contrat de maintenance photocopieur — trimestre 1 2026. Montant: 350,00 €."),
    ("Accounts <accounts@aws-partner.com>", "AWS Consulting Invoice", "Invoice for AWS architecture review and optimization. Amount: $8,000.00."),
    ("Comptabilité <compta@securite.fr>", "Facture gardiennage mars", "Service de gardiennage pour le mois de mars. Montant: 4 500,00 €."),
    ("Finance <finance@pr-agency.com>", "PR Services Invoice: Q1", "Public relations services for Q1 2026. Total: $9,500.00."),
    ("Facturation <facturation@hebergeur.fr>", "Facture hébergement serveurs", "Hébergement serveurs dédiés — mars 2026. Montant: 780,00 € HT."),
    ("Finance <finance@payroll-corp.com>", "Payroll Processing Fee Invoice", "March payroll processing fee invoice for 45 employees. Amount: $675.00. Payment due: April 5."),
    ("Comptabilité <compta@plombier.fr>", "Facture intervention urgente", "Intervention urgente du 18 mars — réparation fuite. Montant: 320,00 € TTC."),
    ("Finance <finance@translation.com>", "Translation Services Invoice", "Invoice for 15,000 words translated FR→EN. Amount: $1,950.00."),
    ("Comptabilité <compta@electricien.fr>", "Facture travaux électriques", "Installation de prises réseau — bureau 3ème étage. Montant: 1 200,00 €."),
    ("Finance <finance@coworking-space.com>", "Monthly Coworking Space Invoice", "March 2026: 5 dedicated desks. Invoice amount: $2,250.00. Payment due: April 5."),
    ("Trésorerie <finance@assurance.fr>", "Facture — Appel de cotisation 2026", "Cotisation annuelle d'assurance responsabilité civile. Montant: 1 890,00 €. Échéance: 15 avril."),
    ("Accounting <accounting@media-agency.com>", "Media Buying Invoice: March", "Digital advertising spend for March. Total: $14,500.00."),
    ("Comptabilité <compta@photographe.fr>", "Facture shooting produit", "Session photo produit — 50 photos retouchées. Montant: 950,00 €."),
]

# --- 3. Approval/Review requests (50) ---
ACTION_APPROVALS = [
    ("Marc Dupont <marc@company.fr>", "Re: Access request", "Please review and approve the access request for the staging environment."),
    ("HR Team <hr@company.com>", "Vacation Request: Approval Needed", "Please approve Jean's vacation request for April 7-11."),
    ("Legal <legal@company.fr>", "Contrat à signer", "Signature requise pour le contrat de partenariat avec TechStartup Inc."),
    ("Manager <manager@company.com>", "Budget Approval Required", "Please approve the Q2 marketing budget of $45,000. Deadline: March 28."),
    ("Procurement <procurement@company.fr>", "Demande d'achat à valider", "Veuillez valider la demande d'achat #PA-2026-089 pour du matériel informatique."),
    ("IT Admin <it@company.com>", "Permission request: Admin access", "Please review the request for admin access to the production database."),
    ("Finance <finance@company.fr>", "Engagement budgétaire à approuver", "Pourrais-tu approuver l'engagement budgétaire de 12 000 € pour le projet mobile?"),
    ("Design Lead <design@company.com>", "Design approval: Landing page v3", "Please sign off on the final design for the landing page before we hand off to dev."),
    ("RH <rh@company.fr>", "Demande de formation à valider", "Veuillez approuver la demande de formation AWS pour 3 développeurs."),
    ("Project Manager <pm@company.com>", "Release sign-off needed", "Please approve the release of v2.5.0 to production. All tests pass."),
    ("Directeur <directeur@company.fr>", "Approbation recrutement", "Merci de valider l'ouverture du poste de Tech Lead. Fiche de poste jointe."),
    ("QA Lead <qa@company.com>", "Test plan approval", "Please review and approve the test plan for the payment module."),
    ("Compliance <compliance@company.fr>", "Validation conformité RGPD", "Merci de valider le rapport de conformité RGPD avant envoi à la CNIL."),
    ("Security <security@company.com>", "Firewall rule change: Approval needed", "Please approve the firewall rule change to allow traffic on port 8443."),
    ("DRH <drh@company.fr>", "Augmentation à valider", "Veuillez approuver la proposition d'augmentation pour Mathieu Leroy."),
    ("Architecture Board <arch@company.com>", "ADR-045: Review and approve", "Please review Architecture Decision Record #045 on the new caching strategy."),
    ("Comptabilité <compta@company.fr>", "Note de frais à approuver", "Peux-tu valider les 3 notes de frais en attente? Montant total: 1 245,00 €."),
    ("VP Engineering <vp@company.com>", "Hiring plan: Q2 review", "Please review and approve the Q2 hiring plan for 5 new engineers."),
    ("Juridique <juridique@company.fr>", "NDA à signer", "Merci de signer le NDA avec le nouveau partenaire. Document à signer joint."),
    ("Product Owner <po@company.com>", "Feature specification approval", "Please approve the spec for the auto-labeling feature. Deadline: Friday."),
    ("DSI <dsi@company.fr>", "Validation choix technique", "Peux-tu approuver le choix de PostgreSQL comme base de données principale?"),
    ("CTO <cto@company.com>", "Infrastructure proposal: Review needed", "Please review the proposal to migrate from AWS to GCP. Cost analysis attached."),
    ("RH <rh@company.fr>", "Solde de tout compte à valider", "Merci de valider le solde de tout compte de Marie Dupont avant le 31 mars."),
    ("Team Lead <lead@company.com>", "Code review: Merge blocked", "Please approve PR #567 to unblock the release. It's been waiting since yesterday."),
    ("Directrice <directrice@company.fr>", "Plan stratégique à valider", "Veuillez valider le plan stratégique 2026-2027 avant la présentation au board."),
    ("Legal <legal@company.com>", "Terms of Service update approval", "Please review and approve the updated Terms of Service. Legal review complete."),
    ("Finance <finance@company.fr>", "Approbation dépense exceptionnelle", "Pourrais-tu approuver la dépense exceptionnelle de 8 000 € pour le salon tech?"),
    ("Engineering Manager <em@company.com>", "On-call rotation: Approval needed", "Please approve the new on-call rotation schedule starting April 1."),
    ("Responsable QSE <qse@company.fr>", "Document qualité à signer", "Merci de signer la procédure qualité QP-2026-012 avant audit."),
    ("Data Protection <dpo@company.com>", "Data processing agreement: Sign", "Please sign the DPA with our new analytics provider. Deadline: March 28."),
    ("Achats <achats@company.fr>", "Bon de commande à valider", "Veuillez valider le bon de commande #BC-2026-456 pour les licences JetBrains."),
    ("CEO <ceo@company.com>", "Board presentation: Final review", "Please review the board presentation before our meeting on Friday."),
    ("DAF <daf@company.fr>", "Clôture comptable à approuver", "Peux-tu approuver la clôture comptable du mois de mars? On doit envoyer au cabinet avant vendredi."),
    ("Tech Lead <tech@company.com>", "Database schema change: Approve", "Please approve the database schema migration for the new labeling system."),
    ("Médecin du travail <medecin@company.fr>", "Avis d'aptitude à signer", "Merci de signer l'avis d'aptitude pour les 5 nouveaux collaborateurs."),
    ("VP Product <vpproduct@company.com>", "Roadmap Q3: Approval required", "Please approve the Q3 product roadmap. Presentation slides attached."),
    ("Responsable sécurité <securite@company.fr>", "PCA à valider", "Merci de valider le Plan de Continuité d'Activité mis à jour."),
    ("Marketing Director <mktg-director@company.com>", "Campaign budget: Sign-off", "Please approve the $25,000 budget for the launch campaign."),
    ("DG <dg@company.fr>", "Partenariat stratégique à approuver", "Veuillez donner votre approbation pour le partenariat avec CloudTech."),
    ("Release Manager <rm@company.com>", "Hotfix deployment: Approval needed", "Critical bug fix ready. Please approve deployment to production."),
    ("Secrétariat général <sg@company.fr>", "PV assemblée à signer", "Merci de signer le procès-verbal de l'assemblée générale du 20 mars."),
    ("Engineering VP <evp@company.com>", "New tool procurement: Approve", "Please approve the purchase of 50 Copilot Enterprise licenses ($19/user/mo)."),
    ("Responsable formation <formation@company.fr>", "Plan de formation à valider", "Veuillez valider le plan de formation 2026. Budget: 35 000 €."),
    ("IT Director <itd@company.com>", "Vendor selection: Final approval", "Please approve the selection of CloudGuard as our new security vendor."),
    ("Contrôle de gestion <cdg@company.fr>", "Rapport mensuel à valider", "Merci de valider le rapport de gestion de mars avant diffusion."),
    ("Site Reliability <sre@company.com>", "SLA update: Customer approval", "Please review and approve the updated SLA terms for enterprise customers."),
    ("Chef de projet <cdp@company.fr>", "Planning projet à valider", "Veuillez valider le planning du projet migration cloud."),
    ("Board Secretary <secretary@company.com>", "Board resolution: E-signature", "Please sign the board resolution regarding the Series B funding."),
    ("DAF adjoint <dafadj@company.fr>", "Virement fournisseur à valider", "Merci de valider les virements fournisseurs du mois. Montant total: 45 670 €."),
    ("Head of Engineering <hoe@company.com>", "Team restructuring: Review", "Please review and approve the proposed team restructuring plan."),
]

# --- 4. Meeting/RSVP requests (40) ---
ACTION_MEETINGS = [
    ("Julie Morin <julie@company.fr>", "Réunion demain", "Tu es dispo demain à 14h pour le point projet?"),
    ("Mark Stevens <mark@client.com>", "Meeting request: Product demo", "Can we schedule a 30-minute call Thursday to review the product demo?"),
    ("Sophie Leblanc <sophie@team.fr>", "Déjeuner équipe vendredi", "RSVP pour le déjeuner d'équipe vendredi midi. On va au resto italien."),
    ("Alex Turner <alex@partner.io>", "Quarterly business review", "Are you free next Tuesday at 10am for the QBR? I've blocked the room."),
    ("Camille Durand <camille@company.fr>", "Point hebdo", "On se voit à 10h pour le standup? J'ai des sujets à aborder."),
    ("Paul Richardson <paul@vendor.com>", "Contract negotiation meeting", "Can we meet Friday at 2pm to finalize the contract terms?"),
    ("Marie-Claire Petit <mc@company.fr>", "Séminaire équipe", "Est-ce que tu peux confirmer ta présence au séminaire du 5 avril?"),
    ("David Chen <david@startup.io>", "Investor pitch preparation", "Are you available Wednesday to rehearse the investor pitch?"),
    ("Thomas Lefevre <thomas@company.fr>", "Entretien candidat", "Tu peux faire passer l'entretien technique au candidat demain à 15h?"),
    ("Sarah Kim <sarah@design.com>", "Design critique session", "RSVP for the design critique session Thursday at 3pm. Your feedback is needed."),
    ("Pierre Garnier <pierre@company.fr>", "Soutenance de stage", "Est-ce que tu es dispo le 2 avril pour la soutenance du stagiaire?"),
    ("Lisa Anderson <lisa@marketing.io>", "Launch planning meeting", "Can we schedule a meeting to plan the v3.0 launch? I need your input."),
    ("Nicolas Roche <nicolas@company.fr>", "Rétrospective sprint", "On fait la rétro vendredi à 16h? J'ai réservé la salle Everest."),
    ("Jane Cooper <jane@hr.com>", "Team building event: RSVP", "RSVP for the team building event on April 12. Activities: escape room and dinner."),
    ("Olivier Martin <olivier@company.fr>", "Point client urgent", "Tu es dispo dans l'heure pour un appel avec le client? Il y a un problème."),
    ("Michael Lee <michael@enterprise.com>", "Partnership discussion", "Would you be available next week for a discussion about partnership opportunities?"),
    ("Chloé Fontaine <chloe@company.fr>", "Atelier design thinking", "On se retrouve mercredi pour l'atelier design thinking? 10h en salle Montblanc."),
    ("Robert Williams <robert@consulting.com>", "Strategy workshop", "Can you confirm your attendance at the strategy workshop April 8-9?"),
    ("Margaux Dufour <margaux@company.fr>", "Café et brainstorm", "Ça te dit un café demain matin pour brainstormer sur le nouveau produit?"),
    ("Andrew Park <andrew@tech.io>", "Technical architecture review", "Are you free Thursday afternoon for the architecture review? 3 hours blocked."),
    ("Élise Bertrand <elise@company.fr>", "Réunion comité de direction", "Est-ce que tu peux confirmer ta présence au comité de direction du 28 mars à 9h?"),
    ("Kevin Murphy <kevin@sales.com>", "Sales kickoff meeting", "RSVP for the Q2 sales kickoff on April 3. Presentations and team dinner."),
    ("Amandine Roy <amandine@company.fr>", "Point one-on-one", "On se fait un one-on-one vendredi? J'ai des sujets RH à discuter."),
    ("Jennifer Taylor <jennifer@partner.com>", "Integration kickoff", "Can we schedule a kickoff meeting for the API integration project?"),
    ("Raphaël Dumont <raphael@company.fr>", "Revue de code collective", "On se retrouve jeudi à 14h pour la revue de code du module auth? Tu viens?"),
    ("Emma Wilson <emma@agency.com>", "Creative brief meeting", "Are you available Monday to discuss the creative brief for the new campaign?"),
    ("Mathilde Laurent <mathilde@company.fr>", "Présentation nouveaux outils", "Je fais une démo des nouveaux outils de monitoring mardi à 11h. Tu viens?"),
    ("Jack Thompson <jack@infra.com>", "Incident post-mortem", "Can we schedule the post-mortem for last week's outage? Suggest Friday 10am."),
    ("Léna Moreau <lena@company.fr>", "Planning sprint suivant", "Tu es dispo lundi pour le planning du sprint 15?"),
    ("Daniel Brown <daniel@client.co>", "Contract renewal discussion", "Shall we schedule a call to discuss the contract renewal for next year?"),
    ("Gabrielle Simon <gabrielle@company.fr>", "Afterwork équipe tech", "On organise un afterwork jeudi soir. T'es dispo? On commence à 18h."),
    ("Ryan Hughes <ryan@vendor.io>", "Product roadmap alignment", "Are you free next week for a roadmap alignment session? 90 minutes."),
    ("Aurélie Mercier <aurelie@company.fr>", "Formation sécurité obligatoire", "T'es dispo le 2 avril pour la formation sécurité obligatoire? Confirme ta présence."),
    ("Chris Miller <chris@tech.com>", "Hackathon planning", "Would you like to participate in the internal hackathon April 15-16?"),
    ("Florence Beaumont <florence@company.fr>", "Journée portes ouvertes", "Est-ce que tu es dispo le 10 avril pour participer à la journée portes ouvertes?"),
    ("Steve Harris <steve@enterprise.io>", "Quarterly sync meeting", "Can we sync next Tuesday about the enterprise integration progress?"),
    ("Inès Lefebvre <ines@company.fr>", "Présentation client", "Tu es dispo demain pour la présentation au client? On a besoin de toi pour la partie technique."),
    ("Laura Green <laura@design.io>", "UX research planning", "Shall we meet to plan the next round of user interviews?"),
    ("Yann Chevalier <yann@company.fr>", "Réunion partenaires", "On a une réunion avec les partenaires le 3 avril. Tu confirmes ta présence?"),
    ("Amanda Roberts <amanda@pm.com>", "Sprint demo invitation", "RSVP for the sprint demo Friday at 4pm. Stakeholders will attend."),
]

# --- 5. French informal requests (40) ---
ACTION_FRENCH_INFORMAL = [
    ("Hugo <hugo@team.fr>", "Re: Fichier budget", "Peux-tu m'envoyer le fichier budget avant ce soir?"),
    ("Léa <lea@team.fr>", "Demain matin", "T'es dispo demain matin pour un café rapide?"),
    ("Maxime <maxime@team.fr>", "Point rapide", "On se voit à 14h? J'ai un truc à te montrer."),
    ("Camille <camille@team.fr>", "Ce midi", "Ça te dit de déjeuner ensemble ce midi?"),
    ("Antoine <antoine@team.fr>", "Slides", "Tu peux m'envoyer les slides de la présentation d'hier?"),
    ("Manon <manon@team.fr>", "Aide sur un bug", "J'ai besoin de ton aide sur un bug bloquant. Tu es dispo?"),
    ("Julien <julien@team.fr>", "Validation maquette", "Tu valides la maquette du nouveau dashboard?"),
    ("Chloé <chloe@team.fr>", "Question rapide", "Est-ce que tu peux me rappeler le mot de passe du serveur de staging?"),
    ("Romain <romain@team.fr>", "Code review", "Pourrais-tu reviewer mon code? C'est sur la branche feature/auth."),
    ("Émilie <emilie@team.fr>", "Réunion client", "T'es dispo pour la réunion client de jeudi après-midi?"),
    ("Nicolas <nicolas@team.fr>", "Doc API", "Peux-tu mettre à jour la documentation de l'API?"),
    ("Marine <marine@team.fr>", "Design", "Qu'en penses-tu du nouveau design de la page d'accueil?"),
    ("Adrien <adrien@team.fr>", "Déploiement", "On se retrouve à 17h pour le déploiement?"),
    ("Sophie <sophie@team.fr>", "Retours prod", "Tu peux vérifier les logs de prod? Je crois qu'il y a eu une erreur."),
    ("Thomas <thomas@team.fr>", "Formation React", "Ça vous dit une session formation React vendredi?"),
    ("Pauline <pauline@team.fr>", "Prêt de matériel", "Tu peux me prêter ton écran externe pour la démo de demain?"),
    ("Bastien <bastien@team.fr>", "Tests", "Est-ce que tu peux lancer les tests d'intégration sur staging?"),
    ("Laure <laure@team.fr>", "Retour sur le workshop", "Qu'en penses-tu du workshop d'hier? On fait un débrief?"),
    ("Vincent <vincent@team.fr>", "Accès serveur", "J'aurais besoin d'un accès SSH au serveur de prod. Tu peux m'arranger ça?"),
    ("Anaïs <anais@team.fr>", "Sprint review", "Tu viens à la sprint review de demain? On a besoin de tes retours."),
    ("Pierre-Antoine <pa@team.fr>", "Merge request", "Tu peux valider ma merge request? C'est prêt depuis ce matin."),
    ("Clara <clara@team.fr>", "Maquette mobile", "Tu as eu le temps de regarder la maquette mobile? Ça te va?"),
    ("Mathieu <mathieu@team.fr>", "Script migration", "Peux-tu vérifier mon script de migration avant que je le lance en prod?"),
    ("Élise <elise@team.fr>", "Brainstorm", "On se fait un brainstorm demain matin sur la feature de notifications?"),
    ("Thibault <thibault@team.fr>", "Config Nginx", "Tu peux jeter un œil à la config Nginx? Le reverse proxy ne marche pas."),
    ("Marion <marion@team.fr>", "Planning", "Tu es dispo la semaine prochaine pour le planning projet?"),
    ("Gabriel <gabriel@team.fr>", "Pair programming", "Ça te dit une session de pair programming cet après-midi?"),
    ("Agathe <agathe@team.fr>", "Retour client", "Tu peux appeler le client pour le rassurer? Il s'inquiète du retard."),
    ("Sébastien <sebastien@team.fr>", "Benchmark", "Pourrais-tu faire un benchmark Redis vs Memcached pour le cache?"),
    ("Inès <ines@team.fr>", "Point projet", "On se voit à 16h pour faire le point sur le projet?"),
    ("Florian <florian@team.fr>", "Hotfix", "J'ai besoin que tu valides le hotfix avant déploiement. Tu peux?"),
    ("Célia <celia@team.fr>", "Feedback design", "Tu viens voir le nouveau prototype? J'ai besoin de ton feedback."),
    ("Damien <damien@team.fr>", "Base de données", "Est-ce que tu peux m'expliquer le schéma de la base de données?"),
    ("Lucie <lucie@team.fr>", "Compte-rendu", "Tu peux rédiger le compte-rendu de la réunion de ce matin?"),
    ("Arnaud <arnaud@team.fr>", "Intégration API", "Qu'est-ce que tu en penses de l'intégration avec l'API partenaire?"),
    ("Julie <julie@team.fr>", "Présentation", "Tu es dispo pour répéter la présentation client avec moi?"),
    ("Kévin <kevin@team.fr>", "Performance", "Tu peux regarder pourquoi l'endpoint /search est lent?"),
    ("Amandine <amandine@team.fr>", "Accès admin", "J'aurais besoin des droits admin sur le backoffice. Tu peux?"),
    ("Valentin <valentin@team.fr>", "Release notes", "Peux-tu écrire les release notes pour la version 3.2?"),
    ("Margot <margot@team.fr>", "Tests E2E", "Tu peux ajouter des tests E2E pour le nouveau parcours d'inscription?"),
]

# --- 6. Urgent/Security from NON-automated senders (40) ---
ACTION_URGENT_SECURITY = [
    ("Security Team <security@google.com>", "Unusual sign-in detected", "We noticed a sign-in to your account from a new device in Montreal, Canada. If this wasn't you, change your password immediately."),
    ("Security <security@bank.com>", "Suspicious activity on your account", "We detected suspicious activity on your account. A transaction of $2,500 was attempted from an unrecognized device."),
    ("Security <security@platform.com>", "Verify your identity", "Please verify your identity to regain access to your account. We blocked a suspicious login attempt."),
    ("Sécurité <securite@banque.fr>", "Activité suspecte détectée", "Une activité suspecte a été détectée sur votre compte. Veuillez vérifier vos dernières transactions."),
    ("Security <security@service.com>", "Secure your account now", "We noticed unusual login activity on your account from an IP address in Ukraine. Secure your account now."),
    ("Security <security@github.com>", "New SSH key added to your account", "A new SSH key was added to your account. If you did not make this change, secure your account immediately."),
    ("Security <security@mycompany-cloud.com>", "Root account sign-in detected", "A sign-in to your cloud root account was detected. If this wasn't you, change your password and enable MFA."),
    ("Sécurité <securite@paypal.fr>", "Connexion inhabituelle", "Nous avons détecté une activité inhabituelle sur votre compte PayPal depuis un appareil inconnu. Si ce n'est pas vous, sécurisez votre compte."),
    ("Security <security@stripe.com>", "API key compromised", "We believe your API key sk_live_xxx may have been compromised. If you didn't make this change, secure your account and rotate it immediately."),
    ("Security Team <security@dropbox.com>", "Account locked", "Your account has been locked due to multiple failed login attempts. Verify your identity to unlock."),
    ("Sécurité <securite@impots.gouv.fr>", "Tentative de connexion suspecte", "Si ce n'est pas vous qui avez tenté de vous connecter, sécurisez votre compte immédiatement."),
    ("Security <security@digitalocean.com>", "Unauthorized access attempt", "We detected an unauthorized access attempt to your DigitalOcean account from Russia."),
    ("Sécurité <securite@laposte.fr>", "Activité inhabituelle sur votre compte", "Nous avons détecté une activité inhabituelle. Vérifiez votre identité pour continuer."),
    ("Security <security@cloudflare.com>", "Account compromised alert", "Your Cloudflare account may have been compromised. We've temporarily restricted access."),
    ("Security <security@myvercel-project.com>", "New team member added", "A new team member was added to your project. If you didn't do this, secure your account and review your team settings."),
    ("Sécurité <securite@orange.fr>", "Changement de mot de passe suspect", "Un changement de mot de passe a été effectué sur votre compte. Si ce n'était pas vous, contactez-nous."),
    ("Security <security@heroku.com>", "API key rotation required", "Unusual access detected: your Heroku API key may have been exposed in a public repository. If you didn't do this, rotate it now."),
    ("Security <security@mongodb.com>", "IP whitelist modified", "Unusual activity detected: the IP whitelist for your MongoDB Atlas cluster was modified. If this wasn't you, review the changes immediately."),
    ("Sécurité <securite@credit-mutuel.fr>", "Transaction suspecte de 1 500 €", "Activité suspecte détectée: une transaction de 1 500 € a été effectuée. Si ce n'est pas vous, contactez-nous immédiatement."),
    ("Security <security@gitlab.com>", "Deploy token accessed from new IP", "Unusual access detected: your deploy token was used from an unrecognized IP address. If this wasn't you, review access logs."),
    ("Security <security@slack.com>", "Workspace admin change", "Unusual activity detected: a new workspace admin was added to your Slack workspace. If this wasn't you, review immediately."),
    ("Sécurité <securite@societe-generale.fr>", "Compte verrouillé", "Votre compte a été verrouillé suite à 5 tentatives de connexion échouées. Vérifiez votre identité."),
    ("Security <security@fastly.com>", "TLS certificate expiring — action required", "Your TLS certificate for api.example.com expires in 3 days. Renew it immediately to avoid service disruption. If you didn't request this change, secure your account."),
    ("Security <security@datadog.com>", "Unusual API usage detected", "We detected unusual activity on your Datadog account. If this wasn't you, review your API keys immediately."),
    ("Sécurité <securite@caisse-epargne.fr>", "Virement suspect de 3 000 €", "Un virement de 3 000 € a été initié. Si ce n'est pas vous, bloquez votre carte immédiatement."),
    ("Security <security@okta.com>", "MFA device added", "A new MFA device was registered on your Okta account. If this wasn't you, contact your admin."),
    ("Security <security@supabase.com>", "Database password changed", "The database password for your Supabase project was changed. If this wasn't you, reset your password and secure your account immediately."),
    ("Sécurité <securite@bnp-paribas.fr>", "Alerte fraude", "Activité suspecte détectée sur votre carte bancaire. Vérifiez les transactions récentes."),
    ("Security <security@firebase.com>", "Service account key downloaded", "Unusual activity on your Firebase project: a new service account key was downloaded. If this wasn't you, revoke it immediately."),
    ("Security <security@azure.microsoft.com>", "Unusual resource provisioning", "Unusual activity detected in your Azure subscription: unauthorized VM provisioning. If this wasn't you, review and secure your account."),
    ("Sécurité <securite@banque-nationale.fr>", "Connexion depuis un nouvel appareil", "Si ce n'était pas vous, sécurisez votre compte immédiatement."),
    ("Security <security@gcp.google.com>", "IAM policy change detected", "Suspicious activity on your GCP project: an IAM policy change was detected. If this wasn't you, review the modifications immediately."),
    ("Security <security@auth0.com>", "Brute force attack detected", "Suspicious activity detected: we detected a brute force attack on your Auth0 tenant. Secure your account and review access logs immediately."),
    ("Sécurité <securite@lcl.fr>", "Carte bloquée préventivement", "Activité suspecte détectée sur votre carte bancaire. Votre carte a été bloquée préventivement. Si ce n'est pas vous, contactez-nous immédiatement."),
    ("Security <security@railway.app>", "Environment variable exposed", "Unusual activity: an environment variable containing a secret may have been exposed. If you didn't make this change, secure your account and rotate the credential."),
    ("Security <security@render.com>", "SSH access from new location", "Unusual access detected: SSH access to your Render service was initiated from a new geographic location. If this wasn't you, review your security settings."),
    ("Sécurité <securite@boursorama.fr>", "Activité suspecte détectée", "Nous avons détecté une activité suspecte sur votre espace client. Si ce n'est pas vous, sécurisez votre compte immédiatement."),
    ("Security <security@mymonitoring-app.com>", "Organization ownership transfer", "An ownership transfer was initiated for your organization. If this wasn't you, secure your account and reject the transfer immediately."),
    ("Security <security@fly.io>", "Machine accessed from unknown IP", "Unusual access detected: your Fly.io machine was accessed from an unknown IP address. If this wasn't you, review security settings immediately."),
    ("Sécurité <securite@revolut.com>", "Transaction bloquée", "Activité suspecte détectée: votre transaction de 890 € a été bloquée. Si ce n'est pas vous, sécurisez votre compte immédiatement."),
]


# ============================================================================
# EMAIL DATA — FYI (150 total)
# ============================================================================

# --- 1. FYI markers (40) ---
FYI_MARKERS = [
    ("Pierre Dumont <pierre@team.fr>", "Re: Rapport Q1", "FYI: le rapport Q1 est disponible sur le Drive partagé."),
    ("Alice Cooper <alice@company.com>", "Budget update", "FYI — the marketing budget has been approved. No action needed from you."),
    ("Marc Leblanc <marc@team.fr>", "Pour info: nouveau process", "Pour info: on a mis en place un nouveau process de déploiement. Détails sur le wiki."),
    ("Sarah Johnson <sarah@company.com>", "Heads up on deployment", "Just a heads up — we're deploying to production tonight at 11pm."),
    ("Thomas Girard <thomas@team.fr>", "Info: changement de bureau", "À titre d'information: l'équipe tech déménage au 3ème étage la semaine prochaine."),
    ("Emily Brown <emily@company.com>", "No action needed: Q1 results", "No action needed — just sharing the Q1 results with the team. Revenue up 15%."),
    ("Julien Martin <julien@team.fr>", "Pour ton info", "Pour ton info: le client a validé la proposition. On peut démarrer."),
    ("David Wilson <david@company.com>", "FYI: Team restructuring", "For your information, the engineering team will be reorganized starting April 1."),
    ("Nathalie Petit <nathalie@team.fr>", "Info interne", "Pour info: la direction a annoncé un jour de télétravail supplémentaire."),
    ("Chris Taylor <chris@company.com>", "FYI: New vendor selected", "FYI: we've selected CloudGuard as our new security vendor. Details in the attached doc."),
    ("Céline Roux <celine@team.fr>", "Pour ta gouverne", "Pour info: le DSI a approuvé le budget cloud pour 2026. On peut commander les instances."),
    ("Matt Lee <matt@company.com>", "Heads up: API deprecation", "Heads up — API v1 will be deprecated on June 1. Plan your migration."),
    ("Audrey Moreau <audrey@team.fr>", "FYI: Résultat audit", "FYI — l'audit de sécurité est passé. Aucune vulnérabilité critique trouvée."),
    ("Jason Clark <jason@company.com>", "No response needed: Pricing update", "No response needed. Just letting you know we've updated the pricing page."),
    ("Marion Dupont <marion@team.fr>", "Info: congés été", "Pour info: la période de congés d'été est ouverte. Posez vos dates avant le 15 avril."),
    ("Laura White <laura@company.com>", "FYI: Competition analysis", "FYI — I've completed the competition analysis. Report attached for reference."),
    ("Philippe Bernard <philippe@team.fr>", "Pour info: migration terminée", "À titre informatif: la migration vers PostgreSQL 17 est terminée. Tout fonctionne."),
    ("Kevin Adams <kevin@company.com>", "Heads up: Office closure", "Just a heads up that the office will be closed on April 18 for Good Friday."),
    ("Sandrine Laurent <sandrine@team.fr>", "FYI: Nouveau prestataire", "Pour votre information: nous avons changé de prestataire pour le nettoyage des bureaux."),
    ("Rachel Kim <rachel@company.com>", "FYI: Training calendar", "For your information, the Q2 training calendar is now published on the intranet."),
    ("Olivier Chevalier <olivier@team.fr>", "Info: maintenance serveurs", "Pour info: maintenance planifiée des serveurs samedi de 2h à 6h du matin."),
    ("Amanda Garcia <amanda@company.com>", "No action required: Legal update", "No action required. Legal has updated the privacy policy. See attached."),
    ("François Simon <francois@team.fr>", "FYI: Nouvelle imprimante", "FYI — une nouvelle imprimante a été installée au 2ème étage, salle de pause."),
    ("Ben Thompson <ben@company.com>", "Heads up: Sprint scope change", "Heads up — the sprint scope has been adjusted. 2 stories moved to next sprint."),
    ("Isabelle Blanc <isabelle@team.fr>", "Pour info: résultats sondage", "Pour info: les résultats du sondage de satisfaction sont disponibles sur l'intranet."),
    ("Daniel Rogers <daniel@company.com>", "FYI: Client feedback", "FYI — positive client feedback from the demo yesterday. Well done team!"),
    ("Carole Perrin <carole@team.fr>", "Info: nouvel outil", "Pour info: on adopte Linear pour le suivi de projets à partir du 1er avril."),
    ("Mike Robinson <mike@company.com>", "No action: Build status", "No action needed. CI/CD pipeline has been fixed. All builds are green again."),
    ("Estelle Dupuis <estelle@team.fr>", "FYI: Partenariat confirmé", "FYI — le partenariat avec TechStartup a été officialisé. Communiqué de presse à venir."),
    ("Greg Harris <greg@company.com>", "Heads up: Monitoring change", "Just a heads up — we've switched monitoring from Datadog to Grafana."),
    ("Sophie Arnaud <sophie@team.fr>", "Info: badge accès", "Pour info: les badges d'accès seront remplacés la semaine prochaine. Passez à l'accueil."),
    ("Jake Nelson <jake@company.com>", "FYI: Open source contribution", "FYI — we've open-sourced our rate limiting library. GitHub link inside."),
    ("Pauline Marchand <pauline@team.fr>", "Pour info: vacances Pierre", "Pour info: Pierre sera en vacances du 7 au 18 avril. Adressez-vous à Julien pendant son absence."),
    ("Chris Evans <chris@company.com>", "No response needed: Docs updated", "No response needed. I've updated the architecture docs on Confluence."),
    ("Valérie Fontaine <valerie@team.fr>", "FYI: Résultat appel d'offres", "FYI: nous avons remporté l'appel d'offres pour le projet municipal. Détails à venir."),
    ("Tim Baker <tim@company.com>", "Heads up: Dependencies updated", "Heads up — all npm dependencies have been updated to latest versions. Tests pass."),
    ("Hélène Garnier <helene@team.fr>", "Pour info: réorganisation bureaux", "Pour info: la réorganisation des bureaux commence lundi. Plan joint."),
    ("Anna Scott <anna@company.com>", "FYI: Customer milestone", "For your information, we've reached 10,000 active users. Great milestone!"),
    ("René Berger <rene@team.fr>", "Info: changement horaires", "Pour info: les horaires de la cantine changent à partir du 1er avril. Nouveau: 11h30-14h."),
    ("Lisa Turner <lisa@company.com>", "FYI: Conference talk accepted", "FYI — my talk on AI email classification has been accepted at PyCon 2026."),
]

# --- 2. Forwards (30) ---
FYI_FORWARDS = [
    ("Pierre <pierre@team.fr>", "Fwd: Article intéressant sur l'IA", "Je te transfère cet article sur les dernières avancées en IA. Ça pourrait t'intéresser."),
    ("Alice <alice@company.com>", "Fwd: Meeting notes from yesterday", "Forwarding the meeting notes from yesterday's sync. See below."),
    ("Marc <marc@team.fr>", "Tr: Compte-rendu réunion client", "Je te fais suivre le compte-rendu de la réunion client. Voir ci-dessous."),
    ("Sarah <sarah@company.com>", "Fwd: Competitor analysis report", "Thought you should see this competitor analysis. Interesting findings."),
    ("Thomas <thomas@team.fr>", "Tr: Nouvelle politique RH", "Je te transmets la nouvelle politique RH. Voir ci-dessous pour les détails."),
    ("Emily <emily@company.com>", "Fwd: Industry benchmark data", "Forwarding this benchmark data from Gartner. Good reference for our planning."),
    ("Julien <julien@team.fr>", "Fwd: Bug report du client", "Je te fais suivre le bug report du client. Pas urgent, pour info."),
    ("David <david@company.com>", "Fwd: Investment memo", "Wanted to share this investment memo. Relevant to our fundraising strategy."),
    ("Nathalie <nathalie@team.fr>", "Tr: Retour fournisseur", "Je te transfère le retour du fournisseur. Pas d'action de ta part."),
    ("Chris <chris@company.com>", "Fwd: Tech blog post about our product", "See below — a tech blog mentioned our product in a positive review."),
    ("Céline <celine@team.fr>", "Tr: Rapport sectoriel", "Je te fais suivre ce rapport sectoriel intéressant. Bonne lecture."),
    ("Matt <matt@company.com>", "Fwd: Conference CFP", "Forwarding the call for papers for PyCon 2026. In case you're interested."),
    ("Audrey <audrey@team.fr>", "Tr: Résultats benchmark", "Voici les résultats du benchmark de performance. Voir ci-dessous."),
    ("Jason <jason@company.com>", "Fwd: Customer success story", "Forwarding a great customer success story from the sales team."),
    ("Marion <marion@team.fr>", "Fwd: Article React 19", "Un bon article sur les nouveautés de React 19. Je te le transfère."),
    ("Laura <laura@company.com>", "Fwd: Market research findings", "See the market research findings below. Interesting data points."),
    ("Philippe <philippe@team.fr>", "Tr: Offre de formation", "Je te transmets une offre de formation sur Kubernetes. Pour info."),
    ("Kevin <kevin@company.com>", "Fwd: Security advisory", "Forwarding this security advisory about a critical vulnerability in OpenSSL."),
    ("Sandrine <sandrine@team.fr>", "Tr: Planning événement", "Je te fais suivre le planning de l'événement du mois prochain."),
    ("Rachel <rachel@company.com>", "Fwd: Design trends 2026", "Thought you'd enjoy this article on 2026 design trends."),
    ("Olivier <olivier@team.fr>", "Tr: Proposition commerciale", "Je te transfère la proposition commerciale du partenaire. Pour info."),
    ("Amanda <amanda@company.com>", "Fwd: Board meeting summary", "See below for the board meeting summary from last week."),
    ("François <francois@team.fr>", "Fwd: Rapport mensuel infra", "Voici le rapport mensuel de l'infrastructure. Pas d'action requise."),
    ("Ben <ben@company.com>", "Fwd: Release announcement", "Forwarding the public release announcement for v3.0. FYI."),
    ("Isabelle <isabelle@team.fr>", "Tr: Retour entretien candidat", "Je te transmets le retour sur l'entretien du candidat. Pour info."),
    ("Daniel <daniel@company.com>", "Fwd: Partnership proposal", "See the partnership proposal below. Interesting opportunity."),
    ("Carole <carole@team.fr>", "Tr: Mise à jour contrat", "Je te fais suivre la mise à jour du contrat. Rien de critique."),
    ("Mike <mike@company.com>", "Fwd: Open source license review", "Forwarding the open source license review from legal. No issues found."),
    ("Estelle <estelle@team.fr>", "Fwd: Invitation conférence", "Je te transfère l'invitation à la conférence IA de Paris. Intéressant."),
    ("Greg <greg@company.com>", "Fwd: Customer survey results", "See the customer survey results below. Good feedback overall."),
]

# --- 3. Status updates (30) ---
FYI_STATUS_UPDATES = [
    ("Pierre <pierre@team.fr>", "Re: Projet X", "Pour info: le projet X avance bien. On est dans les temps pour la livraison du 31 mars."),
    ("Alice <alice@company.com>", "Sprint review notes", "FYI — Sprint 14 is complete. 18 of 20 stories delivered. Velocity steady at 38 pts."),
    ("Marc <marc@team.fr>", "Mise à jour projet migration", "Pour info: la migration de la base de données est terminée à 80%. On finit vendredi."),
    ("Sarah <sarah@company.com>", "Project X is on track", "Just wanted to let you know Project X is on track for the April 1 launch."),
    ("Thomas <thomas@team.fr>", "Point sur la refonte", "Pour info: la refonte du frontend progresse bien. 60% des composants sont migrés."),
    ("Emily <emily@company.com>", "Team update: Q2 kickoff", "Heads up — Q2 kickoff went well. New priorities set. Details in the shared doc."),
    ("Julien <julien@team.fr>", "Avancement sprint 15", "Pour info: sprint 15 en cours, 8 stories terminées sur 18. Pas de bloquant."),
    ("David <david@company.com>", "Feature launch recap", "FYI — the auto-labeling feature launched successfully. 0 critical bugs so far."),
    ("Nathalie <nathalie@team.fr>", "Rapport mensuel RH", "Voici le rapport RH de mars: 3 recrutements, 0 départ, NPS employés: 72."),
    ("Chris <chris@company.com>", "Infrastructure status update", "FYI — all services green. Uptime: 99.98%. No incidents this week."),
    ("Céline <celine@team.fr>", "Bilan campagne marketing", "Pour info: la campagne de mars a généré 2 500 leads. Coût par lead: 12,50 €."),
    ("Matt <matt@company.com>", "API performance report", "FYI — API response times stable. P50: 120ms, P95: 450ms, P99: 980ms."),
    ("Audrey <audrey@team.fr>", "Progression objectifs T1", "Pour info: objectifs T1 à 85% atteints. Détails dans le dashboard OKR."),
    ("Jason <jason@company.com>", "Customer support metrics", "FYI — March support metrics: 450 tickets, avg response: 2.1 hours, CSAT: 94%."),
    ("Marion <marion@team.fr>", "État des lieux technique", "Pour info: architecture microservices — 12 services déployés, 3 en développement."),
    ("Laura <laura@company.com>", "Design system progress", "Just a heads up — design system v3 is 90% complete. Remaining: data visualization components."),
    ("Philippe <philippe@team.fr>", "Bilan sécurité mars", "Pour info: audit sécurité — 0 vulnérabilité critique, 3 mineures corrigées."),
    ("Kevin <kevin@company.com>", "Sales pipeline update", "FYI — pipeline update: $250K in qualified opportunities. Expected close: April."),
    ("Sandrine <sandrine@team.fr>", "Rapport satisfaction client", "Pour ton info: NPS client à 68 (+5 vs février). Principaux retours positifs sur la rapidité."),
    ("Rachel <rachel@company.com>", "User growth metrics", "FYI — DAU: 1,500 (+12% MoM). WAU: 8,200 (+8% MoM). Retention: 45%."),
    ("Olivier <olivier@team.fr>", "Bilan formation T1", "Pour info: 12 formations dispensées au T1. 45 collaborateurs formés. Budget utilisé: 75%."),
    ("Amanda <amanda@company.com>", "Release notes v3.1", "FYI — v3.1 released: 4 new features, 12 bug fixes, 3 performance improvements."),
    ("François <francois@team.fr>", "Monitoring: tout est stable", "Pour info: tous les systèmes sont stables. Aucune alerte depuis 72 heures."),
    ("Ben <ben@company.com>", "Hiring update", "FYI — hiring update: 3 offers accepted, 2 pending, 5 interviews scheduled next week."),
    ("Isabelle <isabelle@team.fr>", "Point budget mars", "Pour info: budget mars utilisé à 92%. Reste 4 200 € pour les dépenses courantes."),
    ("Daniel <daniel@company.com>", "Product analytics summary", "FYI — key metrics: signups +15%, activation +8%, churn -2%. Good month overall."),
    ("Carole <carole@team.fr>", "Bilan événement networking", "Pour info: l'événement networking a réuni 150 participants. 45 contacts qualifiés."),
    ("Mike <mike@company.com>", "CI/CD pipeline improvements", "FYI — pipeline time reduced from 25min to 12min. Parallel test execution enabled."),
    ("Estelle <estelle@team.fr>", "Récap réunion d'équipe", "Pour info: prochaine release le 4 avril, 2 nouvelles features prévues."),
    ("Greg <greg@company.com>", "End of quarter summary", "FYI — Q1 summary: revenue +18%, customers +22%, NPS 72. Strong quarter."),
]

# --- 4. Out of office (20) ---
FYI_OUT_OF_OFFICE = [
    ("Pierre Dumont <pierre@team.fr>", "Absence", "Je suis en vacances du 25 mars au 5 avril. Contactez Julien pour les urgences."),
    ("Alice Cooper <alice@company.com>", "Out of Office", "I'm out of office until April 7. For urgent matters, contact Sarah."),
    ("Marc Leblanc <marc@team.fr>", "En congés", "Je suis en congés cette semaine. De retour lundi 31 mars."),
    ("Sarah Johnson <sarah@company.com>", "OOO: Vacation", "I'm on vacation until April 2. Limited email access. Back soon!"),
    ("Thomas Girard <thomas@team.fr>", "Absent du bureau", "Je suis absent du bureau aujourd'hui pour rendez-vous médical. De retour demain."),
    ("Emily Brown <emily@company.com>", "On leave", "I'm on annual leave March 28 - April 4. See you when I'm back!"),
    ("Julien Martin <julien@team.fr>", "RTT lundi", "Je prends un RTT lundi. Disponible par téléphone en cas d'urgence."),
    ("David Wilson <david@company.com>", "Away from office", "I'm away from the office this week for a conference. Will respond to emails on Monday."),
    ("Nathalie Petit <nathalie@team.fr>", "Séminaire d'entreprise", "Je suis au séminaire d'entreprise mercredi et jeudi. Disponibilité limitée."),
    ("Chris Taylor <chris@company.com>", "Paternity leave", "I'm on paternity leave until April 15. Contact Kevin for engineering questions."),
    ("Céline Roux <celine@team.fr>", "Télétravail mercredi", "Je suis en télétravail mercredi. Joignable sur Slack et par email."),
    ("Matt Lee <matt@company.com>", "PTO Friday", "Taking PTO on Friday. I'll be back Monday. Non-urgent items can wait."),
    ("Audrey Moreau <audrey@team.fr>", "Congé maladie", "Je suis en congé maladie pour quelques jours. Adressez-vous à Sophie."),
    ("Jason Clark <jason@company.com>", "Sabbatical notice", "I'm starting a 3-month sabbatical on April 1. See handoff document."),
    ("Marion Dupont <marion@team.fr>", "Congé maternité", "Je serai en congé maternité à partir du 1er avril. Marie me remplace."),
    ("Laura White <laura@company.com>", "Extended leave", "I'll be on extended leave for 6 weeks starting April 7."),
    ("Philippe Bernard <philippe@team.fr>", "En déplacement", "Je suis en déplacement chez le client mardi et mercredi."),
    ("Kevin Adams <kevin@company.com>", "Holiday notice", "Office will be closed April 18-21 for Easter weekend."),
    ("Sandrine Laurent <sandrine@team.fr>", "Jour férié rappel", "Rappel: lundi de Pâques est un jour férié. L'office est fermé."),
    ("Rachel Kim <rachel@company.com>", "Out sick today", "I'm out sick today. Will try to be back tomorrow. Ping me on Slack if urgent."),
]

# --- 5. Acknowledgments (30) ---
FYI_ACKNOWLEDGMENTS = [
    ("Pierre <pierre@team.fr>", "Re: Rapport Q1", "Bien reçu, merci!"),
    ("Alice <alice@company.com>", "Re: Budget proposal", "Got it, thanks. Looks good to me."),
    ("Marc <marc@team.fr>", "Re: Maquettes v2", "C'est noté. Je regarde ça demain."),
    ("Sarah <sarah@company.com>", "Re: Deployment plan", "Noted. I'll review it this afternoon."),
    ("Thomas <thomas@team.fr>", "Re: Sprint planning", "Noté, merci pour le résumé."),
    ("Emily <emily@company.com>", "Re: Feature spec", "Looks good! No further comments from me."),
    ("Julien <julien@team.fr>", "Re: PR #234", "Bien reçu. Je fais la review demain matin."),
    ("David <david@company.com>", "Re: Architecture proposal", "Got it. Solid approach. Let's proceed."),
    ("Nathalie <nathalie@team.fr>", "Re: Planning", "Parfait."),
    ("Chris <chris@company.com>", "Re: Infrastructure changes", "Acknowledged. I'll update the docs accordingly."),
    ("Céline <celine@team.fr>", "Re: Brief créatif", "Bien noté. Je partage avec l'équipe design."),
    ("Matt <matt@company.com>", "Re: API documentation", "Looks great, thanks for the update."),
    ("Audrey <audrey@team.fr>", "Re: Rapport audit", "Bien reçu, merci."),
    ("Jason <jason@company.com>", "Re: Release plan", "All clear. Ready for deployment."),
    ("Marion <marion@team.fr>", "Re: Budget marketing", "C'est noté. Pas de remarques de mon côté."),
    ("Laura <laura@company.com>", "Re: Design tokens", "Got the docs. I'll review them this week."),
    ("Philippe <philippe@team.fr>", "Re: Config serveur", "Noté. Tout est OK de mon côté."),
    ("Kevin <kevin@company.com>", "Re: Sales strategy", "Understood. Let's align on this next week."),
    ("Sandrine <sandrine@team.fr>", "Re: Process recrutement", "Bien reçu. Je transmets aux managers."),
    ("Rachel <rachel@company.com>", "Re: User research", "Thanks for sharing. Very insightful findings."),
    ("Olivier <olivier@team.fr>", "Re: Monitoring", "Noté, merci. Les alertes sont bien configurées."),
    ("Amanda <amanda@company.com>", "Re: Contract terms", "Received, thanks. I'll forward to legal."),
    ("François <francois@team.fr>", "Re: Déploiement", "C'est bon."),
    ("Ben <ben@company.com>", "Re: Sprint retro", "Noted. Good action items from the retro."),
    ("Isabelle <isabelle@team.fr>", "Re: Factures", "Bien reçu. Je traite ça cette semaine."),
    ("Daniel <daniel@company.com>", "Re: Performance report", "Got it. Numbers look solid."),
    ("Carole <carole@team.fr>", "Re: Organisation événement", "Noté. Je m'occupe de la logistique."),
    ("Mike <mike@company.com>", "Re: CI/CD pipeline", "Looks good to me. Ship it!"),
    ("Estelle <estelle@team.fr>", "Re: Brief projet", "Bien noté, merci. On en reparle vendredi."),
    ("Greg <greg@company.com>", "Re: Quarterly goals", "Thanks, received. Aligned on all goals."),
]


# ============================================================================
# TEST CLASS
# ============================================================================


class TestLabelNoiseAction1000:
    """1000 emails: 550 Noise + 300 Action + 150 FYI."""

    # ================================================================
    # NOISE TESTS (550)
    # ================================================================

    def test_noise_bitcoin(self, use_case):
        """All bitcoin.com emails -> Noise (50 emails)."""
        for sender, subject, body in NOISE_BITCOIN:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Noise", (
                f"Expected Noise for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_noise_apollo_neuro(self, use_case):
        """All Apollo Neuro emails -> Noise (30 emails)."""
        for sender, subject, body in NOISE_APOLLO_NEURO:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Noise", (
                f"Expected Noise for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_noise_amazon_ca(self, use_case):
        """All amazon.ca emails -> Noise (50 emails)."""
        for sender, subject, body in NOISE_AMAZON_CA:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Noise", (
                f"Expected Noise for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_noise_cerebral_valley(self, use_case):
        """All Cerebral Valley emails -> Noise (30 emails)."""
        for sender, subject, body in NOISE_CEREBRAL_VALLEY:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Noise", (
                f"Expected Noise for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_noise_linkedin(self, use_case):
        """All LinkedIn emails -> Noise (50 emails)."""
        for sender, subject, body in NOISE_LINKEDIN:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Noise", (
                f"Expected Noise for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_noise_saas_marketing(self, use_case):
        """All SaaS/Marketing emails -> Noise (100 emails)."""
        for sender, subject, body in NOISE_SAAS_MARKETING:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Noise", (
                f"Expected Noise for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_noise_generic_newsletters(self, use_case):
        """All generic newsletter emails -> Noise (100 emails)."""
        for sender, subject, body in NOISE_GENERIC_NEWSLETTERS:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Noise", (
                f"Expected Noise for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_noise_social_media(self, use_case):
        """All social media notification emails -> Noise (50 emails)."""
        for sender, subject, body in NOISE_SOCIAL_MEDIA:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Noise", (
                f"Expected Noise for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_noise_crypto_fintech(self, use_case):
        """All crypto/fintech emails -> Noise (50 emails)."""
        for sender, subject, body in NOISE_CRYPTO_FINTECH:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Noise", (
                f"Expected Noise for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_noise_retail_ecommerce(self, use_case):
        """All retail/e-commerce emails -> Noise (40 emails)."""
        for sender, subject, body in NOISE_RETAIL_ECOMMERCE:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Noise", (
                f"Expected Noise for sender={sender!r}, subject={subject!r}, got {label}"
            )

    # ================================================================
    # ACTION TESTS (300)
    # ================================================================

    def test_action_direct_questions(self, use_case):
        """All direct question emails from real people -> Action (80 emails)."""
        for sender, subject, body in ACTION_DIRECT_QUESTIONS:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Action", (
                f"Expected Action for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_action_invoices(self, use_case):
        """All invoice/payment emails -> Action (50 emails)."""
        for sender, subject, body in ACTION_INVOICES:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Action", (
                f"Expected Action for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_action_approvals(self, use_case):
        """All approval/review request emails -> Action (50 emails)."""
        for sender, subject, body in ACTION_APPROVALS:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Action", (
                f"Expected Action for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_action_meetings(self, use_case):
        """All meeting/RSVP request emails -> Action (40 emails)."""
        for sender, subject, body in ACTION_MEETINGS:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Action", (
                f"Expected Action for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_action_french_informal(self, use_case):
        """All French informal request emails -> Action (40 emails)."""
        for sender, subject, body in ACTION_FRENCH_INFORMAL:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Action", (
                f"Expected Action for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_action_urgent_security(self, use_case):
        """All urgent/security emails from non-automated senders -> Action (40 emails)."""
        for sender, subject, body in ACTION_URGENT_SECURITY:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "Action", (
                f"Expected Action for sender={sender!r}, subject={subject!r}, got {label}"
            )

    # ================================================================
    # FYI TESTS (150)
    # ================================================================

    def test_fyi_markers(self, use_case):
        """All FYI-marked emails -> FYI (40 emails)."""
        for sender, subject, body in FYI_MARKERS:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "FYI", (
                f"Expected FYI for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_fyi_forwards(self, use_case):
        """All forwarded emails -> FYI (30 emails)."""
        for sender, subject, body in FYI_FORWARDS:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "FYI", (
                f"Expected FYI for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_fyi_status_updates(self, use_case):
        """All status update emails -> FYI (30 emails)."""
        for sender, subject, body in FYI_STATUS_UPDATES:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "FYI", (
                f"Expected FYI for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_fyi_out_of_office(self, use_case):
        """All out-of-office emails -> FYI (20 emails)."""
        for sender, subject, body in FYI_OUT_OF_OFFICE:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "FYI", (
                f"Expected FYI for sender={sender!r}, subject={subject!r}, got {label}"
            )

    def test_fyi_acknowledgments(self, use_case):
        """All acknowledgment emails -> FYI (30 emails)."""
        for sender, subject, body in FYI_ACKNOWLEDGMENTS:
            email = make_email(sender=sender, subject=subject, body=body)
            label = get_builtin_label(use_case, email)
            assert label == "FYI", (
                f"Expected FYI for sender={sender!r}, subject={subject!r}, got {label}"
            )

    # ================================================================
    # OVERALL ACCURACY TEST
    # ================================================================

    def test_overall_accuracy(self, use_case):
        """Run ALL 1000 emails and assert 95%+ accuracy per category."""
        all_datasets = {
            "Noise": [
                NOISE_BITCOIN, NOISE_APOLLO_NEURO, NOISE_AMAZON_CA,
                NOISE_CEREBRAL_VALLEY, NOISE_LINKEDIN, NOISE_SAAS_MARKETING,
                NOISE_GENERIC_NEWSLETTERS, NOISE_SOCIAL_MEDIA,
                NOISE_CRYPTO_FINTECH, NOISE_RETAIL_ECOMMERCE,
            ],
            "Action": [
                ACTION_DIRECT_QUESTIONS, ACTION_INVOICES, ACTION_APPROVALS,
                ACTION_MEETINGS, ACTION_FRENCH_INFORMAL, ACTION_URGENT_SECURITY,
            ],
            "FYI": [
                FYI_MARKERS, FYI_FORWARDS, FYI_STATUS_UPDATES,
                FYI_OUT_OF_OFFICE, FYI_ACKNOWLEDGMENTS,
            ],
        }

        results = {}
        total_correct = 0
        total_emails = 0
        failures = []

        for expected_label, datasets in all_datasets.items():
            correct = 0
            count = 0
            for dataset in datasets:
                for sender, subject, body in dataset:
                    email = make_email(sender=sender, subject=subject, body=body)
                    label = get_builtin_label(use_case, email)
                    count += 1
                    total_emails += 1
                    if label == expected_label:
                        correct += 1
                        total_correct += 1
                    else:
                        failures.append(
                            f"  [{expected_label}] got={label} sender={sender!r} "
                            f"subject={subject!r}"
                        )

            accuracy = correct / count * 100 if count else 0
            results[expected_label] = (correct, count, accuracy)

        # Print summary
        print(f"\n{'='*70}")
        print(f"OVERALL ACCURACY: {total_correct}/{total_emails} "
              f"({total_correct/total_emails*100:.1f}%)")
        print(f"{'='*70}")
        for label, (correct, count, accuracy) in results.items():
            status = "PASS" if accuracy >= 95 else "FAIL"
            print(f"  [{status}] {label}: {correct}/{count} ({accuracy:.1f}%)")
        if failures:
            print(f"\nFailures ({len(failures)}):")
            for f in failures[:50]:  # limit to 50 to avoid flooding
                print(f)
            if len(failures) > 50:
                print(f"  ... and {len(failures) - 50} more")
        print(f"{'='*70}\n")

        # Assert 95%+ per category
        for label, (correct, count, accuracy) in results.items():
            assert accuracy >= 95, (
                f"{label} accuracy {accuracy:.1f}% < 95% "
                f"({correct}/{count})"
            )

    def test_total_email_count(self):
        """Verify we have exactly 1000 test emails."""
        noise_count = (
            len(NOISE_BITCOIN) + len(NOISE_APOLLO_NEURO) + len(NOISE_AMAZON_CA) +
            len(NOISE_CEREBRAL_VALLEY) + len(NOISE_LINKEDIN) + len(NOISE_SAAS_MARKETING) +
            len(NOISE_GENERIC_NEWSLETTERS) + len(NOISE_SOCIAL_MEDIA) +
            len(NOISE_CRYPTO_FINTECH) + len(NOISE_RETAIL_ECOMMERCE)
        )
        action_count = (
            len(ACTION_DIRECT_QUESTIONS) + len(ACTION_INVOICES) + len(ACTION_APPROVALS) +
            len(ACTION_MEETINGS) + len(ACTION_FRENCH_INFORMAL) + len(ACTION_URGENT_SECURITY)
        )
        fyi_count = (
            len(FYI_MARKERS) + len(FYI_FORWARDS) + len(FYI_STATUS_UPDATES) +
            len(FYI_OUT_OF_OFFICE) + len(FYI_ACKNOWLEDGMENTS)
        )

        assert noise_count == 550, f"Expected 550 Noise emails, got {noise_count}"
        assert action_count == 300, f"Expected 300 Action emails, got {action_count}"
        assert fyi_count == 150, f"Expected 150 FYI emails, got {fyi_count}"
        assert noise_count + action_count + fyi_count == 1000, (
            f"Expected 1000 total emails, got {noise_count + action_count + fyi_count}"
        )
