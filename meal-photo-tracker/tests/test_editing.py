from mealtrack.editing import items_from_rows


def row(**kw):
    base = dict(name="Oats", grams=40, kcal=150, kcal_low=130, kcal_high=170,
                protein_g=5, carbs_g=27, fat_g=3)
    base.update(kw)
    return base


def test_blank_rows_are_dropped():
    blank = dict(name=None, grams=float("nan"), kcal=float("nan"), kcal_low=None,
                 kcal_high=None, protein_g=None, carbs_g=None, fat_g=None)
    assert len(items_from_rows([row(), blank])) == 1


def test_hand_typed_row_without_range_is_a_point_value():
    items = items_from_rows([row(kcal=200, kcal_low=0, kcal_high=0)])
    assert items[0].kcal_low == items[0].kcal_high == 200


def test_range_is_widened_when_user_raises_kcal():
    items = items_from_rows([row(kcal=300)])
    assert items[0].kcal_high == 300


def test_nan_numbers_become_zero():
    items = items_from_rows([row(protein_g=float("nan"))])
    assert items[0].protein_g == 0


def test_nameless_row_with_numbers_gets_placeholder_name():
    assert items_from_rows([row(name="")])[0].name == "unknown item"
