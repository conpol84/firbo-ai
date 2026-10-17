from benchmarks.memory_recall import evaluate, load_fixture, rank


def test_memory_fixture_contains_no_real_user_data():
    corpus = load_fixture()
    assert len(corpus) == 4
    assert all(item["id"].startswith("m") for item in corpus)


def test_hybrid_recovers_greeklish_preference():
    corpus = load_fixture()
    assert rank("skoteino thema sta tools", corpus, mode="hybrid")[0][0] == "m3"


def test_hybrid_recall_is_not_worse_than_lexical():
    result = evaluate()
    assert result["hybrid_recall_at_1"] >= result["lexical_recall_at_1"]
    assert result["hybrid_recall_at_1"] >= 0.75
