"""One need per zone: normal cheeks with low moisture read 'hydration' once, not twice."""
from app import needs as N


def zones(t, u):
    return {"t_zone": N.ZoneRead("t_zone", t, False, "face"), "u_zone": N.ZoneRead("u_zone", u, False, "face")}


def keys(needs):
    return [(n.key, n.zone) for n in needs]


def test_normal_cheeks_with_low_moisture_get_one_need():
    needs = N.build_needs(zones("oily", "normal"), {"moisture": 40.0})
    cheeks = [n for n in needs if n.zone == "u_zone"]
    assert len(cheeks) == 1 and cheeks[0].key == "hydration"
    assert "zone type" in cheeks[0].from_ and "moisture" in cheeks[0].from_


def test_no_zone_ever_has_two_needs_from_the_same_group():
    groups = [set(g) for g in N.data()["same_need"]]
    for t in ("oily", "normal", "dry", "combination"):
        for u in ("oily", "normal", "dry"):
            try:
                ns = N.build_needs(zones(t, u), {"moisture": 40.0, "oiliness": 40.0})
            except KeyError:
                continue
            ks = keys(ns)
            assert len(ks) == len(set(ks))
            for g in groups:
                for z in ("t_zone", "u_zone", "whole"):
                    assert sum(1 for k, zz in ks if zz == z and k in g) <= 1, ks
