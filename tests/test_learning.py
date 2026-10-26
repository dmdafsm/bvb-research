from bvb import learning


def test_concepts_are_consistent():
    keys = [c.key for c in learning.CONCEPTS]
    assert len(keys) == len(set(keys))
    for c in learning.CONCEPTS:
        assert c.topic in learning.TOPICS, c.key
        assert c.pages and set(c.pages) <= set(learning.PAGES), c.key
        assert c.summary.strip(), c.key
        for label, url in c.links:
            assert label and url.startswith("https://"), c.key


def test_formulas_have_balanced_braces():
    for c in learning.CONCEPTS:
        for f in c.formulas:
            depth = 0
            for ch in f.replace(r"\{", "").replace(r"\}", ""):
                depth += {"{": 1, "}": -1}.get(ch, 0)
                assert depth >= 0, (c.key, f)
            assert depth == 0, (c.key, f)
        # $ pentru LaTeX inline in markdown trebuie sa vina in perechi
        assert (c.method + c.summary).count("$") % 2 == 0, c.key


def test_every_page_has_concepts():
    for page in learning.PAGES:
        assert learning.search("", [page]), page


def test_search_filters_text_and_pages():
    assert {c.key for c in learning.search("ledoit")} == {"covariance", "var"}  # VaR parametric o foloseste
    assert all("Screener" in c.pages for c in learning.search("", ["Screener"]))
    assert learning.search("nu exista asa ceva") == []
    groups = learning.by_topic(learning.search("", ["Portofoliu"]))
    assert list(groups) == [t for t in learning.TOPICS if t in groups]
