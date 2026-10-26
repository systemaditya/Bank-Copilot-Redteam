from app.policy import PolicyIndex


def test_loads_all_policy_documents(settings):
    index = PolicyIndex.from_directory(settings.policy_docs_dir)
    sources = {section.source for section in index.sections}
    assert sources == {"fees.md", "transfers.md", "accounts-faq.md", "privacy-security.md"}
    assert len(index.sections) >= 12


def test_finds_daily_transfer_limit(settings):
    results = PolicyIndex.from_directory(settings.policy_docs_dir).search("daily transfer limit")
    assert results[0].title == "Daily transfer limits"
    assert "$3,000.00" in results[0].text


def test_finds_monthly_fee(settings):
    results = PolicyIndex.from_directory(settings.policy_docs_dir).search("monthly account fees")
    assert results[0].title == "Monthly account fees"


def test_stopword_only_query_returns_nothing(settings):
    assert PolicyIndex.from_directory(settings.policy_docs_dir).search("what is the") == []
