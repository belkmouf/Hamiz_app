from pulse.adjoin import UNATTRIBUTED, join


def sp(ad, usd, campaign="C1"):
    return {"ad_name": ad, "spend_usd": usd, "campaign_name": campaign}


def od(stage, ad=None, campaign=None, source=None, total=4500):
    return {"ad": ad, "campaign": campaign, "source": source, "stage": stage, "total": total}


def test_join_on_utm_content_case_and_space_insensitive():
    spend, groups, other, _ = join([sp("Ad One", 10)], [od("confirmed", ad="ad  one", source="fb"), od("pending", ad="Ad One")])
    assert spend == {"Ad One": 10}
    assert groups["Ad One"]["raw"] == 2 and groups["Ad One"]["conf"] == 1 and groups["Ad One"]["pending"] == 1
    assert groups["Ad One"]["val"] == [4500]


def test_no_utm_goes_to_unattributed():
    _, groups, _, _ = join([sp("A", 5)], [od("confirmed")])
    assert groups[UNATTRIBUTED]["raw"] == 1


def test_other_channels_left_out():
    _, groups, other, _ = join([sp("A", 5)], [od("confirmed", source="google", campaign="Search")])
    assert other == 1 and UNATTRIBUTED not in groups


def test_campaign_fallback_when_campaign_has_no_ad_level_tracking():
    spend, groups, _, members = join([sp("A", 5, "Lampes"), sp("B", 7, "Lampes")],
                                     [od("confirmed", campaign="lampes", source="facebook"), od("delivered", campaign="Lampes")])
    assert spend == {"Lampes": 12}
    assert groups["Lampes"]["approx"] is True and groups["Lampes"]["raw"] == 2 and groups["Lampes"]["deliv"] == 1
    assert sorted(members["Lampes"]) == ["A", "B"]


def test_campaign_only_orders_are_unattributed_when_campaign_tracks_ads():
    spend, groups, _, _ = join([sp("A", 5, "Lampes"), sp("B", 7, "Lampes")],
                               [od("confirmed", ad="A", campaign="Lampes"), od("confirmed", campaign="Lampes", source="fb")])
    assert spend == {"A": 5, "B": 7}
    assert groups["A"]["raw"] == 1 and groups[UNATTRIBUTED]["raw"] == 1


def test_meta_source_without_match_is_unattributed():
    _, groups, other, _ = join([sp("A", 5)], [od("pending", source="fb", campaign="Old campaign")])
    assert groups[UNATTRIBUTED]["raw"] == 1 and other == 0


def test_url_encoded_utm_content_matches():
    spend, groups, _, _ = join([sp("Bundle 2+1 v1", 4)], [od("confirmed", ad="Bundle+2%2B1+v1"), od("confirmed", ad="bundle 2+1 v1")])
    assert groups["Bundle 2+1 v1"]["raw"] == 2 and UNATTRIBUTED not in groups
