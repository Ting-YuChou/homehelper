from collections import defaultdict

from homehelper_evals.splits import assign_split, build_splits, group_key, load_rows, load_splits


def test_tone_variants_share_a_split() -> None:
    assert group_key("  The dryer  won't START. ") == group_key("the dryer won't start.")
    assert assign_split("The dryer won't start.") == assign_split("the  dryer won't start.")


def test_committed_splits_match_dataset_and_keep_groups_together() -> None:
    rows = load_rows()
    committed = load_splits()
    assert committed == build_splits(rows)["assignments"]

    splits_by_group: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        splits_by_group[group_key(row["scenario"])].add(committed[str(row["id"])])
    assert all(len(splits) == 1 for splits in splits_by_group.values())

    dev_share = sum(split == "dev" for split in committed.values()) / len(committed)
    assert 0.15 < dev_share < 0.25
