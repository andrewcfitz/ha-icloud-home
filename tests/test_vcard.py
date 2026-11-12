from custom_components.icloud_home import vcard

from .conftest import GROUP, ME, OTHER

ADDRESS = {
    "street": "123 Campground Ln, Site 42",
    "city": "Fredericksburg",
    "state": "TX",
    "postal_code": "78624",
    "country": "United States",
}


def test_replaces_only_home_adr():
    out = vcard.set_home_address(ME, ADDRESS)
    unfolded = vcard.unfold(out)
    assert (
        "item1.ADR;type=HOME;type=pref:;;123 Campground Ln\\, Site 42;Fredericksburg;"
        "TX;78624;United States" in unfolded
    )
    assert "item2.ADR;type=WORK:;;9 Work St;Worktown;TX;75002;United States" in unfolded
    assert "1 Old Rd" not in unfolded
    assert all(len(line.encode()) <= 75 for line in out.split("\r\n"))


def test_appends_home_adr_when_missing():
    out = vcard.unfold(vcard.set_home_address(OTHER, ADDRESS))
    assert "ADR;type=HOME:;;123 Campground Ln\\, Site 42;" in out
    assert out.index("ADR;type=HOME") < out.index("END:VCARD")


def test_second_write_is_a_no_op():
    once = vcard.set_home_address(ME, ADDRESS)
    assert vcard.same(once, vcard.set_home_address(once, ADDRESS))
    assert not vcard.same(ME, once)


def test_fold_does_not_split_multibyte_characters():
    line = "NOTE:" + "é" * 100
    folded = vcard.fold(line)
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))
    assert vcard.unfold(folded) == line


def test_full_name_and_group_detection():
    assert vcard.full_name(ME) == "Pat Tester"
    assert vcard.is_group(GROUP)
    assert not vcard.is_group(ME)
