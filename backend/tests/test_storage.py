from app.services.storage import safe_filename


def test_path_traversal_is_stripped():
    assert safe_filename("../../etc/passwd") == "etc_passwd" or "passwd" in safe_filename("../../etc/passwd")
    assert "/" not in safe_filename("../../etc/passwd")
    assert "\\" not in safe_filename(r"..\..\windows\system32\cmd.exe")


def test_unsafe_characters_are_replaced():
    assert safe_filename("my changes (v2).xlsx") == "my_changes_v2_.xlsx"


def test_empty_name_falls_back():
    assert safe_filename("...", "changes.xlsx") == "changes.xlsx"
